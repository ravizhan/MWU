from pydantic import BaseModel
from typing import Optional, Literal


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
    darkMode: Optional[bool | str] = "auto"


class Runtime(BaseModel):
    timeout: int = 300
    reminderInterval: int = 30
    autoRetry: bool = True
    maxRetryCount: int = 3


class About(BaseModel):
    version: str = ""
    author: str = ""
    github: str = ""
    license: str = ""
    description: str = ""
    contact: str = ""
    issueUrl: str = ""


class PanelLastConnectedDevice(BaseModel):
    type: Literal["Adb", "Win32", "Gamepad", "PlayCover"]
    fingerprint: str = ""
    adb_path: str = ""
    address: str = ""
    class_name: str = ""
    window_name: str = ""
    hWnd: int = 0
    gamepad_type: int = 0
    uuid: str = ""


class Panel(BaseModel):
    lastResource: str = ""
    lastConnectedDevice: Optional[PanelLastConnectedDevice] = None


class SettingsModel(BaseModel):
    update: Update = Update()
    notification: Notification = Notification()
    ui: UI = UI()
    runtime: Runtime = Runtime()
    about: About = About()
    panel: Panel = Panel()
