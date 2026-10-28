import ast
import importlib.abc
import importlib.machinery
import importlib.util
import os
import re
import subprocess
import sys
import traceback
import types
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from maa_utils import MaaWorker

from maa.agent_client import AgentClient

from app_paths import resolve_app_root

# Sink 基类名称映射 — 用于 AST 隐式继承检测
_SINK_BASE_CLASS_MAP: dict[str, str] = {
    "ResourceEventSink": "resource",
    "ControllerEventSink": "controller",
    "TaskerEventSink": "tasker",
    "ContextEventSink": "context",
}


class _DepsFirstFinder(importlib.abc.MetaPathFinder):
    """让 deps 目录中的顶级包优先于其他导入器解析。"""

    def __init__(self, deps_path: Path):
        self.deps_path = deps_path.resolve()
        self.top_level_modules: set[str] = set()
        self.refresh()

    def refresh(self) -> None:
        modules: set[str] = set()
        extension_suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)

        if self.deps_path.is_dir():
            for child in self.deps_path.iterdir():
                name = child.name

                if child.is_dir():
                    if name.isidentifier():
                        modules.add(name)
                    continue

                if name.endswith(".py"):
                    module_name = Path(name).stem
                elif any(name.endswith(suffix) for suffix in extension_suffixes):
                    module_name = name.split(".", 1)[0]
                else:
                    continue

                if module_name.isidentifier():
                    modules.add(module_name)

        self.top_level_modules = modules

    def find_spec(self, fullname: str, path=None, target=None):
        top_level = fullname.partition(".")[0]
        if top_level not in self.top_level_modules:
            return None

        search_path = path
        spec = importlib.machinery.PathFinder.find_spec(fullname, search_path, target)
        if spec is None:
            return None

        if not self._is_spec_from_deps(spec):
            return None

        return spec

    def _is_spec_from_deps(self, spec) -> bool:
        origin = spec.origin
        if origin and origin not in {"built-in", "frozen", "namespace"}:
            return self._is_relative_to_deps(origin)

        locations = spec.submodule_search_locations or []
        return any(self._is_relative_to_deps(location) for location in locations)

    def _is_relative_to_deps(self, path_value: str) -> bool:
        try:
            return Path(path_value).resolve().is_relative_to(self.deps_path)
        except Exception:
            return False


_deps_first_finder: _DepsFirstFinder | None = None


def _resolve_runtime_root() -> Path:
    return resolve_app_root()


def _resolve_runtime_path(path_value: str, runtime_root: Path) -> Path:
    normalized = path_value.replace("{PROJECT_DIR}", str(runtime_root))
    candidate = Path(normalized)
    if not candidate.is_absolute():
        candidate = runtime_root / candidate
    return candidate.resolve()


def _resolve_agent_index_path(agent_config: Any, runtime_root: Path) -> Path:
    for arg in agent_config.child_args or []:
        if isinstance(arg, str) and arg.endswith(".py"):
            return _resolve_runtime_path(arg, runtime_root).parent
    raise AssertionError("Agent解析错误，无法找到Agent文件夹")


def _ensure_sys_path_priority(path: Path, index: int) -> None:
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(index, path_str)


def _ensure_deps_first_finder(
    deps_path: Path,
) -> None:
    global _deps_first_finder

    deps_path = deps_path.resolve()

    if _deps_first_finder is not None and _deps_first_finder.deps_path != deps_path:
        if _deps_first_finder in sys.meta_path:
            sys.meta_path.remove(_deps_first_finder)
        _deps_first_finder = None

    if _deps_first_finder is None:
        _deps_first_finder = _DepsFirstFinder(deps_path)
    else:
        _deps_first_finder.refresh()

    if _deps_first_finder in sys.meta_path:
        sys.meta_path.remove(_deps_first_finder)
    sys.meta_path.insert(0, _deps_first_finder)


def _disable_deps_first_finder() -> None:
    global _deps_first_finder

    if _deps_first_finder is not None and _deps_first_finder in sys.meta_path:
        sys.meta_path.remove(_deps_first_finder)
    _deps_first_finder = None


def _module_comes_from_path(module: types.ModuleType, base_path: Path) -> bool:
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    if origin and origin not in {"built-in", "frozen", "namespace"}:
        try:
            if Path(origin).resolve().is_relative_to(base_path):
                return True
        except Exception:
            pass

    module_file = getattr(module, "__file__", None)
    if module_file:
        try:
            if Path(module_file).resolve().is_relative_to(base_path):
                return True
        except Exception:
            pass

    module_paths = getattr(module, "__path__", None) or []
    for location in module_paths:
        try:
            if Path(location).resolve().is_relative_to(base_path):
                return True
        except Exception:
            continue

    return False


