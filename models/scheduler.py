import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, model_validator
from pydantic_extra_types.cron import CronStr

from models.device_address import (
    DeviceType,
    canonicalize_runtime_device_address,
)

TaskOptionValue = str | list[str] | dict[str, str]
TaskOptionsByTask = dict[str, dict[str, TaskOptionValue]]

ExecutionOrigin = Literal["manual", "in_app", "native"]
ExecutionStatus = Literal[
    "running",
    "success",
    "failed",
    "stopped",
    "skipped_busy_manual",
    "skipped_busy_scheduled",
    "skipped_update_in_progress",
]


_PORTABLE_CRON_ALPHABET = re.compile(r"^[0-9\*,\-/\s]+$")
_MONTH_MAX_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _normalize_portable_cron(value: Any) -> str:
    """Normalize the strict cron wire format before CronStr validation."""
    if not isinstance(value, str):
        raise ValueError("cron expression must be a string")
    text = re.sub(r"\s+", " ", value.strip())
    if not text:
        raise ValueError("cron expression must not be empty")
    if not _PORTABLE_CRON_ALPHABET.match(text):
        raise ValueError("cron expression contains unsupported characters")
    fields = text.split(" ")
    if len(fields) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {len(fields)}")

    # Check directly stated month/day combinations. Ranges and steps are left to
    # CronStr, which owns the full cron grammar and semantic expansion.
    day_field, month_field = fields[2], fields[3]
    if day_field != "*" and month_field != "*":
        for m_str in month_field.split(","):
            for d_str in day_field.split(","):
                try:
                    m, d = int(m_str), int(d_str)
                except ValueError:
                    continue
                if 1 <= m <= 12 and d > _MONTH_MAX_DAYS[m - 1]:
                    raise ValueError(f"month {m} has no day {d}")
    return text


def _validate_native_cron(value: CronStr) -> CronStr:
    """Validate the strict subset shared by APScheduler and native OS schedulers.

    统一 cron 校验：5 字段、单值或 *、分钟必须具体。任一遍历（APScheduler
    CronTrigger 或 OS 原生调度）都可直接消费，无需二次校验。
    """
    minute_set, hour_set, day_set, month_set, dow_set = value.cron_obj.to_list()
    full_minute = set(range(60))
    full_hour = set(range(24))
    full_day = set(range(1, 32))
    full_month = set(range(1, 13))
    full_dow = set(range(7))

    def scalar_or_none(
        field_set: set[int], full_set: set[int], name: str
    ) -> int | None:
        values = sorted(field_set)
        if set(values) == full_set:
            return None
        if len(values) == 1:
            return values[0]
        raise ValueError(f"{name} field must be * or a single value")

    minute = scalar_or_none(minute_set, full_minute, "minute")
    hour = scalar_or_none(hour_set, full_hour, "hour")
    day = scalar_or_none(day_set, full_day, "day")
    month = scalar_or_none(month_set, full_month, "month")
    dow = scalar_or_none(dow_set, full_dow, "dow")
    if minute is None:
        raise ValueError("minute field must be a single value, not *")
    if day is not None and dow is not None:
        raise ValueError("day and day-of-week cannot both be restricted")
    if hour is None and (day is not None or month is not None or dow is not None):
        raise ValueError("when hour is *, day/month/dow must all be *")
    if month is not None and day is None:
        raise ValueError("when month is restricted, day must also be restricted")
    if month is not None and day is not None:
        max_day = _MONTH_MAX_DAYS
        if day > max_day[month - 1]:
            raise ValueError(f"month {month} has no day {day}")
    return value


PortableCronStr = Annotated[
    CronStr,
    BeforeValidator(_normalize_portable_cron),
    AfterValidator(_validate_native_cron),
]


def _validate_task_name(value: Any) -> str:
    """Strip and validate a user-supplied scheduled task name."""
    if not isinstance(value, str):
        raise ValueError("task name must be a string")
    text = value.strip()
    if not text:
        raise ValueError("task name must not be empty")
    if len(text) > 100:
        raise ValueError("task name must be at most 100 characters")
    return text


TaskName = Annotated[str, BeforeValidator(_validate_task_name)]


def _strip_text(value: Any) -> Any:
    """Trim string request fields before their Field constraints run."""
    return value.strip() if isinstance(value, str) else value


_RequiredText = Annotated[str, BeforeValidator(_strip_text)]


class ScheduledTaskDeviceConfig(BaseModel):
    """定时任务设备配置"""

    controller_name: str = Field(..., description="控制器名称")
    device_type: DeviceType = Field(..., description="设备类型")
    device_address: str = Field(..., description="设备地址")

    @model_validator(mode="after")
    def _canonicalize_address(self) -> "ScheduledTaskDeviceConfig":
        self.device_address = canonicalize_runtime_device_address(
            self.device_type, self.device_address
        )
        return self


def _generate_pre_task_id() -> str:
    """生成前置命令的唯一标识"""
    return str(uuid.uuid4())


class PreTaskCommand(BaseModel):
    """前置 shell 命令配置"""

    id: str = Field(default_factory=_generate_pre_task_id, description="唯一标识")
    command: str = Field(..., description="要执行的 shell 命令")
    enabled: bool = Field(True, description="是否启用")
    timeout: int = Field(30, ge=1, le=3600, description="超时时间（秒），范围 1-3600")


class CronTriggerConfig(BaseModel):
    """Cron 触发器配置"""

    type: Literal["cron"] = "cron"
    cron: PortableCronStr = Field(..., description="Cron 表达式，如 '0 9 * * *'")


