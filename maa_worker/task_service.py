import copy
import threading
import time
import traceback
from typing import TYPE_CHECKING

from models.scheduler import PreTaskCommand, TaskOptionsByTask, TaskOptionValue

if TYPE_CHECKING:
    from maa_utils import MaaWorker


class TaskService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _get_task_definition(self, task_name: str):
        return next(
            (
                task
                for task in self.worker.interface.task or []
                if task.name == task_name
            ),
            None,
        )

    def _is_task_compatible(
        self,
        task_definition,
        controller_names: set[str],
        resource_name: str | None,
    ) -> tuple[bool, str]:
        if task_definition is None:
            return True, ""

        if task_definition.controller and not controller_names.intersection(
            task_definition.controller
        ):
            return (
                False,
                "当前控制器不受支持"
                + f" (支持: {', '.join(task_definition.controller)})",
            )

        if task_definition.resource and (
            resource_name is None or resource_name not in task_definition.resource
        ):
            return (
                False,
                "当前资源不受支持" + f" (支持: {', '.join(task_definition.resource)})",
            )

        return True, ""

    def start(
        self,
        task_list: list[str],
        options: TaskOptionsByTask,
        task_name: str | None = None,
        pre_tasks: list[PreTaskCommand] | None = None,
        global_options: dict[str, TaskOptionValue] | None = None,
    ) -> bool:
        self.worker.task_state.last_error = None
        if not self.worker.device_state.connected:
            return False
        if not self.worker.device_state.current_resource_name:
            self.worker.device_state.last_resource_error = "请先设置资源"
            self.worker.events.send_log(self.worker.device_state.last_resource_error)
            return False

        controller_names = self.worker.device.get_active_controller_names()
        current_resource_name = self.worker.device_state.current_resource_name

        filtered_task_list: list[str] = []
        for task_name in task_list:
            task_definition = self._get_task_definition(task_name)
            compatible, reason = self._is_task_compatible(
                task_definition,
                controller_names,
                current_resource_name,
            )
            if compatible:
                filtered_task_list.append(task_name)
                continue

            self.worker.events.send_log(f"跳过任务 {task_name}: {reason}")

        if not filtered_task_list:
            self.worker.task_state.last_error = "当前资源/控制器下无可执行任务"
            self.worker.events.send_log(self.worker.task_state.last_error)
            return False

        if not self.worker.agents.ensure_started_once():
            return False

        cleaned_options: TaskOptionsByTask = {}
        for task_name, task_options in options.items():
            if not isinstance(task_name, str) or not isinstance(task_options, dict):
                continue

            cleaned_task_options: dict[str, TaskOptionValue] = {}
            for key, value in task_options.items():
                if not isinstance(key, str):
                    continue
                if value is None:
                    cleaned_task_options[key] = ""
                elif isinstance(value, list):
                    cleaned_task_options[key] = [
                        item for item in value if isinstance(item, str)
                    ]
                elif isinstance(value, dict):
                    cleaned_task_options[key] = {
                        input_key: input_value
                        for input_key, input_value in value.items()
                        if isinstance(input_key, str) and isinstance(input_value, str)
                    }
                else:
                    cleaned_task_options[key] = value

            cleaned_options[task_name] = cleaned_task_options

        state = self.worker.task_state
        if not state.lock.acquire(blocking=False):
            return False
        try:
            if state.running:
                return False
            if state.stop_flag:
                # 前置阶段已收到停止请求：保持标志，不启动任务线程
                return False
            state.stop_flag = False
            state.running = True
            state.last_status = "running"
            state.last_error = None
            state.current_task_name = task_name
            state.thread = threading.Thread(
                target=self.run_process,
                args=(
                    filtered_task_list,
                    copy.deepcopy(cleaned_options),
                    pre_tasks or [],
                    copy.deepcopy(global_options or {}),
                ),
                daemon=True,
            )
            state.thread.start()
            return True
        finally:
            state.lock.release()

    def stop(self) -> bool:
        state = self.worker.task_state
        state.stop_flag = True
        self.worker.pretasks.stop_current()
        while self.worker.tasker.running:
            time.sleep(0.5)
        return True

    def run_process(
        self,
        task_list: list[str],
        options: TaskOptionsByTask,
        pre_tasks: list[PreTaskCommand] | None = None,
        global_options: dict[str, TaskOptionValue] | None = None,
    ):
        state = self.worker.task_state
        state.pre_tasks = pre_tasks or []
        try:
            self.worker.events.emit_task_started(task_list)
            for task_name in task_list:
                if state.stop_flag:
                    self.worker.tasker.post_stop().wait()
                    state.last_status = "stopped"
                    state.last_error = "任务已终止"
                    self.worker.events.send_log("任务已终止")
                    self.worker.events.emit_task_failed(task_list, "任务已终止")
                    return

                task_definition = self._get_task_definition(task_name)
                if task_definition is None:
                    self.worker.events.send_log(f"跳过任务 {task_name}: 未找到任务定义")
                    continue

                pipeline_override = self.worker.pipeline.build_task_pipeline_override(
                    task_name,
                    options.get(task_name, {}),
                    global_options or {},
                )
                if pipeline_override:
                    task_result = self.worker.tasker.post_task(
                        task_definition.entry, pipeline_override
                    )
                else:
                    task_result = self.worker.tasker.post_task(task_definition.entry)
                self.worker.events.send_log("正在运行任务: " + task_name)
                while not task_result.done:
                    time.sleep(0.5)
                    if state.stop_flag:
                        self.worker.tasker.post_stop().wait()
                        state.last_status = "stopped"
                        state.last_error = "任务已终止"
                        self.worker.events.send_log("任务已终止")
                        self.worker.events.emit_task_failed(task_list, "任务已终止")
                        return
            state.last_status = "success"
            state.last_error = None
            self.worker.events.emit_task_completed(task_list)
        except Exception as exc:
            traceback.print_exc()
            state.last_status = "failed"
            state.last_error = str(exc) or "任务执行失败"
            self.worker.events.emit_task_failed(task_list, state.last_error)
            self.worker.events.send_log("任务出现异常，请检查终端日志")
            self.worker.events.send_log(
                f"请将日志反馈至 {self.worker.interface.github}/issues"
            )
        finally:
            state.running = False
            state.thread = None
            state.current_task_name = None
            state.current_pre_task_process = None
            time.sleep(0.5)
