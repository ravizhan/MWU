"""系统级唤醒调度适配（无状态）。

将启用了系统级唤醒（wakeup_enabled）的定时任务收敛到 OS 原生调度
（schtasks / launchctl / crontab），不做任何本地状态持久化：
每次调用都以"期望集合"为准，注册缺失/更新、清理孤儿。
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from models.scheduler import CronTriggerConfig, ScheduledTask, parse_portable_cron
from services.system_scheduler_backend import (
    NativeTaskSpec,
    SystemSchedulerBackend,
    build_native_command,
    get_backend,
)

logger = logging.getLogger(__name__)


@dataclass
class ConvergeReport:
    """系统级唤醒收敛结果"""

    registered: list[str] = field(default_factory=list)
    unregistered: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    list_error: str | None = None


class SystemScheduler:
    """OS 级调度适配器：以期望集合收敛原生注册，单任务失败不中断。"""

    def __init__(
        self,
        app_root: Path,
        backend: SystemSchedulerBackend | None = None,
    ) -> None:
        self._app_root = app_root
        self._backend = backend or get_backend()

    @property
    def supports_native(self) -> bool:
        """后端是否真正提供 OS 原生唤醒（NullBackend 为 False）。"""
        return self._backend.supports_native

    def _build_spec(self, task: ScheduledTask) -> NativeTaskSpec:
        """将调度任务转换为原生注册规格，仅支持 Cron 触发器。"""
        if not isinstance(task.trigger_config, CronTriggerConfig):
            raise ValueError("仅 Cron 触发器支持系统级唤醒")
        cron = parse_portable_cron(task.trigger_config.cron)
        exe_path, cli_args = build_native_command(self._app_root, task.id)
        return NativeTaskSpec(
            task_id=task.id,
            task_name=task.name,
            exe_path=exe_path,
            cli_args=cli_args,
            cron=cron,
            working_dir=str(self._app_root),
        )

    def register(self, task: ScheduledTask) -> None:
        """注册（或覆盖更新）单个任务的系统级唤醒。"""
        self._backend.register(self._build_spec(task))
        logger.info(f"已注册系统级唤醒: {task.name} ({task.id})")

    def unregister(self, task_id: str) -> None:
        """注销单个任务的系统级唤醒。"""
        self._backend.unregister(task_id)
        logger.info(f"已注销系统级唤醒: {task_id}")

    def converge(self, desired: list[ScheduledTask]) -> ConvergeReport:
        """收敛到期望集合：注册所有启用了唤醒的任务，清理孤儿。

        查询已注册任务失败时记录到 ``report.list_error`` 并直接返回
        （当前状态未知，不做任何注册/清理），由调用方记录失败；单个任务
        的注册/注销失败不中断其它任务。
        """
        report = ConvergeReport()
        desired_tasks = [t for t in desired if t.wakeup_enabled and t.enabled]
        desired_ids = {t.id for t in desired_tasks}

        try:
            registered_ids = self._backend.list_registered_task_ids()
        except Exception as e:  # noqa: BLE001 - 状态未知，收敛退出交由调用方记录
            logger.warning(f"查询已注册系统级唤醒失败: {e}")
            report.list_error = str(e)
            return report

        for task in desired_tasks:
            try:
                self._backend.register(self._build_spec(task))
                report.registered.append(task.id)
            except Exception as e:  # noqa: BLE001 - 单任务失败不中断其余任务
                report.failed[task.id] = str(e)
                logger.warning(f"注册系统级唤醒失败: {task.name} ({task.id}): {e}")

        for orphan_id in sorted(registered_ids - desired_ids):
            try:
                self._backend.unregister(orphan_id)
                report.unregistered.append(orphan_id)
            except Exception as e:  # noqa: BLE001 - 单任务失败不中断其余任务
                report.failed[orphan_id] = str(e)
                logger.warning(f"注销系统级唤醒失败: {orphan_id}: {e}")

        return report
