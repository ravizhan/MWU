from pydantic import BaseModel
from typing import Optional, Literal


class Update(BaseModel):
    autoUpdate: bool
    updateChannel: Literal["stable", "beta"]
    proxy: str
    mirrorchyanCdk: str = ""


class Notification(BaseModel):
    systemNotification: bool = False
    browserNotification: bool = False
    externalNotification: bool = False
    webhook: str
    contentType: Literal["application/json", "application/x-www-form-urlencoded"] = (
        "application/json"
    )
    headers: str = ""
    body: str = ""
    username: str = ""
    password: str = ""
    method: Literal["POST", "GET"] = "POST"
    notifyOnComplete: bool
    notifyOnError: bool


class UI(BaseModel):
    darkMode: Optional[bool | str] = "auto"


class Runtime(BaseModel):
    timeout: int
    reminderInterval: int
    autoRetry: bool
    maxRetryCount: int


class About(BaseModel):
    version: str
    author: str
    github: str
    license: str
    description: str
    contact: str
    issueUrl: str


class SettingsModel(BaseModel):
    update: Update
    notification: Notification
    ui: UI
    runtime: Runtime
    about: About
