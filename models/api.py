from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field


class DeviceModel(BaseModel):
    type: Literal["Adb", "Win32", "Gamepad", "PlayCover"]
    name: str
    adb_path: str
    address: str
    screencap_methods: int | str
    input_methods: int | str
    hWnd: int
    gamepad_type: int
    uuid: str = ""
