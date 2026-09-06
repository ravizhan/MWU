"""调度器管理器：APScheduler 3.x CRUD/生命周期 + 触发器构建/还原（吸收 codec）+ 系统级唤醒协同。

执行入口统一移交 ``maa_worker.execution.submit_scheduled``（origin="in_app"）；
执行记录持久化在 ``maa_worker.execution``（stdlib sqlite3，经 asyncio.to_thread）。
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel, TypeAdapter
from tzlocal import get_localzone

from app_state import AppState
from maa_worker.event_service import load_settings
from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskDeviceConfig,
    ScheduledTaskUpdate,
    TaskExecution,
    TaskOptionsByTask,
    TriggerConfig,
)
from models.task_config import normalize_task_execution_payload
from services.native_cron import (
    aps_dow_to_unix,
    native_crons_may_conflict,
    parse_native_cron,
    unix_dow_to_aps,
)

logger = logging.getLogger(__name__)

# APS 持久化回调的运行期状态（initialize 时经 _bind_callback_runtime 注入）。
# APScheduler 的 jobstore 只持久化模块级函数引用，无法携带实例，故用模块全局。
_CALLBACK_STATE: AppState | None = None

_TriggerConfigAdapter = TypeAdapter(TriggerConfig)


def _bind_callback_runtime(state: AppState) -> None:
    """绑定 APS 持久化回调所需的运行期状态（模块级全局）。"""
    global _CALLBACK_STATE
    _CALLBACK_STATE = state


def _decode_trigger_config(raw: Any) -> TriggerConfig:
    """从 kwargs 中的 model_dump 字典还原触发器配置（按 type 判别字段）。"""
    if isinstance(raw, (CronTriggerConfig, DateTriggerConfig, IntervalTriggerConfig)):
        return raw
    return _TriggerConfigAdapter.validate_python(raw)


def _build_task_from_kwargs(
    job_id: str, kwargs: dict, trigger_config: TriggerConfig
) -> ScheduledTask:
    """从 APS job kwargs 还原任务载荷（触发器由调用方解码提供）。"""
    device_raw = kwargs.get("device")
    if isinstance(device_raw, ScheduledTaskDeviceConfig):
        device = device_raw
    elif device_raw:
        device = ScheduledTaskDeviceConfig(**device_raw)
    else:
        device = None
    return ScheduledTask(
        id=job_id,
        name=kwargs.get("task_name", ""),
        task_identity=kwargs.get("task_identity", None),
        description=kwargs.get("task_description", ""),
        wakeup_enabled=bool(kwargs.get("wakeup_enabled", False)),
        trigger_config=trigger_config,
        task_list=kwargs.get("task_list", []) or [],
        task_options=kwargs.get("task_options", {}) or {},
        preTasks=kwargs.get("pre_tasks", []) or [],
        controller_name=kwargs.get("controller_name"),
        device=device,
        resource_name=kwargs.get("resource_name"),
    )


async def scheduled_job_fired(**kwargs) -> None:
    """APScheduler 可持久化执行入口。

    - 启用了系统级唤醒（wakeup_enabled）且系统级后端可用的任务由 OS 原生调度负责，
      应用内直接跳过，避免双重派发；后端不可用（NullBackend）时回退应用内派发；
    - 其余任务移交 ``maa_worker.execution.submit_scheduled``（origin="in_app"）。
    """
    state = _CALLBACK_STATE
    if state is None:
        logger.error(f"调度器运行期状态未绑定，跳过定时任务 {kwargs.get('task_id')}")
        return
    # 唤醒任务仅在系统级后端可用时才跳过应用内派发；不可用则回退，防止任务失能
    if kwargs.get("wakeup_enabled") and getattr(
        state.system_scheduler, "supports_native", False
    ):
        logger.info(
            f"定时任务 {kwargs.get('task_id')} 已启用系统级唤醒，跳过应用内派发"
        )
        return
    try:
        trigger_config = _decode_trigger_config(kwargs.get("trigger_config"))
        task = _build_task_from_kwargs(
            kwargs.get("task_id", ""), kwargs, trigger_config
        )
    except Exception as e:
        logger.warning(f"定时任务 {kwargs.get('task_id')} 载荷解码失败，跳过执行: {e}")
        return
    from maa_worker import execution  # 延迟导入避免循环依赖

    # fire-time 身份校验：task_identity 缺失或 task name 不在当前 PI 中时，
    # 落库一条失败记录（含 job id 与具体未知名称）并通知，不让校验异常
    # 逃出 APScheduler 回调形成无记录触发。
    worker = state.worker
    if (
        kwargs.get("task_identity") != "name"
        or worker is None
        or not getattr(worker, "interface", None)
    ):
        await _record_fire_time_skip(
            state, task, "任务身份标记缺失（task_identity != name）"
        )
        return
    from models.task_config import find_unknown_task_names

    unknown_names = find_unknown_task_names(worker.interface, task.task_list)
    if unknown_names:
        await _record_fire_time_skip(
            state,
            task,
            "任务名称不在当前 interface 中: " + ", ".join(unknown_names),
        )
        return

    await execution.submit_scheduled(
        state,
        task,
        origin="in_app",
    )


async def _record_fire_time_skip(state: AppState, task: ScheduledTask, reason: str):
    """fire-time 载荷/身份失效：落库 failed 记录 + 通知，不派发执行。"""
    logger.warning(f"定时任务 {task.id} 触发但被拒绝: {reason}")
    from maa_worker import execution

    await execution.record_fire_time_rejection(state, task, reason)


class SchedulerManager:
    """调度器管理器"""

    def __init__(self, state: AppState, db_path: Path, system_scheduler=None):
        self._state = state
        self._db_path = db_path
        self._system_scheduler = system_scheduler
        self.scheduler: AsyncIOScheduler | None = None

    @staticmethod
    def _desired_wakeup(wakeup_enabled: bool, enabled: bool) -> bool:
        """期望的系统级唤醒状态：唤醒开关与启用状态同时为真。"""
        return bool(wakeup_enabled) and bool(enabled)

    async def _check_wakeup_minute_conflict(
        self, candidate: ScheduledTask, exclude_task_id: str | None = None
    ) -> None:
        """校验候选任务的系统级唤醒不会与既有任务同分钟触发。

        冷启动单例假设下，两个原生唤醒同分钟触发会派生两个进程竞态绑定
        端口，败者无法委托导致任务丢失。此处以保守判定阻断该配置：
        任一 cron 字段两侧均受限且不同才视为不冲突。仅对双方均成功解析为
        严格 cron 的 Cron 触发器任务生效；非 Cron 或非严格 cron 由
        SystemScheduler.register 自行拒绝。
        """
        if not isinstance(candidate.trigger_config, CronTriggerConfig):
            return
        try:
            candidate_cron = parse_native_cron(candidate.trigger_config.cron)
        except ValueError:
            return

        for existing in await self.get_all_tasks():
            if existing.id == exclude_task_id:
                continue
            if not self._desired_wakeup(existing.wakeup_enabled, existing.enabled):
                continue
            if not isinstance(existing.trigger_config, CronTriggerConfig):
                continue
            try:
                existing_cron = parse_native_cron(existing.trigger_config.cron)
            except ValueError:
                continue
            if native_crons_may_conflict(candidate_cron, existing_cron):
                raise ValueError(
                    f"系统级唤醒与任务「{existing.name}」可能在同一分钟触发，"
                    f"请错开触发时间（cron: {existing.trigger_config.cron!r}）"
                )

    async def initialize(self, paused: bool = True):
        """初始化调度器"""
        _bind_callback_runtime(self._state)

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{self._db_path.resolve().as_posix()}"
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=db_url)},
            job_defaults={"misfire_grace_time": 900, "coalesce": True},
            timezone=get_localzone(),
        )
        self.scheduler.start(paused=paused)
        await self._validate_persisted_jobs()
        logger.info(f"调度器已启动（paused={paused}）")

    async def _validate_persisted_jobs(self) -> None:
        """启动时（暂停状态）校验每条持久化 kwargs 的任务身份。

        严格新格式切换：缺 task_identity 标记或旧 entry 身份的任务明确列出
        job id，拒绝恢复并使启动以清晰错误结束。不自动迁移/删除。
        """
        assert self.scheduler is not None
        invalid_jobs: list[str] = []
        for job in self.scheduler.get_jobs():
            kwargs = job.kwargs or {}
            if kwargs.get("task_identity") != "name":
                invalid_jobs.append(job.id)
                continue
            try:
                trigger_config = self._build_trigger_config(job.trigger)
                _build_task_from_kwargs(job.id, kwargs, trigger_config)
            except Exception as e:
                logger.warning(f"持久化任务 {job.id} 载荷校验失败: {e}")
                invalid_jobs.append(job.id)
        if invalid_jobs:
            raise RuntimeError(
                '以下定时任务使用了不支持的任务身份格式（缺少 task_identity="name"），'
                "无法恢复。请在备份 config/scheduler.sqlite 后删除并重建这些任务: "
                + ", ".join(invalid_jobs)
            )

    async def shutdown(self):
        """关闭调度器"""
        global _CALLBACK_STATE
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("调度器已关闭")
        _CALLBACK_STATE = None

    def _create_trigger(self, trigger_config: TriggerConfig):
        """根据配置创建触发器"""
        if isinstance(trigger_config, CronTriggerConfig):
            nc = parse_native_cron(trigger_config.cron)
            minute = str(nc.minute)
            hour = "*" if nc.hour is None else str(nc.hour)
            day = "*" if nc.day is None else str(nc.day)
            month = "*" if nc.month is None else str(nc.month)
            day_of_week = "*" if nc.dow is None else str(unix_dow_to_aps(nc.dow))
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            )
        elif isinstance(trigger_config, DateTriggerConfig):
            return DateTrigger(run_date=trigger_config.run_date)
        elif isinstance(trigger_config, IntervalTriggerConfig):
            return IntervalTrigger(
                weeks=trigger_config.weeks or 0,
                days=trigger_config.days or 0,
                hours=trigger_config.hours or 0,
                minutes=trigger_config.minutes or 0,
                seconds=trigger_config.seconds or 0,
                start_date=trigger_config.start_date,
                end_date=trigger_config.end_date,
            )
        else:
            raise ValueError(f"未知的触发器类型: {type(trigger_config)}")

    def _build_trigger_config(self, trigger) -> TriggerConfig:
        """从 APScheduler trigger 重建触发器配置"""
        if isinstance(trigger, CronTrigger):
            field_map = {field.name: str(field) for field in trigger.fields}
            aps_dow = field_map.get("day_of_week", "*")
            unix_dow = aps_dow if aps_dow == "*" else str(aps_dow_to_unix(int(aps_dow)))
            cron_text = " ".join(
                [
                    field_map.get("minute", "*"),
                    field_map.get("hour", "*"),
                    field_map.get("day", "*"),
                    field_map.get("month", "*"),
                    unix_dow,
                ]
            )
            # 统一校验（PortableCronStr 严格子集）在模型层执行，roundtrip 恒等
            return CronTriggerConfig(cron=cron_text)

        if isinstance(trigger, DateTrigger):
            run_date = getattr(trigger, "run_date", None)
            if run_date is None:
                raise ValueError("DateTrigger 缺少 run_date")
            return DateTriggerConfig(run_date=run_date)

        if isinstance(trigger, IntervalTrigger):
            interval = getattr(trigger, "interval", None)
            total_seconds = int(interval.total_seconds()) if interval is not None else 0

            week_seconds = 7 * 24 * 60 * 60
            day_seconds = 24 * 60 * 60

            weeks, remainder = divmod(total_seconds, week_seconds)
            days, remainder = divmod(remainder, day_seconds)
            hours, remainder = divmod(remainder, 60 * 60)
            minutes, seconds = divmod(remainder, 60)

            return IntervalTriggerConfig(
                weeks=weeks or None,
                days=days or None,
                hours=hours or None,
                minutes=minutes or None,
                seconds=seconds or None,
                start_date=getattr(trigger, "start_date", None),
                end_date=getattr(trigger, "end_date", None),
            )

        raise ValueError(f"未知的触发器类型: {type(trigger)}")

    def _normalize_task_payload(
        self,
        task_list: Any,
        task_options: Any,
        pre_tasks: Any = None,
    ) -> tuple[list[str], TaskOptionsByTask, list]:
        worker = self._state.worker
        if not worker or not getattr(worker, "interface", None):
            raise RuntimeError("Worker 未就绪，无法校验任务载荷")

        ntl, nto, npt = normalize_task_execution_payload(
            task_list,
            task_options,
            worker.interface,
            pre_tasks,
        )
        return ntl, nto, npt

    async def create_task(self, task_create: ScheduledTaskCreate) -> ScheduledTask:
        """创建定时任务"""
        if not self.scheduler:
            raise RuntimeError("调度器未初始化")

        task_id = str(uuid.uuid4())
        trigger = self._create_trigger(task_create.trigger_config)
        normalized_task_list, normalized_task_options, normalized_pre_tasks = (
            self._normalize_task_payload(
                task_create.task_list,
                task_create.task_options,
                task_create.preTasks,
            )
        )
        if not normalized_task_list:
            raise ValueError("任务列表不能为空")

        task = ScheduledTask(
            id=task_id,
            task_identity="name",
            name=task_create.name,
            description=task_create.description,
            enabled=task_create.enabled,
            wakeup_enabled=task_create.wakeup_enabled,
            trigger_config=task_create.trigger_config,
            task_list=normalized_task_list,
            task_options=normalized_task_options,
            preTasks=normalized_pre_tasks,
            controller_name=task_create.controller_name,
            device=task_create.device,
            resource_name=task_create.resource_name,
        )

        # 系统级唤醒注册先行：失败则阻塞创建（APS 任务不落，避免两侧状态不一致）
        registered_native = False
        if (
            self._desired_wakeup(task.wakeup_enabled, task.enabled)
            and self._system_scheduler is not None
        ):
            await self._check_wakeup_minute_conflict(task)
            try:
                self._system_scheduler.register(task)
            except Exception as e:
                logger.error(f"注册系统级唤醒失败，取消创建任务 {task_id}: {e}")
                raise
            registered_native = True

        try:
            self.scheduler.add_job(
                scheduled_job_fired,
                trigger,
                id=task_id,
                kwargs={
                    "task_id": task_id,
                    "task_identity": "name",
                    "task_name": task.name,
                    "task_description": task.description or "",
                    "task_list": normalized_task_list,
                    "task_options": normalized_task_options,
                    "pre_tasks": [pt.model_dump() for pt in normalized_pre_tasks],
                    "controller_name": task.controller_name,
                    "device": task.device.model_dump() if task.device else None,
                    "resource_name": task.resource_name,
                    "wakeup_enabled": task.wakeup_enabled,
                    "trigger_config": task.trigger_config.model_dump(mode="json"),
                },
            )

            # 如果任务未启用，则暂停
            if not task.enabled:
                self.scheduler.pause_job(task_id)

            # 获取下次执行时间
            job = self.scheduler.get_job(task_id)
            task.next_run_time = job.next_run_time if job else None
        except Exception:
            # APS 落库失败但原生已注册：尽力补偿注销，避免遗留孤儿 OS 任务
            if registered_native and self._system_scheduler is not None:
                try:
                    self._system_scheduler.unregister(task_id)
                except Exception as ce:
                    logger.warning(
                        f"创建任务失败后补偿注销系统级唤醒失败（{task_id}）: {ce}"
                    )
            raise

        logger.info(f"创建定时任务: {task.name} ({task_id})")
        return task

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        """获取定时任务"""
        if not self.scheduler:
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            return None

        try:
            trigger_config = self._build_trigger_config(job.trigger)
            task = _build_task_from_kwargs(job.id, job.kwargs or {}, trigger_config)
            task.enabled = job.next_run_time is not None
            task.next_run_time = job.next_run_time
            task_list, task_options, pre_tasks = self._normalize_task_payload(
                task.task_list,
                task.task_options,
                task.preTasks,
            )
            task.task_list = task_list
            task.task_options = task_options
            task.preTasks = pre_tasks
            return task
        except Exception as e:
            logger.warning(f"任务 {task_id} 载荷解码失败，跳过: {e}")
            return None

    async def get_all_tasks(self) -> list[ScheduledTask]:
        """获取所有定时任务"""
        if not self.scheduler:
            return []
        tasks: list[ScheduledTask] = []
        jobs = self.scheduler.get_jobs()

        for job in jobs:
            try:
                trigger_config = self._build_trigger_config(job.trigger)
                task = _build_task_from_kwargs(job.id, job.kwargs or {}, trigger_config)
                task.enabled = job.next_run_time is not None
                task.next_run_time = job.next_run_time
                task_list, task_options, pre_tasks = self._normalize_task_payload(
                    task.task_list,
                    task.task_options,
                    task.preTasks,
                )
                task.task_list = task_list
                task.task_options = task_options
                task.preTasks = pre_tasks
                tasks.append(task)
            except Exception as e:
                # 无法解码的旧/坏任务仅跳过，不删除
                logger.warning(f"任务 {job.id} 载荷解码失败，跳过: {e}")

        return tasks

    async def update_task(
        self, task_id: str, task_update: ScheduledTaskUpdate
    ) -> ScheduledTask | None:
        """更新定时任务"""
        if not self.scheduler:
            if self._state.worker:
                _settings = load_settings()
                self._state.worker.events.send_notification(
                    "调度器未初始化",
                    "无法更新定时任务：调度器未初始化",
                    level="error",
                    notify=["notification"]
                    if _settings.notification.notifyOnError
                    else [],
                )
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            if self._state.worker:
                _settings = load_settings()
                self._state.worker.events.send_notification(
                    "任务不存在",
                    f"无法更新定时任务：任务 {task_id} 不存在",
                    level="error",
                    notify=["notification"]
                    if _settings.notification.notifyOnError
                    else [],
                )
            return None

        try:
            # 获取当前任务信息
            current_kwargs = job.kwargs or {}

            current_trigger_config = self._build_trigger_config(job.trigger)

            # 合并更新数据
            new_name = (
                task_update.name
                if task_update.name is not None
                else current_kwargs.get("task_name", "")
            )
            new_description = (
                task_update.description
                if task_update.description is not None
                else current_kwargs.get("task_description", "")
            )
            new_task_list = (
                task_update.task_list
                if task_update.task_list is not None
                else current_kwargs.get("task_list", [])
            )
            new_options = (
                task_update.task_options
                if task_update.task_options is not None
                else current_kwargs.get("task_options", {})
            )
            new_pre_tasks = (
                task_update.preTasks
                if task_update.preTasks is not None
                else current_kwargs.get("pre_tasks", [])
            )
            # Use model_fields_set to distinguish "field omitted" (keep current)
            # from "field set to None/false" (explicitly clear).
            updated_fields = task_update.model_fields_set
            new_controller_name = (
                task_update.controller_name
                if "controller_name" in updated_fields
                else current_kwargs.get("controller_name", None)
            )
            if "device" in updated_fields:
                new_device_raw = task_update.device
                new_device = (
                    new_device_raw.model_dump()
                    if isinstance(new_device_raw, BaseModel)
                    else new_device_raw
                )
            else:
                new_device = current_kwargs.get("device", None)
            new_resource_name = (
                task_update.resource_name
                if "resource_name" in updated_fields
                else current_kwargs.get("resource_name", None)
            )
            # 显式给出（含 None/False）即视为关闭唤醒；省略则沿用当前值
            new_wakeup_enabled = (
                bool(task_update.wakeup_enabled)
                if "wakeup_enabled" in updated_fields
                else bool(current_kwargs.get("wakeup_enabled", False))
            )
            normalized_task_list, normalized_task_options, normalized_pre_tasks = (
                self._normalize_task_payload(
                    new_task_list,
                    new_options,
                    new_pre_tasks,
                )
            )
            if not normalized_task_list:
                raise ValueError("任务列表不能为空")

            new_trigger_config = (
                task_update.trigger_config
                if task_update.trigger_config is not None
                else current_trigger_config
            )
            # 合并后的启用状态：更新未显式给出时沿用当前 APS 状态
            new_enabled = (
                task_update.enabled
                if task_update.enabled is not None
                else job.next_run_time is not None
            )
            merged_task = ScheduledTask(
                id=task_id,
                task_identity="name",
                name=new_name,
                description=new_description,
                enabled=new_enabled,
                wakeup_enabled=new_wakeup_enabled,
                trigger_config=new_trigger_config,
                task_list=normalized_task_list,
                task_options=normalized_task_options,
                preTasks=normalized_pre_tasks,
                controller_name=new_controller_name,
                device=(
                    ScheduledTaskDeviceConfig(**new_device) if new_device else None
                ),
                resource_name=new_resource_name,
            )

            # 原生注册/注销先行：期望变化时先对齐 OS 侧，再改 APS
            prev_desired = self._desired_wakeup(
                bool(current_kwargs.get("wakeup_enabled", False)),
                job.next_run_time is not None,
            )
            native_changed = False
            if self._system_scheduler is not None:
                if self._desired_wakeup(
                    merged_task.wakeup_enabled, merged_task.enabled
                ):
                    await self._check_wakeup_minute_conflict(
                        merged_task, exclude_task_id=task_id
                    )
                    try:
                        self._system_scheduler.register(merged_task)
                    except Exception as e:
                        logger.error(
                            f"注册系统级唤醒失败，更新任务 {task_id} 失败: {e}"
                        )
                        raise
                    native_changed = True
                elif prev_desired:
                    try:
                        self._system_scheduler.unregister(task_id)
                    except Exception as e:
                        logger.error(
                            f"注销系统级唤醒失败，更新任务 {task_id} 失败: {e}"
                        )
                        raise
                    native_changed = True

            try:
                # 创建新的触发器并修改任务
                trigger = self._create_trigger(new_trigger_config)
                self.scheduler.modify_job(
                    task_id,
                    trigger=trigger,
                    kwargs={
                        "task_id": task_id,
                        "task_identity": "name",
                        "task_name": new_name,
                        "task_description": new_description,
                        "task_list": normalized_task_list,
                        "task_options": normalized_task_options,
                        "pre_tasks": [pt.model_dump() for pt in normalized_pre_tasks],
                        "controller_name": new_controller_name,
                        "device": new_device,
                        "resource_name": new_resource_name,
                        "wakeup_enabled": new_wakeup_enabled,
                        "trigger_config": new_trigger_config.model_dump(mode="json"),
                    },
                )

                # 处理启用/暂停状态
                if task_update.enabled is not None:
                    if task_update.enabled:
                        self.scheduler.resume_job(task_id)
                    else:
                        self.scheduler.pause_job(task_id)
            except Exception:
                # APS 修改失败但原生注册已在本调用改动：尽力恢复到更新前状态
                if native_changed and self._system_scheduler is not None:
                    try:
                        if prev_desired:
                            prev_task = _build_task_from_kwargs(
                                task_id, current_kwargs, current_trigger_config
                            )
                            prev_task.enabled = job.next_run_time is not None
                            self._system_scheduler.register(prev_task)
                        else:
                            self._system_scheduler.unregister(task_id)
                    except Exception as ce:
                        logger.warning(
                            f"更新任务 {task_id} 失败后补偿原生注册失败: {ce}"
                        )
                raise

            # 获取更新后的任务
            return await self.get_task(task_id)
        except ValueError:
            # 校验类错误（如同分钟唤醒冲突）需原样传播，由 API 层返回 400
            raise
        except Exception as e:
            logger.error(f"更新任务失败: {e}")
            if self._state.worker:
                self._state.worker.events.send_log(f"更新任务失败: {e}")
            return None

    async def delete_task(self, task_id: str) -> bool:
        """删除定时任务"""
        if not self.scheduler:
            return False
        try:
            # 先注销系统级唤醒：唤醒任务注销失败则中止删除，
            # 否则会遗留活着的 OS 任务持续启动应用
            wakeup_enabled = False
            if self._system_scheduler is not None:
                job = self.scheduler.get_job(task_id)
                wakeup_enabled = bool(
                    (job.kwargs or {}).get("wakeup_enabled", False)
                    if job is not None
                    else False
                )
            if wakeup_enabled and self._system_scheduler is not None:
                try:
                    self._system_scheduler.unregister(task_id)
                except Exception as e:
                    logger.error(f"注销系统级唤醒失败，中止删除任务 {task_id}: {e}")
                    if self._state.worker:
                        self._state.worker.events.send_log(
                            f"删除任务失败: 注销系统级唤醒失败 {e}"
                        )
                    return False
            self.scheduler.remove_job(task_id)
            logger.info(f"删除定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"删除任务失败: {e}")
            if self._state.worker:
                self._state.worker.events.send_log(f"删除任务失败: {e}")
            return False

    async def degrade_wakeup(self, task_id: str) -> bool:
        """启动时注册失败后降级任务：关闭 wakeup_enabled，跳过原生注销。

        用于 converge 注册失败后的容错路径：原生后端可能已不可用，
        unregister 会抛异常，因此直接修改 APS 任务属性，不触碰 OS 侧。
        """
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                logger.warning(f"降级失败：任务 {task_id} 不存在")
                return False
            current_kwargs = dict(job.kwargs or {})
            if not current_kwargs.get("wakeup_enabled", False):
                return True  # 已是关闭状态，无需操作
            current_kwargs["wakeup_enabled"] = False
            self.scheduler.modify_job(task_id, kwargs=current_kwargs)
            logger.info(f"已降级任务 {task_id} 的系统级唤醒")
            return True
        except Exception as e:
            logger.error(f"降级任务 {task_id} 失败: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        """暂停定时任务"""
        if not self.scheduler:
            return False
        try:
            # 唤醒任务先注销原生注册：仅当任务当前确实启用了唤醒
            if self._system_scheduler is not None:
                job = self.scheduler.get_job(task_id)
                if job is not None:
                    current_enabled = job.next_run_time is not None
                    if self._desired_wakeup(
                        bool((job.kwargs or {}).get("wakeup_enabled", False)),
                        current_enabled,
                    ):
                        try:
                            self._system_scheduler.unregister(task_id)
                        except Exception as e:
                            logger.error(
                                f"注销系统级唤醒失败，中止暂停任务 {task_id}: {e}"
                            )
                            if self._state.worker:
                                self._state.worker.events.send_log(
                                    f"暂停任务失败: 注销系统级唤醒失败 {e}"
                                )
                            return False
            self.scheduler.pause_job(task_id)
            logger.info(f"暂停定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"暂停任务失败: {e}")
            if self._state.worker:
                self._state.worker.events.send_log(f"暂停任务失败: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        """恢复定时任务"""
        if not self.scheduler:
            return False
        try:
            # 唤醒任务先重新注册原生：失败则中止恢复，避免恢复为启用却无原生匹配
            if self._system_scheduler is not None:
                job = self.scheduler.get_job(task_id)
                if job is not None and self._desired_wakeup(
                    bool((job.kwargs or {}).get("wakeup_enabled", False)),
                    True,  # resume 后任务将启用
                ):
                    try:
                        task = await self.get_task(task_id)
                        if task is None:
                            raise RuntimeError(f"任务 {task_id} 不存在")
                        task.enabled = True  # resume 后将启用
                        self._system_scheduler.register(task)
                    except Exception as e:
                        logger.error(f"注册系统级唤醒失败，中止恢复任务 {task_id}: {e}")
                        if self._state.worker:
                            self._state.worker.events.send_log(
                                f"恢复任务失败: 注册系统级唤醒失败 {e}"
                            )
                        return False
            self.scheduler.resume_job(task_id)
            logger.info(f"恢复定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"恢复任务失败: {e}")
            if self._state.worker:
                self._state.worker.events.send_log(f"恢复任务失败: {e}")
            return False

    async def get_executions(self, limit: int = 50) -> list[TaskExecution]:
        """获取执行历史"""
        from maa_worker import execution  # 延迟导入避免循环依赖

        return await asyncio.to_thread(execution.list_executions, self._db_path, limit)
