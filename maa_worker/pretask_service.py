import json
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

from models.interface import Option, Pretask
from models.scheduler import PreTaskCommand, TaskOptionsByTask, TaskOptionValue

if TYPE_CHECKING:
    from maa_utils import MaaWorker


PRE_TASK_OUTPUT_MAX_LINES = 1000
PRE_TASK_OUTPUT_MAX_CHARS = 8000
PI_PRETASK_TIMEOUT = 30


class PretaskError(RuntimeError):
    pass


class PretaskStopped(PretaskError):
    pass


class PretaskService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def run_all(
        self,
        controller_name: str,
        resource_name: str,
        task_options: TaskOptionsByTask,
        user_pre_tasks: list[PreTaskCommand],
        global_options: dict[str, TaskOptionValue] | None = None,
    ) -> None:
        """Run matching PI pretasks first, then enabled user shell commands."""
        raw_pretasks = self.worker.interface.pretask
        if raw_pretasks is None:
            pi_pretasks: list[Pretask] = []
        elif isinstance(raw_pretasks, list):
            pi_pretasks = raw_pretasks
        else:
            pi_pretasks = [raw_pretasks]

        for pretask in pi_pretasks:
            if pretask.controller and controller_name not in pretask.controller:
                continue
            if pretask.resource and resource_name not in pretask.resource:
                continue

            display_name = pretask.label or pretask.name or pretask.exec
            argv = [pretask.exec, *(pretask.args or [])]
            if pretask.option:
                option_values = self._resolve_option_values(
                    pretask,
                    task_options,
                    global_options or {},
                )
                argv.append(
                    json.dumps(
                        option_values,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
            self._run_one(
                argv,
                display_name,
                PI_PRETASK_TIMEOUT,
                is_shell=False,
            )

        for pre_task in user_pre_tasks:
            if not pre_task.enabled or not pre_task.command.strip():
                continue
            self._run_one(
                pre_task.command,
                pre_task.command,
                pre_task.timeout,
                is_shell=True,
            )

    def _resolve_option_values(
        self,
        pretask: Pretask,
        task_options: TaskOptionsByTask,
        global_options: dict[str, TaskOptionValue],
    ) -> dict[str, TaskOptionValue]:
        option_map = self.worker.interface.option or {}
        values: dict[str, TaskOptionValue] = {}
        for option_name in pretask.option or []:
            resolved_value = self._find_option_value(task_options, option_name)
            if resolved_value is not None:
                values[option_name] = resolved_value
                continue
            global_value = global_options.get(option_name)
            if global_value is not None:
                values[option_name] = global_value
                continue
            option = option_map.get(option_name)
            values[option_name] = (
                self._default_option_value(option) if option is not None else ""
            )
        return values

    @staticmethod
    def _find_option_value(
        task_options: TaskOptionsByTask, option_name: str
    ) -> TaskOptionValue | None:
        """task_options 按任务条目 ID 分组；pretask.option 所列 option 为全局声明，
        从所有选中任务的已提交选项中查找该 option 的用户配置值。"""
        for per_task in task_options.values():
            if isinstance(per_task, dict) and option_name in per_task:
                return per_task[option_name]
        return None

    @staticmethod
    def _default_option_value(option: Option) -> TaskOptionValue:
        if option.type in {"select", "switch"}:
            case_names = [case.name for case in option.cases or []]
            if (
                isinstance(option.default_case, str)
                and option.default_case in case_names
            ):
                return option.default_case
            return case_names[0] if case_names else ""
        if option.type == "checkbox":
            if isinstance(option.default_case, list):
                return [
                    value for value in option.default_case if isinstance(value, str)
                ]
            return []
        if option.type in {"input", "hotkey"}:
            fields = option.inputs if option.type == "input" else option.hotkeys
            return {field.name: field.default or "" for field in fields or []}
        return ""

    def _run_one(
        self,
        argv_or_command: list[str] | str,
        display_name: str,
        timeout: int,
        *,
        is_shell: bool,
    ) -> None:
        state = self.worker.task_state
        if state.stop_flag:
            error = PretaskError(f"前置任务已停止: {display_name}")
            self._notify_failure(display_name, error)
            raise error

        self.worker.events.send_log(f"执行前置程序: {display_name}")
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                if is_shell
                else subprocess.CREATE_NO_WINDOW
            )

        try:
            process = subprocess.Popen(
                argv_or_command,
                shell=is_shell,
                cwd=str(self.worker.context.interface_base_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        except FileNotFoundError as exc:
            executable = (
                argv_or_command[0]
                if isinstance(argv_or_command, list) and argv_or_command
                else display_name
            )
            error = PretaskError(f"前置任务程序未找到: {executable}")
            self._notify_failure(display_name, error)
            raise error from exc
        except Exception as exc:
            error = PretaskError(f"前置任务启动失败: {display_name}\n{exc}")
            self._notify_failure(display_name, error)
            raise error from exc

        state.current_pre_task_process = process
        output_lines: list[str] = []
        stdout = process.stdout

        def _reader() -> None:
            if stdout is None:
                return
            try:
                for line in stdout:
                    output_lines.append(line)
            except Exception:
                pass

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()
        started_at = time.monotonic()
        timed_out = False
        stopped = False

        try:
            while process.poll() is None:
                if state.stop_flag:
                    stopped = True
                    break
                if time.monotonic() - started_at > timeout:
                    timed_out = True
                    break
                time.sleep(0.1)

            if stopped or timed_out:
                self._terminate_process(process)
            reader_thread.join(timeout=2)
        finally:
            state.current_pre_task_process = None

        output = self._truncate_output(output_lines)
        if output:
            for line in output.splitlines():
                self.worker.events.send_log(line)

        if stopped:
            error = PretaskError(f"前置任务已停止: {display_name}")
            self._notify_failure(display_name, error)
            raise error
        if timed_out:
            error = PretaskError(f"前置任务执行超时（{timeout}s）: {display_name}")
            self._notify_failure(display_name, error)
            raise error

        return_code = process.returncode
        if return_code != 0:
            message = f"前置任务执行失败（退出码 {return_code}）: {display_name}"
            if output:
                message = f"{message}\n{output}"
            error = PretaskError(message)
            self._notify_failure(display_name, error)
            raise error

        self.worker.events.send_log(f"前置程序执行成功: {display_name}")

    @staticmethod
    def _truncate_output(output_lines: list[str]) -> str:
        output = "".join(output_lines[-PRE_TASK_OUTPUT_MAX_LINES:]).strip()
        if len(output) > PRE_TASK_OUTPUT_MAX_CHARS:
            output = output[-PRE_TASK_OUTPUT_MAX_CHARS:]
        return output

    def _notify_failure(self, display_name: str, error: PretaskError) -> None:
        self.worker.events.send_log(f"前置程序执行失败: {display_name}")
        self.worker.events.send_notification(
            "前置程序执行失败",
            str(error),
            notify=["notification"],
        )

    def stop_current(self) -> None:
        process = self.worker.task_state.current_pre_task_process
        if process is not None and process.poll() is None:
            self._terminate_process(process)

    @staticmethod
    def _terminate_process(process: subprocess.Popen) -> None:
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=2)
        except Exception:
            if sys.platform == "win32":
                try:
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                        check=False,
                    )
                except Exception:
                    pass
            else:
                try:
                    process.kill()
                except Exception:
                    pass
