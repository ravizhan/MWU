from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from models.device_address import (
    DeviceType,
    canonicalize_custom_device_address,
    canonicalize_runtime_device_address,
)

RealtimeEventName = Literal[
    "log",
    "focus.display",
    "focus.modal",
    "task.started",
    "task.completed",
    "task.failed",
    "notification.test",
]
RealtimeEventLevel = Literal["info", "success", "error"]


class DeviceModel(BaseModel):
    type: DeviceType
    controller_name: str = ""
    name: str = ""
    adb_path: str = ""
    address: str = ""
    screencap_methods: int | str = 0
    input_methods: int | str = 0
    hWnd: int = 0
    gamepad_type: int = 0
    uuid: str = ""
    config: dict = {}

    @model_validator(mode="after")
    def _validate_device_fields(self) -> "DeviceModel":
        if self.type in ("Adb", "PlayCover", "Linux"):
            self.address = canonicalize_runtime_device_address(self.type, self.address)
        elif self.type == "Win32":
            self.hWnd = int(
                canonicalize_runtime_device_address("Win32", str(self.hWnd))
            )
        elif self.type == "Gamepad":
            hwnd, gamepad_type = canonicalize_runtime_device_address(
                "Gamepad", f"{self.hWnd}|{self.gamepad_type}"
            ).split("|")
            self.hWnd = int(hwnd)
            self.gamepad_type = int(gamepad_type)
        return self


class CustomDeviceCreate(BaseModel):
    """User-entered device address to persist and merge with scan results."""

    controller_name: str = Field(..., description="interface.json controller name")
    type: DeviceType
    address: str = Field(..., description="Device address (format depends on type)")

    @field_validator("controller_name", mode="before")
    @classmethod
    def strip_and_require(cls, value: Any) -> str:
        if value is None:
            raise ValueError("must not be empty")
        text = str(value).strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @model_validator(mode="after")
    def _canonicalize_address(self) -> "CustomDeviceCreate":
        self.address = canonicalize_custom_device_address(self.type, self.address)
        return self


class FocusModal(BaseModel):
    id: str
    message: str
    level: RealtimeEventLevel


class RealtimeEvent(BaseModel):
    event: RealtimeEventName
    level: RealtimeEventLevel = "info"
    message: str
    time: str
    notify: list[str] = Field(default_factory=list)
    title: str | None = None
    details: dict[str, Any] | None = None
    display: bool = True
    focus_modals: list[FocusModal] | None = None
