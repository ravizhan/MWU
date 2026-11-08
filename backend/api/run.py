"""任务启停、Focus 确认、通知测试、SSE 日志流与日志打包导出。"""

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from backend.core import json_utils as json
from backend.core import secret_store
from backend.maa_worker import execution
from backend.models.scheduler import ManualStartPayload
from backend.models.task_config import TaskConfigModel
from backend.runtime import APP_ROOT_DIR, TASK_CONFIG_FILE, app_state
from backend.services import log_export

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


def _saved_task_config() -> TaskConfigModel:
    if not TASK_CONFIG_FILE.exists():
        return TaskConfigModel()
    with TASK_CONFIG_FILE.open("r", encoding="utf-8") as f:
        return TaskConfigModel(**secret_store.reveal(json.load(f)))


@router.get("/api/logs/export")
async def export_logs():
    """打包日志为 zip 下载；当前保存的与本进程运行用过的 password 明文在打包时抹掉。

    先快照文本日志再收集密码：之后启动的运行写入的新密码不会出现在快照里。
    """
    text_logs = await asyncio.to_thread(
        log_export.snapshot_text_logs, APP_ROOT_DIR, list(app_state.history_message)
    )
    secrets = list(app_state.run_secrets)
    option_maps = [app_state.settings.globalOptionValues]
    task_config = await asyncio.to_thread(_saved_task_config)
    for preset in task_config.presets.values():
        option_maps.extend(preset.taskOptions.values())
    if app_state.scheduler_manager is not None:
        for task in await app_state.scheduler_manager.get_all_tasks():
            option_maps.extend(task.task_options.values())
    secrets += secret_store.password_values(option_maps)

    bundle = await asyncio.to_thread(
        log_export.build_bundle, APP_ROOT_DIR, text_logs, secrets
    )
    return FileResponse(
        bundle,
        media_type="application/zip",
        filename=time.strftime("mwu-logs-%Y%m%d-%H%M%S.zip"),
        background=BackgroundTask(bundle.unlink),
    )
