"""设备连接、资源选择、实时画面、截图与点击。"""

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse

from backend.models.api import ClickPayload, CustomDeviceCreate, DeviceModel
from backend.runtime import (
    app_state,
    interface,
)

router = APIRouter()


async def video_stream_generator(fps: int = 15):
    fps = max(1, min(60, fps))
    interval = 1.0 / fps

    while not app_state.is_shutting_down:
        if app_state.worker and app_state.worker.device_state.connected:
            frame_bytes = await asyncio.to_thread(app_state.worker.get_screencap_bytes)
            if frame_bytes:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
                await asyncio.sleep(interval)
                continue
        await asyncio.sleep(0.5)


@router.get("/api/stream/live")
async def stream_live(fps: int = 15):
    return StreamingResponse(
        video_stream_generator(fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/api/device/screenshot")
async def screenshot():
    png = await asyncio.to_thread(app_state.worker.get_screencap_bytes, "PNG")
    if png is None:
        return JSONResponse(
            {"status": "failed", "message": "截图失败，请确认设备已连接"},
            status_code=409,
        )
    filename = time.strftime("screenshot-%Y%m%d-%H%M%S.png")
    return Response(
        png,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/device/click")
async def click(payload: ClickPayload):
    if await asyncio.to_thread(app_state.worker.click, payload.x, payload.y):
        return {"status": "success"}
    return {"status": "failed", "message": "点击失败，请确认设备已连接"}


@router.get("/api/device")
def get_device(controller: str | None = None):
    data = app_state.worker.device.get_device(controller)
    return {"status": "success", "data": data}


@router.post("/api/device")
async def connect_device(device: DeviceModel):
    if await asyncio.to_thread(app_state.worker.device.connect, device):
        return {"status": "success"}
    msg = app_state.worker.device_state.last_device_error or "设备连接失败"
    return {"status": "failed", "message": msg}


@router.post("/api/device/custom")
def add_custom_device(payload: CustomDeviceCreate):
    try:
        device = app_state.worker.device.add_custom_device(payload)
        return {"status": "success", "data": device}
    except ValueError as e:
        return {"status": "failed", "message": str(e)}
    except OSError as e:
        return {"status": "failed", "message": f"保存自定义设备失败: {e}"}


@router.get("/api/device/state")
def get_device_state():
    if (
        app_state.worker.device_state.connected
        and not app_state.worker.device.is_connection_alive()
    ):
        app_state.worker.device.reset_connection_state(
            "检测到设备连接已断开，已解除设备与资源锁定"
        )

    return {
        "status": "success",
        "state": {
            "connected": app_state.worker.device_state.connected,
            "configuration_locked": app_state.worker.device_state.configuration_locked,
            "controller_name": app_state.worker.device_state.controller_name,
            "resource_name": app_state.worker.device_state.current_resource_name,
        },
    }


@router.get("/api/resource")
def get_resource(controller_type: Annotated[str | None, Query()] = None):
    controller_names = (
        {c.name for c in interface.controller if c.type == controller_type}
        if controller_type
        else None
    )
    resources = [
        {
            "name": r.name,
            "label": r.label,
            "icon": r.icon,
            "controller": r.controller,
        }
        for r in interface.resource
        if controller_names is None
        or not r.controller
        or not controller_names.isdisjoint(r.controller)
    ]
    return {"status": "success", "resource": resources}


@router.post("/api/resource")
async def set_resource(name: str):
    # 设置资源
    if not app_state.worker.device_state.connected:
        msg = "请先连接设备后再选择资源"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        ok = await asyncio.to_thread(app_state.worker.device.set_resource, name)
        if not ok:
            msg = app_state.worker.device_state.last_resource_error or "设置资源失败"
            return {"status": "failed", "message": msg}
    except Exception as e:
        app_state.send_log(f"设置资源失败: {e}")
        return {"status": "failed", "message": str(e)}
    return {"status": "success"}
