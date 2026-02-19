import os
import subprocess
import time
import traceback
from queue import SimpleQueue
import json
import plyer
import threading
from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
import importlib.util
import importlib.abc
import re
import sys
from pathlib import Path
import httpx
import io
from PIL import Image
from models.interface import InterfaceModel
from models.settings import SettingsModel

resource = Resource()
resource.set_cpu()


class MaaWorker:
    def __init__(self, message_conn: SimpleQueue, interface):
        Toolkit.init_option("./")
        self.interface: InterfaceModel = interface
        self.message_conn = message_conn
        self.tasker = Tasker()
        self.controller = None
        self.connected = False
        self.stop_flag = False
        self.running = False
        self._task_lock = threading.Lock()
        self._task_thread: threading.Thread | None = None
        self.send_log("MAA初始化成功")
        self.agent_process: subprocess.Popen | None = None
        self.load_agent()
        self.send_log("Agent加载完成")
        self.http_client = httpx.Client(timeout=30)

    def send_log(self, msg):
        self.message_conn.put(
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())} {msg}"
        )
        time.sleep(0.05)

    def send_notification(self, title, message):
        with open("config/settings.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
        settings = SettingsModel(**config_data)
        if settings.notification.systemNotification:
            plyer.notification.notify(
                title=title, message=message, app_name=self.interface.label, timeout=30
            )
        if settings.notification.externalNotification:
            try:
                body = json.loads(
                    settings.notification.body.replace("{{title}}", title).replace(
                        "{{message}}", message
                    )
                )
                if settings.notification.method == "POST":
                    headers = {}
                    if settings.notification.headers:
                        headers = json.loads(settings.notification.headers)
                    auth = None
                    if (
                        settings.notification.username
                        and settings.notification.password
                    ):
                        auth = (
                            settings.notification.username,
                            settings.notification.password,
                        )
                    if settings.notification.contentType == "application/json":
                        self.http_client.post(
                            settings.notification.webhook,
                            headers=headers,
                            json=body,
                            auth=auth,
                        )
                    else:
                        self.http_client.post(
                            settings.notification.webhook,
                            headers=headers,
                            data=body,
                            auth=auth,
                        )
                else:
                    self.http_client.get(settings.notification.webhook, params=body)
            except Exception as e:
                self.send_log(f"外部通知发送失败: {e}")

    def get_device(self) -> dict:
        devices = {"adb": [], "win32": []}
        for controller in self.interface.controller:
            if controller.type == "Adb":
                for device in Toolkit.find_adb_devices():
                    # 这两个字段的数字在JS里会整数溢出，转为字符串处理
                    device.input_methods = str(device.input_methods)
                    device.screencap_methods = str(device.screencap_methods)
                    if device not in devices["adb"]:
                        devices["adb"].append(device)
            elif controller.type == "Win32":
                for device in Toolkit.find_desktop_windows():
                    class_match = not controller.win32.class_regex or re.search(
                        controller.win32.class_regex, device.class_name
                    )
                    window_match = not controller.win32.window_regex or re.search(
                        controller.win32.window_regex, device.window_name
                    )
                    if class_match and window_match and device not in devices["win32"]:
                        devices["win32"].append(device)
        return devices

    def connect_device(self, device) -> bool:
        controller = AdbController(
            adb_path=device.adb_path,
            address=device.address,
            screencap_methods=device.screencap_methods,
            input_methods=device.input_methods,
            config=device.config,
        )
        status = controller.post_connection().wait().succeeded
        conn_fail_msg = "设备连接失败，请检查终端日志"
        if not status:
            plyer.notification.notify(
                title=self.interface.title,
                message=conn_fail_msg,
                app_name=self.interface.label,
                timeout=30,
            )
            self.send_log(conn_fail_msg)
            return self.connected
        if self.tasker.bind(resource, controller):
            self.connected = True
            self.controller = controller
            self.send_log("设备连接成功")
        else:
            plyer.notification.notify(
                title=self.interface.title,
                message=conn_fail_msg,
                app_name=self.interface.label,
                timeout=30,
            )
            self.send_log(conn_fail_msg)
        return self.connected

    def set_resource(self, resource_name):
        def replace(path: str):
            return os.path.realpath(path.replace("{PROJECT_DIR}", os.getcwd()))

        for i in self.interface.resource:
            if i.name == resource_name:
                resource.post_bundle(replace(i.path[0])).wait()
                if len(i.path) > 1:
                    resource.post_bundle(replace(i.path[1])).wait()
                self.send_log(f"资源已设置为: {i.name}")
        return None

    def set_option(self, option_name: str, case_name: str, input_value: str = ""):
        if option_name.split("_")[0] in self.interface.option:
            option = self.interface.option[option_name]
            if option.type in ["select", "switch"] and option.cases:
                for case in option.cases:
                    if case.name == case_name:
                        resource.override_pipeline(case.pipeline_override)
                        # self.send_log(f"选项 {option_name} 设置为: {case_name}")
                        return
            elif option.type == "input" and option.pipeline_override:
                temp = json.dumps(option.pipeline_override)
                input_name = option_name.split("_")[1]
                for field in option.inputs:
                    if field.name == input_name:
                        if field.pipeline_type == "bool":
                            input_value = (
                                "true"
                                if input_value.lower() in ["true", "1", "yes", "y"]
                                else "false"
                            )
                        elif field.pipeline_type == "int":
                            input_value = str(int(input_value))
                        elif field.pipeline_type == "str":
                            input_value = f'"{input_value}"'
                        temp = temp.replace(f'"{{{input_name}}}"', input_value)
                resource.override_pipeline(json.loads(temp))
                return

    def black_magic(self):
        """
        将Agent转换为custom的黑魔法
        动态加载并注册自定义 Action 和 Recognition
        """
        agent_index_path = next(
            (
                Path(arg.replace("{PROJECT_DIR}", "./")).resolve().parent
                for arg in self.interface.agent.child_args
                if arg.endswith(".py")
            ),
            None,
        )
        assert agent_index_path is not None, "Agent解析错误，无法找到Agent文件夹"

        # 将agent目录添加到sys.path的开头，确保优先级最高
        if str(agent_index_path) not in sys.path:
            sys.path.insert(0, str(agent_index_path))
            sys.path.insert(1, str(Path("./deps").resolve()))

        # 扫描所有 .py 文件建立映射
        module_map = {}  # module_name -> {path, is_pkg}
        for file_path in agent_index_path.glob("**/*.py"):
            try:
                relative_path = file_path.relative_to(agent_index_path)
                if file_path.name == "__init__.py":
                    module_name = (
                        str(relative_path.parent).replace(os.sep, ".").replace("/", ".")
                    )
                    if module_name in {"", "."}:
                        continue
                    is_pkg = True
                else:
                    module_name = (
                        str(relative_path.with_suffix(""))
                        .replace(os.sep, ".")
                        .replace("/", ".")
                    )
                    is_pkg = False
                if module_name:
                    module_map[module_name] = {"path": str(file_path), "is_pkg": is_pkg}
            except ValueError:
                continue

        # 自定义 Loader，利用 importlib 规范支持循环 / 相互导入
        class AgentLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
            def __init__(self, mapping):
                self.mapping = mapping

            def find_spec(self, fullname, path, target=None):
                if fullname not in self.mapping:
                    return None
                record = self.mapping[fullname]
                if record["is_pkg"]:
                    return importlib.util.spec_from_file_location(
                        fullname,
                        record["path"],
                        loader=self,
                        submodule_search_locations=[os.path.dirname(record["path"])],
                    )
                return importlib.util.spec_from_file_location(
                    fullname, record["path"], loader=self
                )

            def create_module(self, spec):
                return None

            def exec_module(self, module):
                record = self.mapping[module.__name__]
                file_path = record["path"]
                with open(file_path, "r", encoding="utf-8") as f:
                    source = f.read()

                # 移除 @AgentServer 装饰器，避免注册时重复绑定
                if "@AgentServer" in source:
                    filtered_lines = [
                        line for line in source.split("\n") if "AgentServer" not in line
                    ]
                    source = "\n".join(filtered_lines)

                module.__file__ = file_path
                module.__loader__ = self
                if record["is_pkg"]:
                    module.__package__ = module.__name__
                    module.__path__ = [os.path.dirname(file_path)]
                else:
                    module.__package__ = module.__name__.rpartition(".")[0]

                exec(compile(source, file_path, "exec"), module.__dict__)

        loader = AgentLoader(module_map)
        sys.meta_path.insert(0, loader)

        # 收集需要注册的 Action 和 Recognition
        custom_action_pattern = re.compile(r"@AgentServer.custom_action\(\".*\"\)")
        custom_recognition_pattern = re.compile(
            r"@AgentServer.custom_recognition\(\".*\"\)"
        )
        to_register = {"action": [], "recognition": []}

        for module_name, info in module_map.items():
            file_path = info.get("path")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                for i, line in enumerate(lines):
                    match_action = re.match(custom_action_pattern, line.strip())
                    match_recognition = re.match(
                        custom_recognition_pattern, line.strip()
                    )

                    if match_action or match_recognition:
                        name = line.split('("')[1].split('")')[0]
                        if i + 1 < len(lines):
                            class_line = lines[i + 1].strip()
                            if class_line.startswith("class "):
                                class_name = (
                                    class_line.split("class ")[1]
                                    .split("(")[0]
                                    .strip()
                                    .split(":")[0]
                                )
                                key = "action" if match_action else "recognition"
                                to_register[key].append(
                                    {
                                        "name": name,
                                        "class_name": class_name,
                                        "module_name": module_name,
                                    }
                                )
            except Exception as e:
                print(f"Error scanning {file_path}: {e}")

        try:
            # 加载所有模块（支持循环/相互导入）
            for module_name in module_map:
                try:
                    importlib.import_module(module_name)
                except Exception as e:
                    print(f"Warning: Failed to import module {module_name}: {e}")
                    traceback.print_exc()

            # 注册实例
            for key in ["recognition", "action"]:
                for item in to_register[key]:
                    try:
                        module = sys.modules.get(item["module_name"])
                        if module:
                            cls = getattr(module, item["class_name"])
                            instance = cls()
                            if key == "action":
                                resource.register_custom_action(item["name"], instance)
                            else:
                                resource.register_custom_recognition(
                                    item["name"], instance
                                )
                    except Exception as e:
                        print(
                            f"Warning: Failed to register {key} '{item['name']}': {e}"
                        )
                        traceback.print_exc()
        finally:
            # 确保清理 loader，避免污染全局导入链
            if loader in sys.meta_path:
                sys.meta_path.remove(loader)

    def load_agent(self):
        if self.interface.agent is None:
            return
        if "python" in self.interface.agent.child_exec:
            assert getattr(self.interface.agent, "child_args", None), (
                "Agent解析错误，缺少child_args"
            )
            try:
                self.black_magic()
            except Exception as e:
                self.send_log("黑魔法爆炸了！")
                self.send_log(f"自定义Agent加载失败: {e}")
                traceback.print_exc()
        else:
            if self.interface.agent.child_args:
                command = [
                    self.interface.agent.child_exec
                ] + self.interface.agent.child_args
            else:
                command = [self.interface.agent.child_exec]
            try:
                self.agent_process = subprocess.Popen(command)
            except Exception as e:
                self.agent_process = None
                self.send_log(f"Agent进程启动失败: {e}")
                traceback.print_exc()

    def start_task(self, task_list, options: dict[str, str]) -> bool:
        if not self.connected:
            return False
        if not self._task_lock.acquire(blocking=False):
            return False
        try:
            if self.running:
                return False
            print(task_list, options)
            for name, case in options.items():
                self.set_option(name, case)
            self.stop_flag = False
            self.running = True
            self._task_thread = threading.Thread(
                target=self._run_process, args=(task_list,), daemon=True
            )
            self._task_thread.start()
            return True
        finally:
            self._task_lock.release()

    def stop_task(self) -> bool:
        if not self.running:
            return False
        self.stop_flag = True
        while self.tasker.running:
            time.sleep(0.5)
        return True

    def _run_process(self, task_list):
        self.send_log("任务开始")
        try:
            for task in task_list:
                if self.stop_flag:
                    self.tasker.post_stop().wait()
                    self.send_log("任务已终止")
                    return
                t = self.tasker.post_task(task)
                self.send_log("正在运行任务: " + task)
                while not t.done:
                    time.sleep(0.5)
                    if self.stop_flag:
                        self.tasker.post_stop().wait()
                        self.send_log("任务已终止")
                        return
        except Exception:
            traceback.print_exc()
            plyer.notification.notify(
                title=self.interface.title,
                message="任务出现异常，请检查终端日志",
                app_name=self.interface.label,
                timeout=30,
            )
            self.send_log("任务出现异常，请检查终端日志")
            self.send_log(f"请将日志反馈至 {self.interface.github}/issues")
        finally:
            self.running = False
            self._task_thread = None
            self.send_log("所有任务完成")
            time.sleep(0.5)

    def get_screencap_bytes(self):
        if not self.connected or not self.controller:
            return None
        try:
            image = self.controller.post_screencap().wait().get()
            if image is not None:
                image_pil = Image.fromarray(image[:, :, ::-1])
                img_byte_arr = io.BytesIO()
                image_pil.save(img_byte_arr, format="JPEG")
                return img_byte_arr.getvalue()
        except Exception as e:
            pass
        return None
