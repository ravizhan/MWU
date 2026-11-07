"""FastAPI 应用装配：生命周期、静态资源托管与路由注册。"""

import asyncio
import webbrowser
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import config, device, run, scheduler, update
from backend.api import interface as interface_api
from backend.core import settings_io
from backend.core.state import LogBroadcaster
from backend.maa_worker import execution
from backend.maa_worker.worker import MaaWorker
from backend.runtime import (
    APP_ROOT_DIR,
    INDEX_FILE,
    PROJECT_DIR,
    SCHEDULER_DB_PATH,
    SETTINGS_FILE,
    app_state,
    interface,
    interface_translations,
)
from backend.scheduler.manager import SchedulerManager
from backend.scheduler.system_scheduler import SystemScheduler
from backend.services import telemetry


async def log_monitor():
    while not app_state.is_shutting_down:
        try:
            while not app_state.message_conn.empty():
                message = app_state.message_conn.get_nowait()
                if message.event == "focus.modal":
                    # modal 快照是状态而非日志，不进历史；重连时由 stream_logs 补发当前快照。
                    await app_state.broadcaster.broadcast(message)
                    continue
                app_state.history_message.append(message)
                await app_state.broadcaster.broadcast(message)
            await asyncio.sleep(0.1)
        except Exception as exc:
            # 异常退出会让 SSE 永久静默，记录后继续推送
            telemetry.capture_exception(exc, stage="log_monitor")
            app_state.send_log(f"日志推送异常: {exc}")
            await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.is_shutting_down = False
    app_state.worker = MaaWorker(app_state, interface, interface_translations)
    app_state.broadcaster = LogBroadcaster()
    app_state.settings = settings_io.load_settings_model(
        SETTINGS_FILE, context={"interface": interface}
    )
    telemetry.apply_consent(app_state.settings.telemetry.helpImproveSoftware)
    # 初始化系统级调度
    app_state.scheduler_db_path = SCHEDULER_DB_PATH
    await asyncio.to_thread(execution.init_db, SCHEDULER_DB_PATH)
    app_state.system_scheduler = SystemScheduler(APP_ROOT_DIR)
    app_state.scheduler_manager = SchedulerManager(
        app_state, SCHEDULER_DB_PATH, app_state.system_scheduler
    )
    await app_state.scheduler_manager.initialize(paused=True)
    desired = await app_state.scheduler_manager.get_all_tasks()
    report = app_state.system_scheduler.converge(desired)
    if report.list_error is not None:
        app_state.send_log(f"查询系统级唤醒注册状态失败: {report.list_error}")
    # 启动时注册失败的任务自动降级为应用内派发，避免静默失能
    for task_id, error in report.failed.items():
        task = await app_state.scheduler_manager.get_task(task_id)
        if task and task.wakeup_enabled:
            ok = await app_state.scheduler_manager.degrade_wakeup(task_id)
            if ok:
                app_state.send_log(
                    f"系统级唤醒注册失败，已降级为应用内派发: {task.name}。"
                    f"请前往定时任务面板重新启用唤醒。错误: {error}"
                )
            else:
                app_state.send_log(f"降级任务 {task_id} 失败")
    app_state.send_log(
        f"系统级调度收敛完成: 注册 {len(report.registered)} 个, "
        f"注销 {len(report.unregistered)} 个, 失败 {len(report.failed)} 个"
    )
    app_state.scheduler_manager.scheduler.resume()

    if app_state.pending_scheduled_task_id:
        pending_id = app_state.pending_scheduled_task_id
        app_state.pending_scheduled_task_id = None
        task = await app_state.scheduler_manager.get_task(pending_id)
        if task is not None and task.enabled and task.wakeup_enabled:
            app_state.send_log(f"冷启动执行系统级任务: {task.name}")
            # 准入只写一条执行记录，运行本身在后台任务中进行
            admission = await execution.submit_scheduled(
                app_state, task, origin="native"
            )
            if not admission.accepted:
                app_state.send_log(
                    f"冷启动系统级任务跳过: {task.name}"
                    f" (原因: {admission.skip_status or '未知'})"
                )

    monitor_task = asyncio.create_task(log_monitor())
    webbrowser.open_new("http://127.0.0.1:5566")
    yield
    app_state.is_shutting_down = True
    monitor_task.cancel()
    with suppress(asyncio.CancelledError):
        await monitor_task
    if app_state.active_execution_task:
        app_state.active_execution_task.cancel()
        with suppress(asyncio.CancelledError):
            await app_state.active_execution_task
    await app_state.scheduler_manager.shutdown()
    app_state.worker.shutdown()
    telemetry.shutdown()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic 验证错误统一返回 422 + {status, message, errors} 信封。"""
    errors: list[dict[str, str]] = []
    for issue in exc.errors():
        loc = issue.get("loc", ())
        # Skip "body" prefix from FastAPI loc tuples
        path_parts = [str(p) for p in loc if p != "body"]
        field_path = ".".join(path_parts) if path_parts else "unknown"
        msg = issue.get("msg", "validation error")
        errors.append({"field": field_path, "message": msg})
    return JSONResponse(
        status_code=422,
        content={
            "status": "failed",
            "message": "请求参数验证失败",
            "errors": errors,
        },
    )


app.mount("/assets", StaticFiles(directory=str(APP_ROOT_DIR / "page/assets")))
app.mount("/resource", StaticFiles(directory=str(PROJECT_DIR / "resource")))

for module in (interface_api, device, config, update, run, scheduler):
    app.include_router(module.router)


@app.middleware("http")
async def spa_middleware(request: Request, call_next):
    response = await call_next(request)
    if response.status_code == 404 and not (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/assets/")
        or request.url.path.startswith("/resource/")
    ):
        return FileResponse(INDEX_FILE)
    return response


@app.get("/")
async def serve_homepage():
    return FileResponse(INDEX_FILE)
