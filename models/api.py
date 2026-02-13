from pydantic import BaseModel


class DeviceModel(BaseModel):
    name: str
    adb_path: str
    address: str
    screencap_methods: int
    input_methods: int
    config: dict
