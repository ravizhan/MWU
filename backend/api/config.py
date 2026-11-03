"""用户设置与任务配置持久化。"""

from fastapi import APIRouter

from backend.core import json_utils as json
from backend.core import secret_store, settings_io
from backend.models.settings import SettingsModel
from backend.models.task_config import (
    TaskConfigModel,
    normalize_task_config,
)
from backend.runtime import (
    SETTINGS_FILE,
    TASK_CONFIG_FILE,
    app_state,
    interface,
)
from backend.services import telemetry

router = APIRouter()


def _write_task_config(config: TaskConfigModel) -> None:
    """加密各预设中的密码字段后原子写盘；加密失败时原文件保持不变。"""
    data = config.model_dump()
    for preset in data["presets"].values():
        preset["taskOptions"] = secret_store.seal_task_options(preset["taskOptions"])
    settings_io.atomic_write_json(TASK_CONFIG_FILE, data)


def _load_normalized_task_config() -> tuple[TaskConfigModel, bool]:
    config_exists = TASK_CONFIG_FILE.exists()

    if config_exists:
        with TASK_CONFIG_FILE.open("r", encoding="utf-8") as f:
            config_data = secret_store.reveal(json.load(f))
    else:
        config_data = TaskConfigModel().model_dump()

    task_config = TaskConfigModel(**config_data)
    normalized_config = normalize_task_config(task_config, interface)
    normalized_data = normalized_config.model_dump()

    should_write_back = (not config_exists) or config_data != normalized_data
    if should_write_back:
        _write_task_config(normalized_config)

    return normalized_config, should_write_back


@router.get("/api/settings")
def get_settings():
    return {"status": "success", "settings": app_state.settings.model_dump()}


@router.post("/api/settings")
def set_settings(settings: SettingsModel):
    settings_io.write_settings_preserving_custom_devices(SETTINGS_FILE, settings)
    app_state.settings = settings
    telemetry.apply_consent(settings.telemetry.helpImproveSoftware)
    return {"status": "success"}


@router.get("/api/telemetry/status")
def get_telemetry_status():
    return {"status": "success", **telemetry.status()}


@router.get("/api/task-config")
def get_task_config():
    try:
        task_config, _ = _load_normalized_task_config()
        return {"status": "success", "config": task_config.model_dump()}
    except Exception as e:
        app_state.send_log(f"获取任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}


@router.post("/api/task-config")
def save_task_config(config: TaskConfigModel):
    try:
        normalized_config = normalize_task_config(config, interface)
        _write_task_config(normalized_config)
        return {"status": "success"}
    except Exception as e:
        app_state.send_log(f"保存任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}


@router.delete("/api/task-config")
def reset_task_config():
    try:
        if TASK_CONFIG_FILE.exists():
            TASK_CONFIG_FILE.unlink()
        return {"status": "success"}
    except Exception as e:
        app_state.send_log(f"重置任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}
