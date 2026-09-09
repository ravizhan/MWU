import logging
import os
import threading
from pathlib import Path
from typing import Any

import json_utils as json
from models.settings import SettingsModel, TelemetryConsent
from services.runtime_info import app_root

SETTINGS_LOCK = threading.RLock()
_logger = logging.getLogger("mwu.settings_io")

# 当前合法的设备类型；持久化的旧/非法类型只移除对应条目并本地告警，
# 不触发整体默认回退。
_LEGAL_DEVICE_TYPES = {"Adb", "Win32", "MacOS", "Gamepad", "PlayCover", "Linux"}


def default_settings_path() -> Path:
    """Return config/settings.json under the frozen or source app root."""
    return app_root() / "config" / "settings.json"


def read_settings_raw(path: Path) -> dict[str, Any]:
    """Read settings.json under lock. Corrupt or missing files yield {}."""
    with SETTINGS_LOCK:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw


def atomic_write_settings(path: Path, data: dict[str, Any]) -> None:
    """Atomically write settings.json under lock (tmp + fsync + os.replace)."""
    with SETTINGS_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".settings.json.{os.getpid()}.tmp")
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
    """Load and validate settings from path. Missing/corrupt → defaults."""
    raw = read_settings_raw(path)
    _prune_illegal_device_entries(raw)
    try:
        return SettingsModel.model_validate(raw, **validate_kwargs)
    except Exception:
        return SettingsModel()


def _prune_illegal_device_entries(raw: dict[str, Any]) -> None:
    """移除类型不再合法的持久化设备条目（仅记录本地警告）。

    覆盖 panel.lastConnectedDevice / recentDevices / customDevices；
    只删除类型非法的单条记录，其余设置原样保留，避免旧配置触发整体默认回退。
    """
    if not isinstance(raw, dict):
        return
    panel = raw.get("panel")
    if not isinstance(panel, dict):
        return

    def _prune_record(record: Any, where: str) -> Any:
        if not isinstance(record, dict):
            return record
        device_type = record.get("type")
        if isinstance(device_type, str) and device_type in _LEGAL_DEVICE_TYPES:
            return record
        _logger.warning(
            "settings 中 %s 设备类型 %r 已不受支持，已移除该记录",
            where,
            device_type,
        )
        return None

    last = panel.get("lastConnectedDevice")
    if isinstance(last, dict):
        pruned = _prune_record(last, "lastConnectedDevice")
        if pruned is None:
            del panel["lastConnectedDevice"]

    recent = panel.get("recentDevices")
    if isinstance(recent, list):
        kept = [
            record
            for record in recent
            if _prune_record(record, "recentDevices") is not None
        ]
        if len(kept) != len(recent):
            panel["recentDevices"] = kept

    custom = panel.get("customDevices")
    if isinstance(custom, list):
        kept = [
            record
            for record in custom
            if _prune_record(record, "customDevices") is not None
        ]
        if len(kept) != len(custom):
            panel["customDevices"] = kept


def write_settings_preserving_protected(
    path: Path,
    settings: SettingsModel,
    *,
    telemetry_override: TelemetryConsent | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write settings while force-preserving disk-owned settings fields.

    Frontend POST /api/settings must not wipe custom devices saved by the
    device service or change telemetry consent through an old/stale snapshot.
    Returns the final dict written to disk.
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
        if telemetry_override is not None:
            if isinstance(telemetry_override, TelemetryConsent):
                payload["telemetry"] = telemetry_override.model_dump()
            else:
                payload["telemetry"] = dict(telemetry_override)
        elif isinstance(disk, dict) and isinstance(disk.get("telemetry"), dict):
            payload["telemetry"] = disk["telemetry"]
        else:
            # A legacy settings file has no consent section.  Do not allow a
            # stale frontend snapshot to grant telemetry while adding the
            # section during a normal settings POST.
            payload["telemetry"] = TelemetryConsent().model_dump()
        atomic_write_settings(path, payload)
        return payload
