"""薄执行模块：单活跃运行准入 + 执行记录 sqlite 落库。

个人自用单实例设计：
- 单事件循环内「检查 active_run is None → 立即赋值」天然原子，无需额外锁。
- 执行记录用 stdlib sqlite3 同步函数，调用方一律经 asyncio.to_thread。
- 替代原 PR 的 ExecutionCoordinator + ExecutionStore（752 行）。
"""

import asyncio
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app_state import ActiveRun, AppState
from maa_worker.event_service import load_settings
from maa_worker.pretask_service import PretaskError, PretaskStopped
from models.scheduler import (
    ExecutionOrigin,
    ExecutionStatus,
    ManualStartPayload,
    ScheduledTask,
    StartConflict,
    TaskExecution,
)
from models.task_config import (
    find_unknown_task_names,
    normalize_global_option_values,
    normalize_task_execution_payload,
)

logger = logging.getLogger(__name__)

EXECUTIONS_MAX_RECORDS = 1000


@dataclass
class Admission:
    """执行准入结果"""

    accepted: bool
    run_id: str | None = None
    conflict: StartConflict | None = None
    skip_status: str | None = None

    invalid_task_names: list[str] | None = None


# ---------------------------------------------------------------------------
# 执行记录持久化（stdlib sqlite3，同步函数）
# ---------------------------------------------------------------------------


def init_db(path: Path) -> None:
    """初始化执行历史表"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduler_executions (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                task_name TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT 'in_app',
                occurrence_id TEXT,
                status TEXT NOT NULL,
                blocker_task_name TEXT,
                error_message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_scheduler_executions_started_at
            ON scheduler_executions(started_at DESC)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_scheduler_executions_task_id
            ON scheduler_executions(task_id)
            """
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


async def _record_prestart_cancel(db_path: Path, run_id: str) -> None:
    """fire-and-forget 落库取消记录（与 _record_skip 一致，sqlite I/O 移出事件循环）。"""
    try:
        await asyncio.to_thread(
            finish_execution, db_path, run_id, "stopped", "运行被取消"
        )
    except Exception as e:
        logger.error(f"补记取消记录失败: {e}")


