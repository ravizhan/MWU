"""进程级运行期单例：应用路径、interface 模型与共享 AppState。"""

import sys
import threading

from backend.core import json_utils as json
from backend.core import secret_store
from backend.core.paths import resolve_app_root, resolve_project_dir
from backend.core.state import AppState
from backend.models.interface_loader import (
    InterfaceLoadError,
    load_interface_model,
    resolve_interface_relative_path,
)
from backend.models.settings import SettingsModel
from backend.models.task_config import TaskConfigModel
from backend.services import telemetry

APP_ROOT_DIR = resolve_app_root()
PROJECT_DIR = resolve_project_dir()
CONFIG_DIR = APP_ROOT_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
TASK_CONFIG_FILE = CONFIG_DIR / "task_config.json"
INDEX_FILE = APP_ROOT_DIR / "page/index.html"
SCHEDULER_DB_PATH = CONFIG_DIR / "scheduler.sqlite"


def load_interface_translations() -> dict[str, dict]:
    translations: dict[str, dict] = {}
    for locale, relative_path in (interface.languages or {}).items():
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise InterfaceLoadError(f"languages[{locale}] 必须是非空字符串")

        resolved_path = resolve_interface_relative_path(
            PROJECT_DIR,
            relative_path,
            field_name=f"languages[{locale}]",
        )
        try:
            with resolved_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            message = getattr(exc, "message", str(exc))
            raise InterfaceLoadError(
                f"解析语言文件失败: {resolved_path}: {message}"
            ) from exc

        if not isinstance(data, dict):
            raise InterfaceLoadError(f"语言文件必须是 JSON 对象: {resolved_path}")
        translations[locale] = data
    return translations


try:
    interface = load_interface_model(PROJECT_DIR)
    interface_translations = load_interface_translations()
except Exception as e:
    print(e)
    input("interface.json加载异常，请修正后重新启动程序，按任意键退出...")
    sys.exit(1)

interface_lock = threading.Lock()
telemetry.configure(interface, APP_ROOT_DIR)
secret_store.configure(interface)


if not CONFIG_DIR.exists():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(SettingsModel().model_dump(), f, indent=4, ensure_ascii=False)
    with TASK_CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(TaskConfigModel().model_dump(), f, indent=4, ensure_ascii=False)


app_state = AppState()
