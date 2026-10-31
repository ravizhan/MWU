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
from models.settings import SettingsModel
from models.task_config import (
    normalize_global_option_values,
    normalize_task_execution_payload,
)
from services import telemetry

logger = logging.getLogger(__name__)

EXECUTIONS_MAX_RECORDS = 1000


@dataclass
class Admission:
    """执行准入结果"""

    accepted: bool
    run_id: str | None = None
    conflict: StartConflict | None = None
    skip_status: str | None = None


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


def _claim_slot(state: AppState, active: ActiveRun) -> None:
    """占用执行槽并开启新的停止生命周期。

    占槽前 active_run 为空，stop_active() 不会执行，因此此处复位 stop_flag
    不会吞掉任何仍有效的停止请求；上一次运行遗留的 True 则必须清掉，否则
    TaskService.start() 会把它当作前置阶段的停止请求而拒绝启动。
    """
    state.active_run = active
    if state.worker is not None:
        state.worker.task_state.stop_flag = False


def _attach_prestart_cancel_guard(state: AppState, run_id: str) -> None:
    """协程在首次调度前被取消时 finally 不会执行：立即清槽并补记取消记录。"""
    task = state.active_execution_task
    if task is None:
        return

    def _guard(t: asyncio.Task) -> None:
        if not t.cancelled():
            return
        if state.active_run is None or state.active_run.run_id != run_id:
            return
        state.active_run = None
        state.active_execution_task = None
        asyncio.get_running_loop().create_task(
            _record_prestart_cancel(state.scheduler_db_path, run_id)
        )

    task.add_done_callback(_guard)


def _release_slot(state: AppState, run_id: str) -> None:
    """准入阶段失败/被取消时立即清槽，避免槽位永久占用（后续启动全被拒 busy）。"""
    if state.active_run is not None and state.active_run.run_id == run_id:
        state.active_run = None
    state.active_execution_task = None


