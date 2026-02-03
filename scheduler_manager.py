import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Literal, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from models.scheduler import (
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    TaskExecution,
    TaskExecutionCreate,
    TriggerConfig,
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
)

logger = logging.getLogger(__name__)


class SchedulerManager:
    """调度器管理器"""

    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._worker = None
        self._executions: List[TaskExecution] = []
        self._executions_lock = asyncio.Lock()

    def set_worker(self, worker):
        """设置 MaaWorker 实例"""
        self._worker = worker

    async def initialize(self):
        """初始化调度器"""
        # 创建调度器
        self.scheduler = AsyncIOScheduler()

        # 启动调度器
        self.scheduler.start()
        logger.info("调度器已启动")

    async def shutdown(self):
        """关闭调度器"""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("调度器已关闭")

    def _create_trigger(self, trigger_config: TriggerConfig):
        """根据配置创建触发器"""
        if isinstance(trigger_config, CronTriggerConfig):
            # 解析 cron 表达式
            parts = trigger_config.cron.split()
            if len(parts) != 5:
                raise ValueError(f"无效的 Cron 表达式: {trigger_config.cron}")
            minute, hour, day, month, day_of_week = parts
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

    async def _execute_task(
        self, task_id: str, task_list: List[str], options: Dict[str, str]
    ):
        """执行定时任务"""
        logger.info(f"开始执行定时任务: {task_id}")

        # 创建执行记录
        execution_id = str(uuid.uuid4())
        task_name = self._get_task_name(task_id)
        execution = TaskExecution(
            id=execution_id,
            task_id=task_id,
            task_name=task_name,
            started_at=datetime.now(),
            status="running",
            finished_at=None,
            error_message=None,
        )
        await self._add_execution(execution)

        try:
            # 检查是否有任务正在运行
            if self._worker and self._worker.running:
                logger.warning(f"任务已在运行，跳过定时任务 {task_id}")
                await self._update_execution_status(
                    execution_id, "stopped", "任务已在运行"
                )
                return

            # 检查设备是否已连接
            if not self._worker or not self._worker.connected:
                logger.error(f"设备未连接，无法执行定时任务 {task_id}")
                await self._update_execution_status(
                    execution_id, "failed", "设备未连接"
                )
                return

            # 启动任务
            if not self._worker.start_task(task_list, options):
                logger.warning(f"任务已在运行，跳过定时任务 {task_id}")
                await self._update_execution_status(
                    execution_id, "stopped", "任务已在运行"
                )
                return

            # 等待任务完成
            while self._worker and self._worker.running:
                await asyncio.sleep(1)

            await self._update_execution_status(execution_id, "success")
            logger.info(f"定时任务 {task_id} 执行成功")

        except Exception as e:
            logger.error(f"定时任务 {task_id} 执行失败: {e}")
            await self._update_execution_status(execution_id, "failed", str(e))

    def _get_task_name(self, task_id: str) -> str:
        """获取任务名称"""
        if not self.scheduler:
            return task_id
        job = self.scheduler.get_job(task_id)
        return job.kwargs.get("task_name", task_id) if job else task_id

    async def _add_execution(self, execution: TaskExecution):
        """添加执行记录"""
        async with self._executions_lock:
            self._executions.append(execution)
            # 只保留最近 100 条记录
            if len(self._executions) > 100:
                self._executions = self._executions[-100:]

    async def _update_execution_status(
        self,
        execution_id: str,
        status: Literal["running", "success", "failed", "stopped"],
        error_message: Optional[str] = None,
    ):
        """更新执行记录状态"""
        async with self._executions_lock:
            for execution in self._executions:
                if execution.id == execution_id:
                    execution.status = status
                    execution.finished_at = datetime.now()
                    if error_message:
                        execution.error_message = error_message
                    break

    async def create_task(self, task_create: ScheduledTaskCreate) -> ScheduledTask:
        """创建定时任务"""
        if not self.scheduler:
            raise RuntimeError("调度器未初始化")

        task_id = str(uuid.uuid4())
        trigger = self._create_trigger(task_create.trigger_config)

        # 添加任务到调度器，存储完整的任务信息
        self.scheduler.add_job(
            self._execute_task,
            trigger,
            id=task_id,
            kwargs={
                "task_id": task_id,
                "task_list": task_create.task_list,
                "options": task_create.task_options,
            },
        )

        # 如果任务未启用，则暂停
        if not task_create.enabled:
            self.scheduler.pause_job(task_id)

        # 获取下次执行时间
        job = self.scheduler.get_job(task_id)
        next_run_time = job.next_run_time if job else None

        # 创建任务对象
        task = ScheduledTask(
            id=task_id,
            name=task_create.name,
            description=task_create.description,
            enabled=task_create.enabled,
            trigger_type=task_create.trigger_type,
            trigger_config=task_create.trigger_config,
            task_list=task_create.task_list,
            task_options=task_create.task_options,
            next_run_time=next_run_time,
        )

        logger.info(f"创建定时任务: {task.name} ({task_id})")
        return task

    async def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """获取定时任务"""
        if not self.scheduler:
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            return None

        # 从 kwargs 中获取任务信息
        task_name = job.kwargs.get("task_name", task_id)
        task_list = job.kwargs.get("task_list", [])
        task_options = job.kwargs.get("options", {})
        trigger_type = job.kwargs.get("trigger_type", "cron")
        trigger_config_dict = job.kwargs.get("trigger_config", {})

        # 根据触发器类型重建配置对象
        if trigger_type == "cron":
            trigger_config = CronTriggerConfig(**trigger_config_dict)
        elif trigger_type == "date":
            trigger_config = DateTriggerConfig(**trigger_config_dict)
        elif trigger_type == "interval":
            trigger_config = IntervalTriggerConfig(**trigger_config_dict)
        else:
            trigger_config = CronTriggerConfig(cron="* * * * *")

        return ScheduledTask(
            id=task_id,
            name=task_name,
            description="",
            enabled=job.next_run_time is not None,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            task_list=task_list,
            task_options=task_options,
            next_run_time=job.next_run_time,
        )

    async def get_all_tasks(self) -> List[ScheduledTask]:
        """获取所有定时任务"""
        if not self.scheduler:
            return []
        tasks = []
        jobs = self.scheduler.get_jobs()

        for job in jobs:
            task_name = job.kwargs.get("task_name", job.id)
            task_list = job.kwargs.get("task_list", [])
            task_options = job.kwargs.get("options", {})
            trigger_type = job.kwargs.get("trigger_type", "cron")
            trigger_config_dict = job.kwargs.get("trigger_config", {})

            # 根据触发器类型重建配置对象
            if trigger_type == "cron":
                trigger_config = CronTriggerConfig(**trigger_config_dict)
            elif trigger_type == "date":
                trigger_config = DateTriggerConfig(**trigger_config_dict)
            elif trigger_type == "interval":
                trigger_config = IntervalTriggerConfig(**trigger_config_dict)
            else:
                trigger_config = CronTriggerConfig(cron="* * * * *")

            task = ScheduledTask(
                id=job.id,
                name=task_name,
                description="",
                enabled=job.next_run_time is not None,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                task_list=task_list,
                task_options=task_options,
                next_run_time=job.next_run_time,
            )
            tasks.append(task)

        return tasks

    async def update_task(
        self, task_id: str, task_update: ScheduledTaskUpdate
    ) -> Optional[ScheduledTask]:
        """更新定时任务"""
        if not self.scheduler:
            logger.error("调度器未初始化")
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            logger.error(f"任务不存在: {task_id}")
            return None

        try:
            # 获取当前任务信息
            current_kwargs = job.kwargs

            # 合并更新数据
            new_name = (
                task_update.name
                if task_update.name is not None
                else current_kwargs.get("task_name", "")
            )
            new_task_list = (
                task_update.task_list
                if task_update.task_list is not None
                else current_kwargs.get("task_list", [])
            )
            new_options = (
                task_update.task_options
                if task_update.task_options is not None
                else current_kwargs.get("options", {})
            )
            new_trigger_type = (
                task_update.trigger_type
                if task_update.trigger_type is not None
                else current_kwargs.get("trigger_type", "cron")
            )
            # 从字典重建触发器配置对象
            current_trigger_config_dict = current_kwargs.get("trigger_config", {})
            current_trigger_type = current_kwargs.get("trigger_type", "cron")

            if current_trigger_type == "cron":
                current_trigger_config = CronTriggerConfig(
                    **current_trigger_config_dict
                )
            elif current_trigger_type == "date":
                current_trigger_config = DateTriggerConfig(
                    **current_trigger_config_dict
                )
            elif current_trigger_type == "interval":
                current_trigger_config = IntervalTriggerConfig(
                    **current_trigger_config_dict
                )
            else:
                current_trigger_config = CronTriggerConfig(cron="* * * * *")

            new_trigger_config = (
                task_update.trigger_config
                if task_update.trigger_config is not None
                else current_trigger_config
            )

            # 创建新的触发器
            trigger = self._create_trigger(new_trigger_config)

            # 修改任务
            self.scheduler.modify_job(
                task_id,
                trigger=trigger,
                kwargs={
                    "task_id": task_id,
                    "task_list": new_task_list,
                    "options": new_options,
                    "task_name": new_name,
                    "trigger_type": new_trigger_type,
                    "trigger_config": new_trigger_config.model_dump(),
                },
            )

            # 处理启用/暂停状态
            if task_update.enabled is not None:
                if task_update.enabled:
                    self.scheduler.resume_job(task_id)
                else:
                    self.scheduler.pause_job(task_id)

            # 获取更新后的任务
            return await self.get_task(task_id)
        except Exception as e:
            logger.error(f"更新任务失败: {e}")
            return None

    async def delete_task(self, task_id: str) -> bool:
        """删除定时任务"""
        if not self.scheduler:
            return False
        try:
            self.scheduler.remove_job(task_id)
            logger.info(f"删除定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"删除任务失败: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        """暂停定时任务"""
        if not self.scheduler:
            return False
        try:
            self.scheduler.pause_job(task_id)
            logger.info(f"暂停定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"暂停任务失败: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        """恢复定时任务"""
        if not self.scheduler:
            return False
        try:
            self.scheduler.resume_job(task_id)
            logger.info(f"恢复定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"恢复任务失败: {e}")
            return False

    async def get_executions(self, limit: int = 50) -> List[TaskExecution]:
        """获取执行历史"""
        async with self._executions_lock:
            return self._executions[-limit:]
