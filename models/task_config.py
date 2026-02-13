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

    def get_selected_tasks(self) -> List[str]:
        """获取选中的任务列表

        如果 taskChecked 为空，则返回全部 taskOrder。
        否则返回 taskChecked 中值为 True 的任务（保持 taskOrder 的顺序）。
        """
        if not self.taskChecked:
            return self.taskOrder
        return [
            task_id
            for task_id in self.taskOrder
            if self.taskChecked.get(task_id, False)
        ]

    def merge_options(
        self, overrides: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """合并选项配置

        Args:
            overrides: 要覆盖的选项值

        Returns:
            合并后的选项配置
        """
        result = dict(self.taskOptions)
        if overrides:
            result.update(overrides)
        return result