def _evict_conflicting_deps_modules(
    deps_path: Path,
    protected_top_levels: set[str] | None = None,
) -> None:
    protected = protected_top_levels or set()
    top_level_modules = (
        _deps_first_finder.top_level_modules if _deps_first_finder else set()
    )

    modules_to_evict: set[str] = set()
    conflicting_top_levels: list[str] = []

    for top_level in sorted(top_level_modules):
        if top_level in protected:
            continue

        module = sys.modules.get(top_level)
        if module is None:
            continue

        if _module_comes_from_path(module, deps_path):
            continue

        conflicting_top_levels.append(top_level)
        prefix = f"{top_level}."
        for module_name in tuple(sys.modules):
            if module_name == top_level or module_name.startswith(prefix):
                modules_to_evict.add(module_name)

    for module_name in modules_to_evict:
        sys.modules.pop(module_name, None)


def _cleanup_agent_processes(
    agent_processes: list[subprocess.Popen],
    send_log: Callable[[str], None],
) -> None:
    for process in agent_processes:
        try:
            if process.poll() is not None:
                continue
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        except Exception as e:
            send_log(f"Agent进程回收失败(pid={process.pid}): {e}")


class _BlackMagicAgentServer:
    """黑魔法导入用的 AgentServer 替身，保留装饰器语义但不触发真实注册。"""

    @staticmethod
    def _noop_decorator():
        def wrapper(*args, **kwargs):
            def decorator(target):
                return target

            return decorator

        return wrapper

    custom_action = _noop_decorator.__func__()
    custom_recognition = _noop_decorator.__func__()
    resource_sink = _noop_decorator.__func__()
    controller_sink = _noop_decorator.__func__()
    tasker_sink = _noop_decorator.__func__()
    context_sink = _noop_decorator.__func__()

    @staticmethod
    def register_custom_action(*args, **kwargs) -> bool:
        return True

    @staticmethod
    def register_custom_recognition(*args, **kwargs) -> bool:
        return True

    @staticmethod
    def add_resource_sink(*args, **kwargs) -> None:
        return None

    @staticmethod
    def add_controller_sink(*args, **kwargs) -> None:
        return None

    @staticmethod
    def add_tasker_sink(*args, **kwargs) -> None:
        return None

    @staticmethod
    def add_context_sink(*args, **kwargs) -> None:
        return None

    @staticmethod
    def start_up(*args, **kwargs) -> bool:
        return True

    @staticmethod
    def join(*args, **kwargs) -> None:
        return None

    @staticmethod
    def shut_down(*args, **kwargs) -> None:
        return None

    @staticmethod
    def detach(*args, **kwargs) -> None:
        return None


@contextmanager
def _black_magic_agent_server_stub():
    """
    临时注入 maa.agent / maa.agent.agent_server 的 stub，
    防止导入 AgentServer 时把全局 Library 切到 agent_server 模式。
    """
    maa_module = importlib.import_module("maa")
    saved_modules = {
        name: sys.modules.get(name) for name in ("maa.agent", "maa.agent.agent_server")
    }
    had_agent_attr = hasattr(maa_module, "agent")
    saved_agent_attr = getattr(maa_module, "agent", None)

    stub_agent_module = types.ModuleType("maa.agent")
    stub_agent_module.__package__ = "maa.agent"
    stub_agent_module.__path__ = []

    stub_agent_server_module = types.ModuleType("maa.agent.agent_server")
    stub_agent_server_module.__package__ = "maa.agent"
    stub_agent_server_module.AgentServer = _BlackMagicAgentServer

    stub_agent_module.agent_server = stub_agent_server_module

    sys.modules["maa.agent"] = stub_agent_module
    sys.modules["maa.agent.agent_server"] = stub_agent_server_module
    maa_module.agent = stub_agent_module

    try:
        yield
    finally:
        for name, saved in saved_modules.items():
            if saved is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved

        if had_agent_attr:
            maa_module.agent = saved_agent_attr
        else:
            delattr(maa_module, "agent")