async def submit_manual(state: AppState, payload: ManualStartPayload) -> Admission:
    """手动启动准入"""
    if state.update_in_progress:
        run_id = str(uuid.uuid4())
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
        return Admission(accepted=False, conflict=conflict)

    run_id = str(uuid.uuid4())
    _claim_slot(
        state,
        ActiveRun(
            run_id=run_id,
            origin="manual",
            task_name=payload.task_list[0] if payload.task_list else "手动任务",
        ),
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
        _attach_prestart_cancel_guard(state, run_id)
    except BaseException:
        _release_slot(state, run_id)
        raise
    return Admission(accepted=True, run_id=run_id)


async def submit_scheduled(
    state: AppState,
    task: ScheduledTask,
    origin: ExecutionOrigin,
) -> Admission:
    """调度触发准入（应用内 / 原生冷启动）；时间仅记录实际开始执行时刻"""
    occurrence_id = f"{task.id}:{_utc_now().isoformat()}"

    if state.update_in_progress:
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
    _claim_slot(
        state,
        ActiveRun(
            run_id=run_id,
            origin=origin,
            task_name=task.name,
            occurrence_id=occurrence_id,
        ),
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
        _attach_prestart_cancel_guard(state, run_id)
    except BaseException:
        _release_slot(state, run_id)
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


async def _drain_cancelled_pretasks(worker, pretask_future: asyncio.Future) -> None:
    """取消后等待 pretask 线程真正退出，再让 finally 清槽。

    shield 只防止线程被取消，被取消的协程本身不会继续等待；若不在此等待，槽位会先释放，
    新运行在 _claim_slot 复位共享 stop_flag 后，旧线程可能继续启动后续前置命令。
    置位 stop_flag 使线程不再启动新命令，并在 0.1s 轮询内终止当前进程。
    """
    worker.task_state.stop_flag = True
    while not pretask_future.done():
        try:
            await asyncio.shield(pretask_future)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if not pretask_future.cancelled():
        # 运行已取消，pretask 结果无意义；取回异常避免 "exception was never retrieved"
        pretask_future.exception()


def _deliver_terminal_side_effects(worker, event, error: str | None) -> None:
    worker.events.deliver_notification(event)
    if error:
        worker.events.send_log(f"任务异常详情: {error}")


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
    event_task_list = payload.task_list if payload is not None else (task_list or [])
    # 通知标题用运行标签（定时任务为计划名）；task_state.current_task_name
    # 会在 run_process 退出时被清空，收尾阶段不能再依赖它。
    run_label = state.active_run.task_name if state.active_run is not None else None
    trace = telemetry.start_run(
        state.active_run.origin if state.active_run is not None else "manual"
    )
    failure_stage: str | None = None
    try:
        if worker is None:
            failure_stage = "prepare"
            raise RuntimeError("Worker 未就绪")

        # 1. 校验设备/资源配置
        if payload is None or not payload.device or not payload.resource_name:
            failure_stage = "prepare"
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
            failure_stage = "prepare"
            raise RuntimeError("任务列表为空")

        global_values = (
            state.settings.globalOptionValues if state.settings is not None else {}
        ) or {}
        normalized_global_options = normalize_global_option_values(
            global_values,
            worker.interface,
        )

        # 3. PI pretask + 用户命令统一在 Controller 创建/连接前执行。
        # 已锁定且可复用的 Controller 无法重新满足“创建前”，此处仍保证在任务启动前执行。
        # stop_flag 只在准入占槽时复位（_claim_slot）；此处不得重置，
        # 否则 stop_active() 在准入后、本阶段前设置的停止请求会被吞掉。
        effective_controller = payload.controller_name or payload.device.controller_name
        pretask_future = asyncio.ensure_future(
            asyncio.to_thread(
                worker.pretasks.run_all,
                effective_controller,
                payload.resource_name,
                normalized_pre_tasks,
                normalized_global_options,
            )
        )
        try:
            await asyncio.shield(pretask_future)
        except asyncio.CancelledError:
            await _drain_cancelled_pretasks(worker, pretask_future)
            raise
        except PretaskStopped:
            raise
        except PretaskError as exc:
            if worker.task_state.stop_flag:
                raise PretaskStopped(str(exc)) from exc
            failure_stage = "pretask"
            raise RuntimeError(str(exc)) from exc

        # 4. 复用已匹配连接；不匹配先解锁
        device_state = worker.device_state
        need_connect = not (
            device_state.connected
            and device_state.configuration_locked
            and device_state.controller_name == payload.device.controller_name
            and device_state.current_resource_name == payload.resource_name
        )
        if need_connect and device_state.configuration_locked:
            await asyncio.to_thread(worker.device.reset_connection_state)

        # 5. 按设置重试 connect + set_resource
        if need_connect:
            settings = load_settings()
            attempts = (
                settings.runtime.maxRetryCount if settings.runtime.autoRetry else 1
            )
            retry_interval = settings.runtime.retryInterval
            device_model = worker.device.build_device_model_from_config(
                payload.device.controller_name,
                payload.device.device_type,
                payload.device.device_address,
            )
            connected = False
            last_err: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    if not await asyncio.to_thread(worker.device.connect, device_model):
                        raise RuntimeError("connect() 返回 False")
                    if not await asyncio.to_thread(
                        worker.device.set_resource, payload.resource_name
                    ):
                        raise RuntimeError("set_resource() 返回 False")
                    connected = True
                    break
                except Exception as e:
                    last_err = e
                    if attempt < attempts:
                        worker.events.send_log(f"连接失败，第 {attempt} 次重试...: {e}")
                        await asyncio.sleep(retry_interval)
            if not connected:
                await asyncio.to_thread(worker.device.reset_connection_state)
                failure_stage = "device"
                raise RuntimeError(f"设备连接失败: {last_err}")

        # 6. 启动任务线程
        if trace is not None:
            trace.set_context(
                controller_type=worker.device_state.controller_type,
                controller_name=worker.device_state.controller_name,
                resource=payload.resource_name,
            )
        if not worker.tasks.start(
            normalized_task_list,
            normalized_task_options,
            task_name=state.active_run.task_name if state.active_run else None,
            pre_tasks=normalized_pre_tasks,
            global_options=normalized_global_options,
            trace=trace,
        ):
            failure_stage = "start"
            raise RuntimeError("任务启动失败（可能已有任务在运行）")
        if state.active_run is not None and state.active_run.run_id == run_id:
            state.active_run.started = True

        # 6. 轮询等待结束（stop_flag 由 worker 内部轮询处理中途停止）
        while worker.task_state.running:
            await asyncio.sleep(1)

        last_status = worker.task_state.last_status
        last_error = worker.task_state.last_error
        if last_status == "success":
            status = "success"
        elif last_status == "stopped":
            status = "stopped"
            error = last_error or "任务已终止"
        else:
            status = "failed"
            error = last_error or "任务执行失败"
            failure_stage = "task"

    except PretaskStopped:
        status = "stopped"
        error = "任务已终止"
        if worker is not None:
            worker.events.send_log(error)
    except Exception as e:
        status = "failed"
        error = str(e)
        if failure_stage is None:
            failure_stage = "prepare"
        logger.error(f"执行运行 {run_id} 失败: {e}")
        if worker is not None:
            worker.events.send_log(f"任务执行失败: {e}")
    finally:
        cancelled = bool(asyncio.current_task().cancelling())
        # 取消路径：改写状态，落库用 shield 保证不被二次取消
        if cancelled:
            status = "stopped"
            error = "运行被取消"
        try:
            await asyncio.shield(
                asyncio.to_thread(
                    finish_execution, state.scheduler_db_path, run_id, status, error
                )
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"收尾执行记录失败: {e}")
        if trace is not None:
            try:
                await asyncio.shield(
                    asyncio.to_thread(trace.finish, status, error, stage=failure_stage)
                )
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"遥测上报失败: {e}")
        # 读取失败也必须发终端事件，否则前端 TaskRunning 卡住；此时仅按默认设置决定是否通知。
        notify_settings = SettingsModel()
        if worker is not None:
            try:
                notify_settings = await asyncio.shield(asyncio.to_thread(load_settings))
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"读取通知设置失败: {e}")
        # 清槽与终端事件入队必须在同一同步段内（中间不得 await）：
        # 前端收到 task.completed/task.failed 后立即发起的新启动不能再被判 busy_manual，
        # 同时新运行的 task.started 也不能排在旧运行的终端事件之前。
        if state.active_run is not None and state.active_run.run_id == run_id:
            state.active_run = None
        if (
            state.active_execution_task is not None
            and state.active_execution_task is asyncio.current_task()
        ):
            state.active_execution_task = None
        terminal_event = None
        if worker is not None:
            try:
                terminal_event = worker.events.publish_task_terminal(
                    event_task_list, run_label, status == "success", notify_settings
                )
            except Exception as emit_err:
                logger.error(f"发送任务终端事件失败: {emit_err}")
        if terminal_event is not None:
            try:
                await asyncio.shield(
                    asyncio.to_thread(
                        _deliver_terminal_side_effects, worker, terminal_event, error
                    )
                )
            except asyncio.CancelledError:
                pass
            except Exception as emit_err:
                logger.error(f"发送任务终端通知失败: {emit_err}")
        # 若任务是被取消的，继续传播 CancelledError
        if cancelled:
            raise asyncio.CancelledError
