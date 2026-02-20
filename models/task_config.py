from pydantic import BaseModel, Field
from typing import List, Dict, Optional


class TaskConfigModel(BaseModel):
    taskOrder: List[str] = Field(
        default_factory=list, description="任务ID列表（有序，表示执行顺序）"
    )
    taskChecked: Optional[Dict[str, bool]] = Field(
        default=None, description="任务选中状态映射，key为任务ID，value为是否选中"
    )
    taskOptions: Dict[str, str] = Field(
        default_factory=dict, description="任务选项配置，key为选项名，value为选项值"
    )