def run_black_magic(agent_config: Any, maa_worker: "MaaWorker"):
    """
    将Agent转换为custom的黑魔法
    动态加载并注册自定义 Action、Recognition 以及 EventSink 子类
    """
    tasker = maa_worker.tasker
    controller = maa_worker.device_state.controller
    resource = maa_worker.resource
    runtime_root = _resolve_runtime_root()
    agent_index_path = _resolve_agent_index_path(agent_config, runtime_root)
    deps_path = runtime_root / "deps"

    if deps_path.is_dir():
        _ensure_deps_first_finder(deps_path)
        _ensure_sys_path_priority(agent_index_path, 0)
        _ensure_sys_path_priority(deps_path, 1)
        _evict_conflicting_deps_modules(deps_path, protected_top_levels={"maa"})
    else:
        _disable_deps_first_finder()
        _ensure_sys_path_priority(agent_index_path, 0)

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
            with open(file_path, encoding="utf-8") as f:
                source = f.read()

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
    to_register = {"action": [], "recognition": [], "sink": []}

    for module_name, info in module_map.items():
        file_path = info.get("path")
        try:
            with open(file_path, encoding="utf-8") as f:
                source = f.read()
            lines = source.splitlines(True)

            for i, line in enumerate(lines):
                match_action = re.match(custom_action_pattern, line.strip())
                match_recognition = re.match(custom_recognition_pattern, line.strip())

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

            # --- AST 隐式继承检测：EventSink 子类 -------------------------------
            try:
                tree = ast.parse(source, filename=file_path)
                for node in ast.walk(tree):
                    if not isinstance(node, ast.ClassDef):
                        continue
                    for base in node.bases:
                        base_name: str | None = None
                        if isinstance(base, ast.Name):
                            base_name = base.id
                        elif isinstance(base, ast.Attribute):
                            base_name = base.attr
                        if base_name is None or base_name not in _SINK_BASE_CLASS_MAP:
                            continue
                        sink_type = _SINK_BASE_CLASS_MAP[base_name]
                        to_register["sink"].append(
                            {
                                "class_name": node.name,
                                "module_name": module_name,
                                "sink_type": sink_type,
                            }
                        )
                        break  # 只匹配第一个能够识别的基类
            except SyntaxError as e:
                print(f"Syntax error in {file_path}: {e}")
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
            traceback.print_exc()
            raise

    try:
        with _black_magic_agent_server_stub():
            # 加载所有模块（支持循环/相互导入）
            for module_name in module_map:
                try:
                    importlib.import_module(module_name)
                except Exception as e:
                    print(f"Warning: Failed to import module {module_name}: {e}")
                    traceback.print_exc()
                    raise

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
                        raise

            # --- 注册嵌入式 Sink -------------------------------------------------
            for item in to_register["sink"]:
                try:
                    module = sys.modules.get(item["module_name"])
                    if module is None:
                        continue
                    cls = getattr(module, item["class_name"])
                    instance = cls()
                    sink_type = item["sink_type"]

                    if sink_type == "resource":
                        resource.add_sink(instance)
                    elif sink_type == "controller":
                        if controller is not None:
                            controller.add_sink(instance)
                    elif sink_type == "tasker":
                        tasker.add_sink(instance)
                    elif sink_type == "context":
                        tasker.add_context_sink(instance)
                except Exception as e:
                    print(
                        f"Warning: Failed to register sink "
                        f"'{item['class_name']}' ({item['sink_type']}): {e}"
                    )
                    traceback.print_exc()
                    raise
    finally:
        # 确保清理 loader，避免污染全局导入链
        if loader in sys.meta_path:
            sys.meta_path.remove(loader)


def load_agents(
    agent_configs: list[Any],
    maa_worker: "MaaWorker",
    pi_env: dict[str, str] | None = None,
) -> list[subprocess.Popen]:
    agent_processes: list[subprocess.Popen] = []
    errors: list[str] = []

    if not agent_configs:
        return agent_processes
    for agent_config in agent_configs:
        if "python" in agent_config.child_exec and agent_config.embedded:
            assert agent_config.child_args, "Agent解析错误，缺少child_args"
            try:
                if pi_env:
                    os.environ.update(pi_env)
                run_black_magic(agent_config, maa_worker)
            except Exception as e:
                maa_worker.events.send_log("黑魔法爆炸了！")
                maa_worker.events.send_log(f"自定义Agent加载失败: {e}")
                errors.append(f"自定义Agent加载失败: {e}")
                traceback.print_exc()
        else:
            agent_client = AgentClient()
            agent_client.bind(maa_worker.resource)
            agent_client.register_sink(
                maa_worker.resource,
                maa_worker.device_state.controller,
                maa_worker.tasker,
            )
            socket_id = agent_client.identifier
            command = [agent_config.child_exec]
            if agent_config.child_args:
                command += agent_config.child_args
            command.append(socket_id)
            try:
                env = os.environ.copy()
                if pi_env:
                    env.update(pi_env)
                agent_process = subprocess.Popen(command, env=env)
                if not agent_client.connect():
                    raise RuntimeError("Agent连接失败")
                agent_processes.append(agent_process)
                maa_worker.agent_state.agent_client = agent_client
            except Exception as e:
                maa_worker.events.send_log(f"Agent进程启动失败: {e}")
                errors.append(f"Agent进程启动失败: {e}")
                traceback.print_exc()

    if errors:
        _cleanup_agent_processes(agent_processes, maa_worker.events.send_log)
        raise RuntimeError("；".join(errors))

    return agent_processes
