from typing import Literal

from pydantic import BaseModel


class DeviceModel(BaseModel):
    type: Literal["Adb", "Win32", "Gamepad", "PlayCover"]
    name: str = ""
    adb_path: str = ""
    address: str = ""
    screencap_methods: int | str = 0
    input_methods: int | str = 0
    hWnd: int = 0
    gamepad_type: int = 0
    uuid: str = ""
