import logging
import os
import threading
from pathlib import Path
from typing import Any

import json_utils as json
import secret_store
from app_paths import resolve_app_root
from models.settings import SettingsModel

logger = logging.getLogger(__name__)

# 保护 settings.json 的读-改-写序列（设备列表与 /api/settings 都会改写同一文件）。
# read_settings_raw / atomic_write_json 自身不加锁，调用方必须在持有本锁时
# 完成「读 → 改 → 写」，避免嵌套加锁。
SETTINGS_LOCK = threading.Lock()


def default_settings_path() -> Path:
    """Return config/settings.json under the frozen or source app root."""
    return resolve_app_root() / "config" / "settings.json"


def read_settings_raw(path: Path) -> dict[str, Any]:
    """Read settings.json. Missing or corrupt files yield {} (corruption is logged)."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning(f"读取设置文件失败，按空设置处理: {path}: {exc}")
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically write a JSON file (tmp + fsync + os.replace).

    The temp name includes pid and thread id, so concurrent writers never share it;
    callers still serialize read-modify-write sequences (e.g. SETTINGS_LOCK).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def load_settings_model(path: Path, **validate_kwargs: Any) -> SettingsModel:
    """Load settings from path; missing/corrupt/invalid → defaults (logged)."""
    raw = read_settings_raw(path)
    raw["globalOptionValues"] = secret_store.reveal(raw.get("globalOptionValues", {}))
    try:
        return SettingsModel.model_validate(raw, **validate_kwargs)
    except ValueError as exc:
        logger.warning(f"校验设置失败，使用默认值: {path}: {exc}")
        return SettingsModel()


def write_settings_preserving_custom_devices(
    path: Path, settings: SettingsModel
) -> None:
    """Write settings while force-preserving panel.customDevices from disk.

    Frontend POST /api/settings must not wipe custom devices saved by the
    device service.
    """
    with SETTINGS_LOCK:
        payload = settings.model_dump()
        disk = read_settings_raw(path)
        disk_panel = disk.get("panel") if isinstance(disk, dict) else None
        if isinstance(disk_panel, dict) and "customDevices" in disk_panel:
            panel = payload.get("panel")
            if not isinstance(panel, dict):
                panel = {}
                payload["panel"] = panel
            panel["customDevices"] = disk_panel["customDevices"]
        payload["globalOptionValues"] = secret_store.seal_option_map(
            payload["globalOptionValues"]
        )
        atomic_write_json(path, payload)
