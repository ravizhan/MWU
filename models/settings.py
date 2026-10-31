from typing import Literal

from pydantic import BaseModel, Field, field_validator

from models.device_address import DeviceType
from models.scheduler import TaskOptionValue


class Update(BaseModel):
    autoUpdate: bool = True
    updateChannel: Literal["stable", "beta"] = "stable"
    proxy: str = ""
    mirrorchyanCdk: str = ""


class Notification(BaseModel):
    systemNotification: bool = False
    browserNotification: bool = False
    externalNotification: bool = False
    webhook: str = ""
    contentType: Literal["application/json", "application/x-www-form-urlencoded"] = (
        "application/json"
    )
    headers: str = ""
    body: str = ""
    username: str = ""
    password: str = ""
    method: Literal["POST", "GET"] = "POST"
    notifyOnComplete: bool = True
    notifyOnError: bool = True


class UI(BaseModel):
    darkMode: bool | str | None = "auto"
    # None 表示尚未保存过语言，前端加载成功后用本地语言补写
    language: Literal["zh-CN", "en-US"] | None = None


class Runtime(BaseModel):
    timeout: int = Field(default=300, ge=60, le=3600)
    autoRetry: bool = True
    maxRetryCount: int = Field(default=3, ge=1, le=10)
    retryInterval: int = Field(default=5, ge=1)


class PanelLastConnectedDevice(BaseModel):
    type: DeviceType
    controller_name: str = ""
    fingerprint: str = ""
    adb_path: str = ""
    address: str = ""
    class_name: str = ""
    window_name: str = ""
    hWnd: int = 0
    gamepad_type: int = 0
    uuid: str = ""


class CustomDevice(BaseModel):
    """Persisted custom device address record.

    Stored in panel.customDevices within settings.json and merged with
    scan results at read time via DeviceService.
    """

    controller_name: str
    type: DeviceType
    address: str


class Panel(BaseModel):
    lastResource: str = ""
    lastConnectedDevice: PanelLastConnectedDevice | None = None
    recentDevices: list[PanelLastConnectedDevice] | None = None
    customDevices: list[CustomDevice] = []

    @field_validator("recentDevices")
    @classmethod
    def truncate_recent_devices(
        cls, v: list[PanelLastConnectedDevice] | None
    ) -> list[PanelLastConnectedDevice] | None:
        if v is not None and len(v) > 5:
            return v[:5]
        return v


class TelemetrySettings(BaseModel):
    helpImproveSoftware: bool = True


class SettingsModel(BaseModel):
    update: Update = Update()
    notification: Notification = Notification()
    ui: UI = UI()
    runtime: Runtime = Runtime()
    panel: Panel = Panel()
    telemetry: TelemetrySettings = TelemetrySettings()
    globalOptionValues: dict[str, TaskOptionValue] = Field(default_factory=dict)