def add_execution(path: Path, execution: TaskExecution) -> None:
    """写入执行记录并裁剪超量历史"""
    with sqlite3.connect(path) as db:
        db.execute(
            """
            INSERT INTO scheduler_executions
            (id, task_id, task_name, origin, occurrence_id,
             status, blocker_task_name, error_message,
             started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution.id,
                execution.task_id,
                execution.task_name,
                execution.origin,
                execution.occurrence_id,
                execution.status,
                execution.blocker_task_name,
                execution.error_message,
                _to_iso(execution.started_at),
                _to_iso(execution.finished_at),
            ),
        )
        db.execute(
            """
            DELETE FROM scheduler_executions
            WHERE id NOT IN (
                SELECT id FROM scheduler_executions
                ORDER BY started_at DESC, id DESC
                LIMIT ?
            )
            """,
            (EXECUTIONS_MAX_RECORDS,),
        )


def finish_execution(
    path: Path,
    run_id: str,
    status: ExecutionStatus,
    error: str | None = None,
) -> None:
    """收尾执行记录"""
    with sqlite3.connect(path) as db:
        db.execute(
            """
            UPDATE scheduler_executions
            SET status = ?, finished_at = ?, error_message = ?
            WHERE id = ?
            """,
            (status, _to_iso(_utc_now()), error, run_id),
        )


def list_executions(path: Path, limit: int = 50) -> list[TaskExecution]:
    """按开始时间倒序读取执行历史"""
    if not path.exists():
        return []
    with sqlite3.connect(path) as db:
        rows = db.execute(
            """
            SELECT id, task_id, task_name, origin, occurrence_id,
                   status, blocker_task_name, error_message, started_at, finished_at
            FROM scheduler_executions
            ORDER BY started_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    executions: list[TaskExecution] = []
    for row in rows:
        executions.append(
            TaskExecution(
                id=row[0],
                task_id=row[1],
                task_name=row[2],
                origin=row[3] or "in_app",
                occurrence_id=row[4],
                status=row[5],
                blocker_task_name=row[6],
                error_message=row[7],
                started_at=datetime.fromisoformat(row[8]),
                finished_at=datetime.fromisoformat(row[9]) if row[9] else None,
            )
        )
    return executions


# ---------------------------------------------------------------------------
# 准入与执行
# ---------------------------------------------------------------------------


def _conflict_from_active(state: AppState) -> StartConflict:
    """按当前活跃运行来源构造冲突信息"""
    active = state.active_run
    assert active is not None
    code = "busy_manual" if active.origin == "manual" else "busy_scheduled"
    return StartConflict(
        code=code,
        message=(
            "已有手动任务正在运行" if code == "busy_manual" else "已有调度任务正在运行"
        ),
        active_run_id=active.run_id,
        active_task_name=active.task_name,
        active_origin=active.origin,
    )


async def _record_skip(
    state: AppState,
    task_id: str | None,
    task_name: str,
    origin: ExecutionOrigin,
    status: ExecutionStatus,
    occurrence_id: str | None = None,
    error: str | None = None,
) -> Admission:
    """落库一条跳过/失败记录并返回拒绝准入"""
    run_id = str(uuid.uuid4())
    execution = TaskExecution(
        id=run_id,
        task_id=task_id,
        task_name=task_name,
        origin=origin,
        occurrence_id=occurrence_id,
        blocker_task_name=state.active_run.task_name if state.active_run else None,
        started_at=_utc_now(),
        finished_at=_utc_now(),
        status=status,
        error_message=error,
    )
    # fire-and-forget 落库（脱离事件循环，避免阻塞）
    try:
        await asyncio.to_thread(add_execution, state.scheduler_db_path, execution)
    except Exception as e:
        logger.error(f"写入跳过记录失败: {e}")
    return Admission(accepted=False, run_id=run_id, skip_status=status)


async def record_fire_time_rejection(
    state: AppState, task: ScheduledTask, reason: str
) -> None:
    """fire-time 载荷/身份失效：落库一条 failed 记录并经现有通知渠道告警。

    归属用户配置漂移，不产生 Sentry Error Event（调用方保证不派发执行）。
    """
    run_id = str(uuid.uuid4())
    execution = TaskExecution(
        id=run_id,
        task_id=task.id,
        task_name=task.name,
        origin="in_app",
        started_at=_utc_now(),
        finished_at=_utc_now(),
        status="failed",
        error_message=reason,
    )
    try:
        await asyncio.to_thread(add_execution, state.scheduler_db_path, execution)
    except Exception as e:
        logger.error(f"写入 fire-time 拒绝记录失败: {e}")
    worker = state.worker
    if worker is not None:
        try:
            await asyncio.to_thread(
                worker.events.send_notification,
                "定时任务触发失败",
                f"{task.name}: {reason}",
                level="error",
            )
        except Exception as e:
            logger.error(f"发送 fire-time 拒绝通知失败: {e}")


async def submit_manual(state: AppState, payload: ManualStartPayload) -> Admission:
    """手动启动准入"""
    telemetry = getattr(state, "telemetry_service", None)
    worker = state.worker
    if worker is not None and getattr(worker, "interface", None) is not None:
        unknown_names = find_unknown_task_names(worker.interface, payload.task_list)
        if unknown_names:
            if telemetry is not None:
                telemetry.record_execution_rejected(
                    origin="manual", error_code="config_error"
                )
            return Admission(
                accepted=False,
                invalid_task_names=unknown_names,
            )
    if state.update_in_progress:
        run_id = str(uuid.uuid4())
        if telemetry is not None:
            telemetry.record_execution_rejected(
                run_id=run_id, origin="manual", error_code="mwu.execution.rejected"
            )
        return Admission(
            accepted=False,
            run_id=run_id,
            conflict=StartConflict(
                code="update_in_progress",
                message="应用正在更新，请稍后再试",
                active_run_id="",
                active_task_name="",
                active_origin="manual",
            ),
        )
    if state.active_run is not None:
        conflict = _conflict_from_active(state)
        if telemetry is not None:
            telemetry.record_execution_rejected(
                origin="manual", error_code=conflict.code
            )
        return Admission(accepted=False, conflict=conflict)

    run_id = str(uuid.uuid4())
    state.active_run = ActiveRun(
        run_id=run_id,
        origin="manual",
        task_name=payload.task_list[0] if payload.task_list else "手动任务",
    )
    try:
        execution = TaskExecution(
            id=run_id,
            task_id=None,
            task_name=state.active_run.task_name,
            origin="manual",
            started_at=_utc_now(),
            status="running",
        )
        await asyncio.to_thread(add_execution, state.scheduler_db_path, execution)
        state.active_execution_task = asyncio.create_task(
            _complete_run(state, run_id, payload)
        )

        # 防御：若协程在首次调度前被取消，finally 不会执行，立即清槽并补记
        def _guard_prestart_cancel(t: asyncio.Task) -> None:
            if (
                t.cancelled()
                and state.active_run is not None
                and state.active_run.run_id == run_id
            ):
                state.active_run = None
                state.active_execution_task = None
                asyncio.get_running_loop().create_task(
                    _record_prestart_cancel(state.scheduler_db_path, run_id)
                )

        state.active_execution_task.add_done_callback(_guard_prestart_cancel)
    except BaseException:
        # 落库失败或准入阶段被取消：立即清槽，避免槽位永久占用（后续每次启动都被拒 busy）
        if state.active_run is not None and state.active_run.run_id == run_id:
            state.active_run = None
        state.active_execution_task = None
        raise
    return Admission(accepted=True, run_id=run_id)


async def submit_scheduled(
    state: AppState,
    task: ScheduledTask,
    origin: ExecutionOrigin,
) -> Admission:
    """调度触发准入（应用内 / 原生冷启动）；时间仅记录实际开始执行时刻"""
    occurrence_id = f"{task.id}:{_utc_now().isoformat()}"

    telemetry = getattr(state, "telemetry_service", None)
    worker = state.worker
    if worker is not None and getattr(worker, "interface", None) is not None:
        unknown_names = find_unknown_task_names(worker.interface, task.task_list)
        if unknown_names:
            if telemetry is not None:
                telemetry.record_execution_rejected(
                    origin=origin, error_code="config_error"
                )
            return await _record_skip(
                state,
                task.id,
                task.name,
                origin,
                "failed",
                occurrence_id=occurrence_id,
                error=(
                    "任务名称不在当前 interface 中: "
                    + ", ".join(unknown_names)
                    + f"（job {task.id}）"
                ),
            )

    if state.update_in_progress:
        if telemetry is not None:
            telemetry.record_execution_rejected(
                origin=origin, error_code="mwu.execution.rejected"
            )
        return await _record_skip(
            state,
            task.id,
            task.name,
            origin,
            "skipped_update_in_progress",
            occurrence_id=occurrence_id,
            error="应用正在更新",
        )

    if state.active_run is not None:
        skip_status: ExecutionStatus = (
            "skipped_busy_manual"
            if state.active_run.origin == "manual"
            else "skipped_busy_scheduled"
        )
        if telemetry is not None:
            telemetry.record_execution_rejected(origin=origin, error_code=skip_status)
        return await _record_skip(
            state,
            task.id,
            task.name,
            origin,
            skip_status,
            occurrence_id=occurrence_id,
            error=f"与运行中的任务冲突: {state.active_run.task_name}",
        )

    run_id = str(uuid.uuid4())
    state.active_run = ActiveRun(
        run_id=run_id,
        origin=origin,
        task_name=task.name,
        occurrence_id=occurrence_id,
    )
    try:
        execution = TaskExecution(
            id=run_id,
            task_id=task.id,
            task_name=task.name,
            origin=origin,
            occurrence_id=occurrence_id,
            started_at=_utc_now(),
            status="running",
        )
        await asyncio.to_thread(add_execution, state.scheduler_db_path, execution)

        # Do not manufacture an invalid empty Adb device when historical or
        # incomplete scheduled-task records omit their device configuration.
        # Passing no payload through to _complete_run keeps the normal failure
        # recording/event path without bypassing ManualStartPayload validation.
        payload = (
            ManualStartPayload(
                task_identity="name",
                task_list=task.task_list,
                task_options=task.task_options,
                preTasks=task.preTasks,
                controller_name=task.controller_name or task.device.controller_name,
                device=task.device,
                resource_name=task.resource_name or "",
            )
            if task.device is not None
            else None
        )
        state.active_execution_task = asyncio.create_task(
            _complete_run(state, run_id, payload, task_list=task.task_list)
        )

        # 防御：若协程在首次调度前被取消，finally 不会执行，立即清槽并补记
        def _guard_prestart_cancel(t: asyncio.Task) -> None:
            if (
                t.cancelled()
                and state.active_run is not None
                and state.active_run.run_id == run_id
            ):
                state.active_run = None
                state.active_execution_task = None
                asyncio.get_running_loop().create_task(
                    _record_prestart_cancel(state.scheduler_db_path, run_id)
                )

        state.active_execution_task.add_done_callback(_guard_prestart_cancel)
    except BaseException:
        # 落库失败或准入阶段被取消：立即清槽，避免槽位永久占用（后续每次启动都被拒 busy）
        if state.active_run is not None and state.active_run.run_id == run_id:
            state.active_run = None
        state.active_execution_task = None
        raise
    return Admission(accepted=True, run_id=run_id)


async def stop_active(state: AppState) -> bool:
    """请求停止当前活跃运行；无活跃运行返回 False"""
    active = state.active_run
    if active is None:
        return False
    if state.worker is not None:
        # tasks.stop() 内部轮询（time.sleep(0.5)），脱离事件循环执行
        await asyncio.to_thread(state.worker.tasks.stop)
    # 任务线程尚未启动时直接取消后台协程，避免前置/设备准备结束后继续启动任务。
    # tasks.stop() 已置 stop_flag 并终止正在运行的前置进程。
    if active.started is False:
        task = state.active_execution_task
        if task is not None and not task.done():
            task.cancel()
    # 后台协程在 finally 中清槽；此处不等待，立即返回
    return True


async def _complete_run(
    state: AppState,
    run_id: str,
    payload: ManualStartPayload | None,
    *,
    task_list: list[str] | None = None,
) -> None:
    """后台执行协程：前置任务 → 设备准备 → 任务运行 → 落库收尾 → 清槽"""
    worker = state.worker
    status: ExecutionStatus = "failed"
    error: str | None = None
    task_started = False
    suppress_prepare_telemetry = False
    event_task_list = payload.task_list if payload is not None else (task_list or [])
    active_run = state.active_run
    telemetry = getattr(state, "telemetry_service", None)
    if telemetry is not None:
        try:
            telemetry.start_run(
                run_id,
                active_run.origin if active_run is not None else "in_app",
                event_task_list,
            )
        except Exception:
            logger.debug("启动遥测 run 事务失败", exc_info=True)
    try:
        if worker is None:
            raise RuntimeError("Worker 未就绪")

        # 1. 校验设备/资源配置
        if payload is None or not payload.device or not payload.resource_name:
            raise RuntimeError("设备或资源配置缺失")

        # 2. 先规范化载荷并确认存在可运行任务，避免任务为空/失效时仍执行前置命令
        normalized_task_list, normalized_task_options, normalized_pre_tasks = (
            normalize_task_execution_payload(
                payload.task_list,
                payload.task_options,
                worker.interface,
                payload.preTasks,
            )
        )
        if not normalized_task_list:
            raise RuntimeError("任务列表为空")

        global_values = (
            state.settings.globalOptionValues if state.settings is not None else {}
        ) or {}
        normalized_global_options = normalize_global_option_values(
            global_values,
            worker.interface,
        )
        if telemetry is not None:
            try:
                telemetry.set_run_context(
                    run_id,
                    controller_type=(
                        payload.device.device_type
                        if payload is not None and payload.device
                        else None
                    ),
                    resource_name=payload.resource_name
                    if payload is not None
                    else None,
                )
            except Exception:
                logger.debug("设置遥测 run 上下文失败", exc_info=True)

        # 3-5. 准备临界区：权限 → 释放旧连接 → PI pretask + 用户命令 →
        # connect + set_resource。preparation_lock 与直接 device/resource API 互斥。
        # stop_flag 由 TaskService.start() 在任务线程启动时重置；此处不得重置，
        # 否则 stop_active() 在准入后、本阶段前设置的停止请求会被吞掉。
        effective_controller = payload.controller_name or payload.device.controller_name
        device_model = worker.device.build_device_model_from_config(
            payload.device.controller_name,
            payload.device.device_type,
            payload.device.device_address,
        )
        async with state.preparation_lock:
            # 获取锁后重查：准入后可能已被停止/更新/关停
            if state.active_run is None or state.active_run.run_id != run_id:
                raise PretaskStopped("运行已被取代或取消")
            if state.update_in_progress or state.is_shutting_down:
                raise PretaskStopped("更新或关停中，运行终止")

            # PI pretask + 用户命令 + 低层 connect（不加载 resource）。
            # shield 包裹：协程被取消时仍等待 pretask 线程退出后再传播取消，
            # 避免 finally 提前清槽导致新运行与未退出的 pretask 进程并发。
            try:
                prepared = await asyncio.shield(
                    asyncio.to_thread(
                        worker.device.prepare_connection,
                        device_model,
                        payload.resource_name,
                        normalized_global_options,
                        normalized_pre_tasks,
                    )
                )
            except PretaskStopped:
                raise
            except PretaskError as exc:
                if worker.task_state.stop_flag:
                    raise PretaskStopped(str(exc)) from exc
                raise RuntimeError(str(exc)) from exc
            if not prepared:
                raise RuntimeError(
                    "设备准备失败: "
                    + (worker.device_state.last_device_error or "未知错误")
                )

            # set_resource + 按设置重试（重试只重试 connect+set_resource，
            # 不重放已成功的准备程序）
            settings = load_settings()
            max_retry = settings.runtime.maxRetryCount
            retry_interval = settings.runtime.retryInterval
            connected = False
            last_err: Exception | None = None
            for attempt in range(1, max_retry + 1):
                try:
                    if not worker.device_state.connected:
                        if not await asyncio.to_thread(
                            worker.device.connect, device_model
                        ):
                            raise RuntimeError("connect() 返回 False")
                    # prepare_connection 复用 locked 上下文时 resource 已加载，
                    # set_resource() 对 locked 状态一律拒绝，重试只会耗尽次数。
                    # 仅当 resource 未加载（新连接）时才真正调用 set_resource()。
                    if (
                        worker.device_state.current_resource_name
                        != payload.resource_name
                    ):
                        if not await asyncio.to_thread(
                            worker.device.set_resource, payload.resource_name
                        ):
                            raise RuntimeError("set_resource() 返回 False")
                    connected = True
                    break
                except Exception as e:
                    last_err = e
                    if attempt < max_retry:
                        worker.events.send_log(f"连接失败，第 {attempt} 次重试...: {e}")
                        await asyncio.sleep(retry_interval)
            if not connected:
                await asyncio.to_thread(worker.device.reset_connection_state)
                raise RuntimeError(f"设备连接失败: {last_err}")

        # 6. 启动任务线程
        if not worker.tasks.start(
            normalized_task_list,
            normalized_task_options,
            task_name=state.active_run.task_name if state.active_run else None,
            pre_tasks=normalized_pre_tasks,
            global_options=normalized_global_options,
        ):
            if (
                worker.task_state.stop_flag
                or state.update_in_progress
                or state.is_shutting_down
            ):
                raise PretaskStopped("运行已终止")
            # A second legacy/parallel task admission is a busy gate, not a
            # preparation failure and must not create a Sentry Error event.
            suppress_prepare_telemetry = bool(worker.task_state.running)
            raise RuntimeError("任务启动失败（可能已有任务在运行）")
        # 任务线程已启动：run_process 自行发出终端事件；标记以便停止/失败时不重复发、不误取消
        task_started = True
        if state.active_run is not None and state.active_run.run_id == run_id:
            state.active_run.started = True

        # 6. 轮询等待结束（stop_flag 由 worker 内部轮询处理中途停止）
        while worker.task_state.running:
            await asyncio.sleep(1)

        last_status = getattr(worker.task_state, "last_status", "failed")
        last_error = getattr(worker.task_state, "last_error", None)
        if last_status == "success":
            status = "success"
        elif last_status == "stopped":
            status = "stopped"
            error = last_error or "任务已终止"
        else:
            status = "failed"
            error = last_error or "任务执行失败"

    except PretaskStopped:
        status = "stopped"
        error = "任务已终止"
        if worker is not None:
            worker.events.send_log(error)
            if not task_started:
                try:
                    await asyncio.to_thread(
                        worker.events.emit_task_failed, event_task_list, error
                    )
                except Exception as emit_err:
                    logger.error(f"发送任务停止事件失败: {emit_err}")
    except Exception as e:
        status = "failed"
        error = str(e)
        logger.error(f"执行运行 {run_id} 失败: {e}")
        if (
            telemetry is not None
            and not task_started
            and not suppress_prepare_telemetry
        ):
            try:
                telemetry.capture_prepare_failed(
                    run_id,
                    e,
                    task_name=event_task_list[0] if event_task_list else None,
                )
            except Exception:
                logger.debug("发送遥测准备失败事件失败", exc_info=True)
        if worker is not None:
            worker.events.send_log(f"任务执行失败: {e}")
            if not task_started:
                # 前置阶段失败（run_process 未启动、未发终端事件）：补发 task.failed，
                # 否则前端 TaskRunning 在 accept 后被置位却无 task.completed/failed 清除，UI 卡死。
                try:
                    await asyncio.to_thread(
                        worker.events.emit_task_failed, event_task_list, error or ""
                    )
                except Exception as emit_err:
                    logger.error(f"发送任务失败事件失败: {emit_err}")
    finally:
        # 取消路径：改写状态，落库用 shield 保证不被二次取消
        if asyncio.current_task().cancelling():
            status = "stopped"
            error = "运行被取消"
            if worker is not None and not task_started:
                # 前置阶段被取消（run_process 未启动）：补发终端事件，避免前端 TaskRunning 卡死
                try:
                    await asyncio.shield(
                        asyncio.to_thread(
                            worker.events.emit_task_failed,
                            event_task_list,
                            error or "",
                        )
                    )
                except Exception as emit_err:
                    logger.error(f"发送任务失败事件失败: {emit_err}")
        try:
            # Finish Sentry before SQLite bookkeeping: the transaction covers
            # the real execution terminal state, not storage latency.
            if telemetry is not None:
                try:
                    telemetry.finish_run(run_id, status)
                except Exception:
                    logger.debug("完成遥测 run 事务失败", exc_info=True)
            await asyncio.shield(
                asyncio.to_thread(
                    finish_execution, state.scheduler_db_path, run_id, status, error
                )
            )
        except Exception as e:
            logger.error(f"收尾执行记录失败: {e}")
        # 无条件清槽（纯同步赋值，不受取消影响）
        if state.active_run is not None and state.active_run.run_id == run_id:
            state.active_run = None
        if (
            state.active_execution_task is not None
            and state.active_execution_task is asyncio.current_task()
        ):
            state.active_execution_task = None
        # 若任务是被取消的，继续传播 CancelledError
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
