from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal
from datetime import datetime


class CronTriggerConfig(BaseModel):
    """Cron 触发器配置"""

    type: Literal["cron"] = "cron"
    cron: str = Field(..., description="Cron 表达式，如 '0 9 * * *'")


class DateTriggerConfig(BaseModel):
    """Date 触发器配置"""

    type: Literal["date"] = "date"
    run_date: datetime = Field(..., description="执行日期时间")


class IntervalTriggerConfig(BaseModel):
    """Interval 触发器配置"""

    type: Literal["interval"] = "interval"
    weeks: Optional[int] = Field(None, ge=0, description="周数")
    days: Optional[int] = Field(None, ge=0, description="天数")
    hours: Optional[int] = Field(None, ge=0, description="小时数")
    minutes: Optional[int] = Field(None, ge=0, description="分钟数")
    seconds: Optional[int] = Field(None, ge=0, description="秒数")
    start_date: Optional[datetime] = Field(None, description="开始时间")
    end_date: Optional[datetime] = Field(None, description="结束时间")


TriggerConfig = CronTriggerConfig | DateTriggerConfig | IntervalTriggerConfig


class ScheduledTask(BaseModel):
    """定时任务配置"""

    id: str = Field(..., description="任务唯一标识")
    name: str = Field(..., min_length=1, max_length=100, description="任务名称")
    description: Optional[str] = Field(None, max_length=500, description="任务描述")
    enabled: bool = Field(True, description="是否启用")
    trigger_type: Literal["cron", "date", "interval"] = Field(
        ..., description="触发器类型"
    )
    trigger_config: TriggerConfig = Field(..., description="触发器配置")
    task_list: List[str] = Field(default_factory=list, description="要执行的任务列表")
    task_options: Dict[str, str] = Field(default_factory=dict, description="任务选项")
    next_run_time: Optional[datetime] = Field(None, description="下次执行时间")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class ScheduledTaskCreate(BaseModel):
    """创建定时任务请求"""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    enabled: bool = True
    trigger_type: Literal["cron", "date", "interval"]
    trigger_config: TriggerConfig
    task_list: List[str] = Field(default_factory=list)
    task_options: Dict[str, str] = Field(default_factory=dict)


class ScheduledTaskUpdate(BaseModel):
    """更新定时任务请求"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    enabled: Optional[bool] = None
    trigger_type: Optional[Literal["cron", "date", "interval"]] = None
    trigger_config: Optional[TriggerConfig] = None
    task_list: Optional[List[str]] = None
    task_options: Optional[Dict[str, str]] = None


class TaskExecution(BaseModel):
    """任务执行记录"""

    id: str = Field(..., description="执行记录唯一标识")
    task_id: str = Field(..., description="关联的定时任务ID")
    task_name: str = Field(..., description="任务名称")
    started_at: datetime = Field(..., description="开始时间")
    finished_at: Optional[datetime] = Field(None, description="结束时间")
    status: Literal["running", "success", "failed", "stopped"] = Field(
        ..., description="执行状态"
    )
    error_message: Optional[str] = Field(None, description="错误信息")


class TaskExecutionCreate(BaseModel):
    """创建执行记录请求"""

    task_id: str
    task_name: str
    status: Literal["running", "success", "failed", "stopped"]
    error_message: Optional[str] = None
