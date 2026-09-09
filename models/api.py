from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from models.device_address import (
    DeviceType,
    LinuxDeviceAddress,
    canonicalize_custom_device_address,
    canonicalize_ipv4_port,
)

RealtimeEventName = Literal[
    "log",
    "focus.display",
    "focus.interaction",
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
        if self.type == "Adb":
            if not self.address.strip():
                raise ValueError("Adb address must not be empty")
        elif self.type == "PlayCover":
            self.address = canonicalize_ipv4_port(self.address)
        elif self.type == "MacOS":
            if not self.address.strip().isdigit() or int(self.address) <= 0:
                raise ValueError("MacOS address must be a positive integer CGWindowID")
            self.address = str(int(self.address))
        elif self.type == "Linux":
            parsed = LinuxDeviceAddress.from_compact_json(self.address)
            self.address = parsed.to_compact_json()
        elif self.type == "Win32":
            if self.hWnd <= 0:
                raise ValueError("Win32 hWnd must be positive")
        elif self.type == "Gamepad":
            if self.hWnd < 0:
                raise ValueError("Gamepad hWnd must not be negative")
            if self.gamepad_type not in (0, 1):
                raise ValueError("Gamepad type must be 0 or 1")
        return self


class CustomDeviceCreate(BaseModel):
    """User-entered device address to persist and merge with scan results."""

    controller_name: str = Field(..., description="interface.json controller name")
    type: DeviceType
    address: str = Field(..., description="Device address (format depends on type)")

    @field_validator("controller_name", "address", mode="before")
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


class RealtimeEvent(BaseModel):
    event: RealtimeEventName
    level: RealtimeEventLevel = "info"
    message: str
    time: str
    notify: list[str] = Field(default_factory=list)
    title: str | None = None
    details: dict[str, Any] | None = None
    display: bool = True
