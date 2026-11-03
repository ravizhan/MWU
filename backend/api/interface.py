"""interface.json 与应用根目录文件访问。"""

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.models.interface_loader import (
    InterfaceLoadError,
    rescan_scan_select_option,
    resolve_interface_relative_path,
)
from backend.runtime import (
    APP_ROOT_DIR,
    app_state,
    interface,
    interface_lock,
    interface_translations,
)

router = APIRouter()


class ScanSelectRescanRequest(BaseModel):
    option_name: str


@router.get("/api/file")
def get_file(path: str):
    try:
        resolved_path = resolve_interface_relative_path(
            APP_ROOT_DIR,
            path,
            field_name="path",
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "failed", "message": str(exc)},
        )
    return FileResponse(resolved_path)


@router.get("/api/interface")
def get_interface():
    with interface_lock:
        data = interface.model_dump(mode="json")
        if interface_translations:
            data["translations"] = interface_translations
        return data


@router.post("/api/interface/scan-select/rescan")
def rescan_scan_select(payload: ScanSelectRescanRequest):
    option_name = payload.option_name.strip()
    if not option_name:
        return {"status": "failed", "message": "option_name 不能为空"}

    try:
        with interface_lock:
            cases = rescan_scan_select_option(interface, option_name, APP_ROOT_DIR)
    except InterfaceLoadError as exc:
        return {"status": "failed", "message": str(exc)}
    except Exception as exc:
        app_state.send_log(f"重扫 scan_select 失败: {exc}")
        return {"status": "failed", "message": "重扫失败"}

    return {
        "status": "success",
        "option_name": option_name,
        "cases": cases,
    }
