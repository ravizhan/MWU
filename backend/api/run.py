"""任务启停、Focus 确认、通知测试与 SSE 日志流。"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.core import json_utils as json
from backend.maa_worker import execution
from backend.models.scheduler import ManualStartPayload
from backend.runtime import app_state

router = APIRouter()


@router.post("/api/test-notification")
def test_notification():
    try:
        app_state.worker.events.send_notification(
            "测试通知",
            "这是一条测试通知。",
            event="notification.test",
        )
        return {"status": "success"}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"发送测试通知失败: {msg}")
        return {"status": "failed", "message": msg}


@router.post("/api/start")
async def start(payload: ManualStartPayload):
    admission = await execution.submit_manual(app_state, payload)
    if admission.accepted:
        return {"status": "success", "run_id": admission.run_id}
    if admission.conflict is not None:
        return {"status": "conflict", "conflict": admission.conflict.model_dump()}
    return {"status": "failed", "message": admission.skip_status or "任务启动失败"}


@router.post("/api/stop")
async def stop():
    ok = await execution.stop_active(app_state)
    if ok:
        return {"status": "success"}
    return {"status": "failed", "message": "任务未开始"}


@router.post("/api/focus/{focus_id}/confirm")
def confirm_focus(focus_id: str):
    app_state.worker.focus.confirm(focus_id)
    return {"status": "success"}


@router.get("/api/logs")
async def stream_logs(request: Request):
    q = app_state.broadcaster.add_client(app_state.history_message)
    # 建连即发送当前 pending 快照（空数组表示无 modal），
    # 清除断线期间已在其他标签页确认的旧弹窗。
    q.put_nowait(app_state.worker.focus.snapshot())

    async def event_generator():
        try:
            while not app_state.is_shutting_down:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps(data.model_dump(), ensure_ascii=False)}\n\n"
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            app_state.broadcaster.remove_client(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",
        },
    )
