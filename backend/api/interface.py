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
    PROJECT_DIR,
    app_state,
    interface,
    interface_lock,
    interface_translations,
)

router = APIRouter()


class ScanSelectRescanRequest(BaseModel):
    option_name: str


class ProjectEntry(BaseModel):
    name: str
    path: str
    is_dir: bool


@router.get("/api/file")
def get_file(path: str):
    try:
        resolved_path = resolve_interface_relative_path(
            PROJECT_DIR,
            path,
            field_name="path",
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "failed", "message": str(exc)},
        )
    return FileResponse(resolved_path)


@router.get("/api/file/list")
def list_project_dir(path: str = ""):
    """列出项目目录内某一层的子项，供 file/directory 输入的选择器懒加载。"""
    try:
        directory = (
            resolve_interface_relative_path(
                PROJECT_DIR, path, field_name="path", allow_directories=True
            )
            if path.strip()
            else PROJECT_DIR
        )
        entries = [
            ProjectEntry(
                name=entry.name,
                path=entry.relative_to(PROJECT_DIR).as_posix(),
                is_dir=entry.is_dir(),
            )
            for entry in directory.iterdir()
            if (entry.is_dir() or entry.is_file())
            and entry.resolve().is_relative_to(PROJECT_DIR)
        ]
    except (ValueError, OSError) as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "failed", "message": str(exc)},
        )
    entries.sort(key=lambda entry: (not entry.is_dir, entry.name.casefold()))
    return {"status": "success", "entries": entries}


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
            cases = rescan_scan_select_option(interface, option_name, PROJECT_DIR)
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