class DateTriggerConfig(BaseModel):
    """Date 触发器配置"""

    type: Literal["date"] = "date"
    run_date: datetime = Field(..., description="执行日期时间")


class IntervalTriggerConfig(BaseModel):
    """Interval 触发器配置"""

    type: Literal["interval"] = "interval"
    weeks: int | None = Field(None, ge=0, description="周数")
    days: int | None = Field(None, ge=0, description="天数")
    hours: int | None = Field(None, ge=0, description="小时数")
    minutes: int | None = Field(None, ge=0, description="分钟数")
    seconds: int | None = Field(None, ge=0, description="秒数")
    start_date: datetime | None = Field(None, description="开始时间")
    end_date: datetime | None = Field(None, description="结束时间")

    @model_validator(mode="after")
    def _check_min_interval(self) -> "IntervalTriggerConfig":
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be greater than or equal to start_date")
        total = (
            (self.weeks or 0) * 604800
            + (self.days or 0) * 86400
            + (self.hours or 0) * 3600
            + (self.minutes or 0) * 60
            + (self.seconds or 0)
        )
        if total < 1:
            raise ValueError("间隔总时长不能小于 1 秒")
        return self


TriggerConfig = Annotated[
    CronTriggerConfig | DateTriggerConfig | IntervalTriggerConfig,
    Field(discriminator="type"),
]


class TaskExecutionPayload(BaseModel):
    """任务执行载荷"""

    task_identity: Literal["name"] = Field(
        ..., description="任务身份标记；PI v2.9 起固定为 name"
    )
    task_list: list[str] = Field(default_factory=list, description="要执行的任务列表")
    task_options: TaskOptionsByTask = Field(
        default_factory=dict, description="任务选项"
    )
    preTasks: list[PreTaskCommand] = Field(
        default_factory=list, description="前置 shell 命令列表"
    )


class ManualStartPayload(TaskExecutionPayload):
    """手动启动载荷（含设备与资源信息）"""

    task_list: list[str] = Field(..., min_length=1, description="要执行的任务列表")
    controller_name: _RequiredText = Field(..., min_length=1, description="控制器名称")
    device: ScheduledTaskDeviceConfig = Field(..., description="设备配置")
    resource_name: _RequiredText = Field(..., min_length=1, description="资源包名称")


class StartConflict(BaseModel):
    """手动启动冲突信息"""

    code: Literal["busy_manual", "busy_scheduled", "update_in_progress"] = Field(
        ..., description="冲突代码"
    )
    message: str = Field(..., description="冲突描述")
    active_run_id: str = Field(..., description="当前运行 ID")
    active_task_name: str = Field(..., description="当前运行任务名称")
    active_origin: ExecutionOrigin = Field(..., description="当前运行来源")


class ScheduledTask(TaskExecutionPayload):
    """定时任务配置"""

    id: str = Field(..., description="任务唯一标识")
    name: str = Field(..., min_length=1, max_length=100, description="任务名称")
    description: str | None = Field(None, max_length=500, description="任务描述")
    enabled: bool = Field(True, description="是否启用")
    wakeup_enabled: bool = Field(
        False, description="是否启用系统级唤醒（应用关闭后仍运行）"
    )
    trigger_config: TriggerConfig = Field(..., description="触发器配置")
    controller_name: str | None = Field(None, description="控制器名称")
    device: ScheduledTaskDeviceConfig | None = Field(None, description="设备配置")
    resource_name: str | None = Field(None, description="资源包名称")
    next_run_time: datetime | None = Field(None, description="下次执行时间")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class ScheduledTaskCreate(TaskExecutionPayload):
    """创建定时任务请求"""

    task_list: list[str] = Field(..., min_length=1, description="要执行的任务列表")
    name: TaskName
    description: str | None = Field(None, max_length=500)
    enabled: bool = True
    wakeup_enabled: bool = False
    trigger_config: TriggerConfig
    controller_name: str | None = Field(None, description="控制器名称")
    device: ScheduledTaskDeviceConfig | None = Field(None, description="设备配置")
    resource_name: str | None = Field(None, description="资源包名称")


class ScheduledTaskUpdate(BaseModel):
    """更新定时任务请求"""

    task_identity: Literal["name"] | None = Field(
        None, description="任务身份标记；给出 task_list 时必须为 name"
    )
    name: TaskName | None = None
    description: str | None = Field(None, max_length=500)
    enabled: bool | None = None
    wakeup_enabled: bool | None = None
    trigger_config: TriggerConfig | None = None
    controller_name: str | None = Field(None, description="控制器名称")
    device: ScheduledTaskDeviceConfig | None = Field(None, description="设备配置")
    resource_name: str | None = Field(None, description="资源包名称")
    task_list: list[str] | None = None
    task_options: TaskOptionsByTask | None = None
    preTasks: list[PreTaskCommand] | None = None


class TaskExecution(BaseModel):
    """任务执行记录"""

    id: str = Field(..., description="执行记录唯一标识")
    task_id: str | None = Field(None, description="关联的定时任务ID（手动执行为空）")
    task_name: str = Field(..., description="任务名称")
    origin: ExecutionOrigin = Field("in_app", description="执行来源")
    occurrence_id: str | None = Field(None, description="调度发生次标识")
    blocker_task_name: str | None = Field(None, description="冲突的占用任务名称")
    started_at: datetime = Field(..., description="开始时间")
    finished_at: datetime | None = Field(None, description="结束时间")
    status: ExecutionStatus = Field(..., description="执行状态")
    error_message: str | None = Field(None, description="错误信息")
