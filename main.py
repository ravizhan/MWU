import argparse
import asyncio
import hashlib
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

import json_utils as json
import settings_io
from app_state import AppState, LogBroadcaster
from maa_utils import MaaWorker
from maa_worker import execution
from models.api import CustomDeviceCreate, DeviceModel
from models.interface_loader import (
    InterfaceLoadError,
    load_interface_model,
    rescan_scan_select_option,
    resolve_interface_relative_path,
)
from models.scheduler import (
    ManualStartPayload,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
)
from models.settings import SettingsModel
from models.task_config import (
    TaskConfigFormatError,
    TaskConfigModel,
    normalize_task_config,
    validate_task_config_identity,
)
from services.interface_content import (
    InterfaceContentError,
    InterfaceContentService,
)
from services.telemetry_service import (
    TelemetryConsentStaleError,
    TelemetryService,
)
from scheduler_manager import SchedulerManager
from services.system_scheduler import SystemScheduler
from services.update_service import (
    check_github_update,
    check_mirrorchyan_update,
    download_file,
    get_platform_info,
)


from services.runtime_info import app_root as _app_root


APP_ROOT_DIR = _app_root()
CONFIG_DIR = APP_ROOT_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
TASK_CONFIG_FILE = CONFIG_DIR / "task_config.json"
INDEX_FILE = APP_ROOT_DIR / "page/index.html"
NATIVE_TOKEN_FILE = CONFIG_DIR / "native_token"
SCHEDULER_DB_PATH = CONFIG_DIR / "scheduler.sqlite"
EXIT_SUCCESS = 0
EXIT_FAILED = 1


def load_interface_translations() -> dict[str, dict]:
    translations: dict[str, dict] = {}
    for locale, relative_path in (interface.languages or {}).items():
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise InterfaceLoadError(f"languages[{locale}] 必须是非空字符串")

        resolved_path = resolve_interface_relative_path(
            APP_ROOT_DIR,
            relative_path,
            field_name=f"languages[{locale}]",
        )
        try:
            with resolved_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            message = getattr(exc, "message", str(exc))
            raise InterfaceLoadError(
                f"解析语言文件失败: {resolved_path}: {message}"
            ) from exc

        if not isinstance(data, dict):
            raise InterfaceLoadError(f"语言文件必须是 JSON 对象: {resolved_path}")
        translations[locale] = data
    return translations


try:
    interface = load_interface_model(APP_ROOT_DIR)
    interface_translations = load_interface_translations()
except Exception as e:
    print(e)
    input("interface.json加载异常，请修正后重新启动程序，按任意键退出...")
    sys.exit(1)

interface_lock = threading.Lock()


class ScanSelectRescanRequest(BaseModel):
    option_name: str


class InterfaceDocumentRequest(BaseModel):
    source: str
    locale: Literal["zh-CN", "en-US"]


class TelemetryConsentRequest(BaseModel):
    configId: str
    consent: Literal["granted", "denied"]
    failureAttachments: bool = False


class DeviceConnectRequest(BaseModel):
    """/api/device 平面请求：设备 + 必需 resource_name（准备并连接，不加载资源）。"""

    device: DeviceModel
    resource_name: str


if not CONFIG_DIR.exists():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(SettingsModel().model_dump(), f, indent=4, ensure_ascii=False)
    with TASK_CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            TaskConfigModel(taskIdentity="name").model_dump(),
            f,
            indent=4,
            ensure_ascii=False,
        )


app_state = AppState()
_PENDING_SCHEDULED_TASK_ID: str | None = None


class NativeDispatchRequest(BaseModel):
    task_id: str
    token: str


def ensure_native_token() -> str:
    """读取或生成 native token（冷启动委托鉴权用，0600 权限）"""
    try:
        if NATIVE_TOKEN_FILE.exists():
            token = NATIVE_TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError:
        pass
    token = secrets.token_hex(32)
    fd = os.open(NATIVE_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    try:
        os.chmod(NATIVE_TOKEN_FILE, 0o600)
    except PermissionError:
        pass
    return token


def _port_in_use(host: str = "127.0.0.1", port: int = 5566) -> bool:
    """端口已被监听即视为已有实例在运行（单实例判定）"""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def delegate_native_dispatch(task_id: str) -> int:
    """已有实例运行时，将系统级任务通过 HTTP 移交给已运行实例"""
    token = NATIVE_TOKEN_FILE.read_text(encoding="utf-8").strip()
    attempts = 6
    for attempt in range(attempts):
        try:
            response = httpx.post(
                "http://127.0.0.1:5566/api/internal/scheduler/native-dispatch",
                json={"task_id": task_id, "token": token},
                timeout=10,
            )
        except Exception as e:
            # 连接失败：端口已由赢家绑定但服务尚未就绪 → 短退避后重试，避免丢任务。
            # 成功连接后的非 2xx（401/404/409 等）属于应用层拒绝，不重试。
            if attempt < attempts - 1:
                print(
                    f"委托系统级任务失败（第 {attempt + 1}/{attempts} 次，将重试）: {e}",
                    file=sys.stderr,
                )
                time.sleep(2)
                continue
            print(f"委托系统级任务失败: {e}", file=sys.stderr)
            return EXIT_FAILED
        if response.status_code < 200 or response.status_code >= 300:
            print(
                f"委托系统级任务失败: HTTP {response.status_code} {response.text}",
                file=sys.stderr,
            )
            return EXIT_FAILED
        return EXIT_SUCCESS
    return EXIT_FAILED


async def log_monitor():
    while not app_state.is_shutting_down:
        while not app_state.message_conn.empty():
            message = app_state.message_conn.get_nowait()
            # focus.interaction 不进入历史回放（仅实时广播）
            if message.event != "focus.interaction":
                app_state.history_message.append(message)
            if app_state.broadcaster:
                await app_state.broadcaster.broadcast(message)
        # modal 周期提醒（每 5 分钟一次）
        interactions = app_state.focus_interactions
        if interactions is not None and app_state.worker is not None:
            _send_modal_reminders(interactions, app_state.worker.events)
        await asyncio.sleep(0.1)


def _send_modal_reminders(interactions, events):
    for item in interactions.get_pending():
        state = interactions._find(item["id"])
        if state is None or not state.reminder_due:
            continue
        state.mark_reminded()
        events.send_notification(
            "等待确认",
            f"有阻塞任务等待确认：{item['content'][:50]}",
        )
        events.send_log(f"提醒（第 {state.reminder_count} 次）：modal 等待确认中")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.is_shutting_down = False
    app_state.broadcaster = LogBroadcaster()
    with interface_lock:
        # 必须走 load_settings_model：它会先 _prune_illegal_device_entries，
        # 把旧版已删除的设备类型（如 WlRoots）条目移除，避免启动即崩溃。
        app_state.settings = settings_io.load_settings_model(
            SETTINGS_FILE,
            context={"interface": interface},
        )
    # Consent must be loaded and gated before constructing Worker/native
    # services.  Source/debug builds remain an inactive, no-client form.
    app_state.telemetry_service = TelemetryService(
        interface,
        app_state.settings,
        SETTINGS_FILE,
    )
    app_state.worker = MaaWorker(app_state, interface)
    if _PENDING_SCHEDULED_TASK_ID is not None:
        app_state.pending_scheduled_task_id = _PENDING_SCHEDULED_TASK_ID
    # 初始化系统级调度
    app_state.native_token = ensure_native_token()
    app_state.scheduler_db_path = SCHEDULER_DB_PATH
    await asyncio.to_thread(execution.init_db, SCHEDULER_DB_PATH)
    app_state.system_scheduler = SystemScheduler(APP_ROOT_DIR)
    app_state.scheduler_manager = SchedulerManager(
        app_state, SCHEDULER_DB_PATH, app_state.system_scheduler
    )
    await app_state.scheduler_manager.initialize(paused=True)
    desired = await app_state.scheduler_manager.get_all_tasks()
    report = app_state.system_scheduler.converge(desired)
    # 启动时注册失败的任务自动降级为应用内派发，避免静默失能
    for task_id, error in report.failed.items():
        if task_id == "__list__":
            continue
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

            async def _cold_start_native():
                admission = await execution.submit_scheduled(
                    app_state, task, origin="native"
                )
                if not admission.accepted:
                    app_state.send_log(
                        f"冷启动系统级任务跳过: {task.name}"
                        f" (原因: {admission.skip_status or '未知'})"
                    )

            asyncio.create_task(_cold_start_native())

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
    # 唤醒所有 pending modal（cancelled），确保工作线程不被回调阻塞
    if app_state.focus_interactions is not None:
        app_state.focus_interactions.wake_all_for_stop()
    if app_state.scheduler_manager:
        await app_state.scheduler_manager.shutdown()
    if app_state.worker:
        app_state.worker.shutdown()
    if app_state.telemetry_service:
        app_state.telemetry_service.flush_and_close_limited()


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
app.mount("/resource", StaticFiles(directory=str(APP_ROOT_DIR / "resource")))


def _load_normalized_task_config() -> tuple[TaskConfigModel, bool]:
    config_exists = TASK_CONFIG_FILE.exists()

    if config_exists:
        with TASK_CONFIG_FILE.open("r", encoding="utf-8") as f:
            config_data = json.load(f)
    else:
        config_data = TaskConfigModel(taskIdentity="name").model_dump()

    # 严格新格式校验：旧格式（缺标记/entry 身份/未知任务键）报错且原文件不变
    validate_task_config_identity(config_data, interface)

    task_config = TaskConfigModel(**config_data)
    normalized_config = normalize_task_config(task_config, interface)
    normalized_data = normalized_config.model_dump()

    should_write_back = (not config_exists) or config_data != normalized_data
    if should_write_back:
        with TASK_CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(normalized_data, f, indent=4, ensure_ascii=False)

    return normalized_config, should_write_back


def _validate_scheduler_task_names(task_list: list[str]) -> JSONResponse | None:
    """定时任务载荷中的 task name 校验；未知名称返回 422 信封。"""
    from models.task_config import find_unknown_task_names

    unknown = find_unknown_task_names(interface, task_list)
    if not unknown:
        return None
    return JSONResponse(
        status_code=422,
        content={
            "status": "failed",
            "message": "任务名称不在当前 interface 中",
            "errors": [
                {
                    "field": f"task_list[{task_list.index(name)}]",
                    "message": f"未知任务: {name}",
                }
                for name in unknown
            ],
        },
    )


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


@app.get("/api/file")
def get_file(path: str):
    try:
        resolved_path = resolve_interface_relative_path(
            APP_ROOT_DIR,
            path,
            field_name="path",
        )
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if ("不存在" in message or "不是文件" in message) else 400
        return JSONResponse(
            status_code=status_code,
            content={"status": "failed", "message": message},
        )
    return FileResponse(resolved_path)


@app.get("/api/interface")
def get_interface():
    with interface_lock:
        data = interface.model_dump(mode="json")
        if interface_translations:
            data["translations"] = interface_translations
        return data


@app.post("/api/interface/scan-select/rescan")
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


@app.post("/api/interface/document")
def resolve_interface_document(payload: InterfaceDocumentRequest):
    """解析当前已加载 PI 中的文档内容。

    仅接受 PI 文档字段及其翻译值组成的来源集合；
    不开放任意 URL 代理或任意路径读取。
    """
    service = InterfaceContentService(interface, APP_ROOT_DIR, interface_translations)
    allowed = service.collect_document_sources()
    source = payload.source.strip()
    if not source or source not in allowed:
        return JSONResponse(
            status_code=404,
            content={"status": "failed", "message": "未知文档来源"},
        )
    try:
        content = service.resolve_document(payload.source, payload.locale)
    except InterfaceContentError as exc:
        return {
            "status": "failed",
            "message": str(exc),
            "source": source,
        }
    return {"status": "success", "content": content}


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


@app.get("/api/stream/live")
async def stream_live(fps: int = 15):
    return StreamingResponse(
        video_stream_generator(fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/device")
def get_device(controller: str | None = None):
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
    data = app_state.worker.device.get_device(controller)
    return {"status": "success", "data": data}


@app.post("/api/device")
async def connect_device(request: DeviceConnectRequest):
    if app_state.worker is None:
        msg = "Worker未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    device = request.device
    resource_name = request.resource_name.strip()
    if not resource_name:
        return {"status": "failed", "message": "resource_name 不能为空"}
    # 与 _complete_run 共用准备临界区；获取锁后重查运行/更新/关停状态
    async with app_state.preparation_lock:
        if app_state.update_in_progress or app_state.is_shutting_down:
            return {"status": "failed", "message": "更新或关停中，暂不连接设备"}
        if app_state.active_run is not None:
            return {"status": "failed", "message": "任务运行中，暂不连接设备"}
        settings = app_state.settings or SettingsModel()
        global_options = settings.globalOptionValues or {}
        try:
            prepared = await asyncio.to_thread(
                app_state.worker.device.prepare_connection,
                device,
                resource_name,
                global_options,
                [],
            )
        except Exception as e:
            app_state.send_log(f"设备准备失败: {e}")
            return {"status": "failed", "message": str(e)}
        if not prepared:
            msg = app_state.worker.device_state.last_device_error or "设备连接失败"
            return {"status": "failed", "message": msg}
        return {"status": "success"}


@app.post("/api/device/custom")
def add_custom_device(payload: CustomDeviceCreate):
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
    try:
        device = app_state.worker.device.add_custom_device(payload)
        return {"status": "success", "data": device}
    except ValueError as e:
        return {"status": "failed", "message": str(e)}
    except OSError as e:
        return {"status": "failed", "message": f"保存自定义设备失败: {e}"}


@app.get("/api/device/state")
def get_device_state():
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
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


@app.get("/api/resource")
def get_resource(controller_type: str | None = Query(default=None)):
    if app_state.worker is None:
        return {"status": "failed", "message": "Worker未初始化"}
    controller_names = (
        {c.name for c in interface.controller if c.type == controller_type}
        if controller_type
        else None
    )
    resources = [
        {
            "name": r.name,
            "label": r.label,
            "controller": r.controller,
        }
        for r in interface.resource
        if controller_names is None
        or not r.controller
        or not controller_names.isdisjoint(r.controller)
    ]
    return {"status": "success", "resource": resources}


@app.post("/api/resource")
async def set_resource(name: str):
    # 设置资源
    if app_state.worker is None:
        msg = "Worker未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    async with app_state.preparation_lock:
        if app_state.update_in_progress or app_state.is_shutting_down:
            return {"status": "failed", "message": "更新或关停中，暂不设置资源"}
        if app_state.active_run is not None:
            return {"status": "failed", "message": "任务运行中，暂不设置资源"}
        if not app_state.worker.device_state.connected:
            msg = "请先连接设备后再选择资源"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}
        # 准备阶段记录的资源不一致：连接上下文已变化，需重新连接
        prepared = app_state.worker.device_state.prepared_resource_name
        if prepared is not None and prepared != name:
            return {
                "status": "failed",
                "code": "resource_context_changed",
                "message": "连接时的资源上下文已变化，请重新连接设备",
            }
        try:
            ok = await asyncio.to_thread(app_state.worker.device.set_resource, name)
            if not ok:
                msg = (
                    app_state.worker.device_state.last_resource_error or "设置资源失败"
                )
                return {"status": "failed", "message": msg}
        except Exception as e:
            app_state.send_log(f"设置资源失败: {e}")
            return {"status": "failed", "message": str(e)}
        return {"status": "success"}


@app.get("/api/settings")
def get_settings():
    with interface_lock:
        app_state.settings = settings_io.load_settings_model(
            SETTINGS_FILE,
            context={"interface": interface},
        )
    return {"status": "success", "settings": app_state.settings.model_dump()}


@app.post("/api/settings")
def set_settings(settings: SettingsModel):
    written = settings_io.write_settings_preserving_protected(SETTINGS_FILE, settings)
    # Re-validate so app_state reflects preserved customDevices from disk.
    with interface_lock:
        app_state.settings = SettingsModel.model_validate(
            written,
            context={"interface": interface},
        )
    return {"status": "success"}


@app.get("/api/telemetry")
def get_telemetry():
    service = app_state.telemetry_service
    if service is None:
        return {
            "status": "success",
            "configured": False,
            "buildAllowed": False,
            "active": False,
            "configId": "",
            "recipient": None,
            "consent": "unknown",
            "failureAttachments": False,
        }
    return {"status": "success", **service.status_payload()}


@app.post("/api/telemetry/consent")
def set_telemetry_consent(payload: TelemetryConsentRequest):
    service = app_state.telemetry_service
    if service is None:
        return JSONResponse(
            status_code=503,
            content={"status": "failed", "message": "遥测服务未初始化"},
        )
    try:
        result = service.apply_consent(
            payload.configId,
            payload.consent,
            payload.failureAttachments,
        )
        app_state.settings = service.settings
        return {"status": "success", **result}
    except TelemetryConsentStaleError as exc:
        return JSONResponse(
            status_code=409,
            content={"status": "failed", "message": str(exc)},
        )
    except Exception as exc:
        # apply_consent writes atomically before replacing in-memory state, so
        # this path leaves the previous authorization unchanged.
        return JSONResponse(
            status_code=500,
            content={"status": "failed", "message": str(exc)},
        )


@app.get("/api/task-config")
def get_task_config():
    try:
        task_config, _ = _load_normalized_task_config()
        return {"status": "success", "config": task_config.model_dump()}
    except TaskConfigFormatError as e:
        return JSONResponse(
            status_code=422,
            content={
                "status": "failed",
                "code": e.code,
                "message": str(e),
            },
        )
    except Exception as e:
        app_state.send_log(f"获取任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}


@app.post("/api/task-config")
def save_task_config(config: TaskConfigModel):
    try:
        validate_task_config_identity(config.model_dump(), interface)
        normalized_config = normalize_task_config(config, interface)
        with TASK_CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(normalized_config.model_dump(), f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        app_state.send_log(f"保存任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}


@app.delete("/api/task-config")
def reset_task_config():
    try:
        if TASK_CONFIG_FILE.exists():
            TASK_CONFIG_FILE.unlink()
        return {"status": "success"}
    except Exception as e:
        app_state.send_log(f"重置任务配置失败: {e}")
        return {"status": "failed", "message": str(e)}


@app.get("/api/update/check")
def check_update():
    try:
        settings = app_state.settings or SettingsModel()
        current_version = interface.version or ""
        mirrorchyan_rid = getattr(interface, "mirrorchyan_rid", None)
        github_url = interface.github or ""
        cdk = settings.update.mirrorchyanCdk

        if mirrorchyan_rid:
            mc_data = check_mirrorchyan_update(
                mirrorchyan_rid, current_version, cdk, settings
            )
            if mc_data and mc_data.get("code") == 0:
                mc_info = mc_data.get("data", {})
                latest_version = mc_info.get("version_name", "")
                has_update = latest_version and latest_version != current_version

                app_state.update_info = {
                    "latest_version": latest_version,
                    "current_version": current_version,
                    "is_update_available": has_update,
                    "release_notes": mc_info.get("release_note", ""),
                    "download_url": mc_info.get("url", ""),
                    "file_hash": mc_info.get("sha256", ""),
                    "file_name": f"update-{latest_version}.7z",
                    "download_source": "mirrorchyan",
                    "update_type": mc_info.get("update_type", "full"),
                }

                # 有 CDK 且有下载链接，直接返回 mirrorchyan 结果
                if app_state.update_info["download_url"]:
                    return {
                        "status": "success",
                        "update_info": app_state.update_info,
                    }

                # 无 CDK 或无下载链接，尝试 GitHub 获取下载链接
                if has_update and github_url:
                    try:
                        gh_info = check_github_update(
                            github_url,
                            current_version,
                            settings,
                        )
                        if gh_info:
                            # 保留 mirrorchyan 的版本信息，用 GitHub 的下载链接
                            app_state.update_info["download_url"] = gh_info[
                                "download_url"
                            ]
                            app_state.update_info["file_hash"] = gh_info["file_hash"]
                            app_state.update_info["file_name"] = gh_info["file_name"]
                            app_state.update_info["download_source"] = "github"
                    except Exception:
                        pass

                return {
                    "status": "success",
                    "update_info": app_state.update_info,
                }

        if github_url:
            gh_info = check_github_update(github_url, current_version, settings)
            if gh_info:
                app_state.update_info = gh_info
                return {"status": "success", "update_info": app_state.update_info}

            plat, arch = get_platform_info()
            msg = f"未找到适合当前平台的更新包:{plat}-{arch}"
            app_state.send_log(msg)
            return {
                "status": "failed",
                "message": msg,
            }

        msg = "未配置更新源"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"检查更新失败: {msg}")
        return {"status": "failed", "message": msg}


@app.get("/api/update")
async def perform_update():
    try:
        if app_state.update_info is None:
            msg = "暂无可用更新信息"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}

        update_package_path = app_state.update_info["file_name"]
        download_url = app_state.update_info["download_url"]
        download_source = app_state.update_info.get("download_source", "github")
        if os.path.exists(update_package_path):
            os.remove(update_package_path)
        app_state.update_status = {
            "status": "downloading",
            "message": "正在下载更新包...",
        }
        # 更新真正开始：置位准入标志，阻塞 /api/start 与调度准入，防止更新期间启动任务
        app_state.set_update_in_progress()

        try:
            raw_proxy = (
                (app_state.settings or SettingsModel()).update.proxy
                if download_source != "mirrorchyan"
                else None
            )
            proxy = (
                raw_proxy.strip()
                if isinstance(raw_proxy, str) and raw_proxy.strip()
                else None
            )
            await download_file(download_url, update_package_path, proxy)
            file_hash = app_state.update_info.get("file_hash", "")
            if file_hash:
                with open(update_package_path, "rb") as f:
                    file_bytes = f.read()
                    sha256_hash = hashlib.sha256(file_bytes).hexdigest()
                    if sha256_hash != file_hash:
                        raise ValueError("文件哈希校验失败，下载的文件可能已损坏。")
        except Exception as e:
            msg = f"下载失败: {e}"
            app_state.send_log(msg)
            app_state.update_status = {"status": "failed", "message": msg}
            app_state.clear_update_in_progress()
            return {"status": "failed", "message": str(e)}

        def run_updater_loop():
            app_state.update_status = {
                "status": "updating",
                "message": "正在运行更新器...",
            }
            # 更新器循环仅在终态分支（启动失败 / 异常退出 / 正常退出）通过 break 退出；
            # 自更新（returncode 10）用 continue 继续，不触发 finally。
            try:
                while True:
                    cmd = [
                        "./mwu-updater",
                        "-archive",
                        os.path.abspath(update_package_path),
                        "-webhook",
                        "http://127.0.0.1:5566/api/system/shutdown",
                        "-restart-cmd",
                        sys.executable,
                    ]

                    try:
                        process = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                        )

                        if process.stdout:
                            for line in process.stdout:
                                print(f"[Updater] {line.strip()}")
                                try:
                                    data = json.loads(line)
                                    if "status" in data:
                                        app_state.update_status = data
                                except json.JSONDecodeError:
                                    pass
                    except Exception as e:
                        msg = f"启动更新器失败: {e}"
                        app_state.send_log(msg)
                        app_state.update_status = {
                            "status": "failed",
                            "message": msg,
                        }
                        break

                    process.wait()

                    if process.returncode == 10:
                        app_state.update_status = {
                            "status": "updating",
                            "message": "更新器自更新完成，正在重启更新器...",
                        }
                        continue
                    else:
                        if process.returncode != 0:
                            msg = f"更新器异常退出: {process.returncode}，请查看updater.log"
                            app_state.send_log(msg)
                            app_state.update_status = {
                                "status": "failed",
                                "message": msg,
                            }
                        break
            finally:
                # 更新器线程终态：无论失败还是正常退出，均放行任务准入。
                # 成功自更新时进程被 webhook 杀除，此 finally 不执行（进程随 flag 消亡），符合预期。
                app_state.clear_update_in_progress()

        threading.Thread(target=run_updater_loop, daemon=True).start()
        return {"status": "success", "message": "正在后台更新程序..."}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"更新失败: {msg}")
        app_state.update_status = {"status": "failed", "message": msg}
        app_state.clear_update_in_progress()
        return {"status": "failed", "message": msg}


@app.get("/api/update/status")
def get_update_status():
    if app_state.update_status is None:
        return {"status": "idle", "message": "没有正在进行的更新"}
    return app_state.update_status


@app.get("/api/system/shutdown")
def system_shutdown():
    def _shutdown():
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_shutdown, daemon=True).start()
    return {"status": "success", "message": "Shutting down"}


@app.post("/api/test-notification")
def test_notification():
    if app_state.worker is None:
        msg = "Worker未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
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


@app.post("/api/start")
async def start(payload: ManualStartPayload):
    admission = await execution.submit_manual(app_state, payload)
    if admission.accepted:
        return {"status": "success", "run_id": admission.run_id}
    if admission.invalid_task_names:
        return JSONResponse(
            status_code=422,
            content={
                "status": "failed",
                "message": "任务名称不在当前 interface 中",
                "errors": [
                    {
                        "field": f"task_list[{payload.task_list.index(name)}]",
                        "message": f"未知任务: {name}",
                    }
                    for name in admission.invalid_task_names
                ],
            },
        )
    if admission.conflict is not None:
        return {"status": "conflict", "conflict": admission.conflict.model_dump()}
    return {"status": "failed", "message": admission.skip_status or "任务启动失败"}


@app.post("/api/stop")
async def stop():
    ok = await execution.stop_active(app_state)
    if ok:
        return {"status": "success"}
    return {"status": "failed", "message": "任务未开始"}


@app.get("/api/focus/interactions")
def get_focus_interactions():
    """获取当前 pending 的焦点交互（dialog / modal）。"""
    interactions = app_state.focus_interactions
    if interactions is None:
        return {"status": "success", "data": []}
    return {"status": "success", "data": interactions.get_pending()}


@app.post("/api/focus/interactions/{interaction_id}/ack")
def acknowledge_focus_interaction(interaction_id: str):
    """确认一个焦点交互。409 = 已结束；404 = 不存在。"""
    interactions = app_state.focus_interactions
    if interactions is None:
        return JSONResponse(
            status_code=404,
            content={"status": "failed", "message": "交互服务未初始化"},
        )
    state = interactions.acknowledge(interaction_id)
    if state is None:
        return JSONResponse(
            status_code=404,
            content={"status": "failed", "message": "交互不存在或已清理"},
        )
    if state.state != "acknowledged":
        return JSONResponse(
            status_code=409,
            content={
                "status": "failed",
                "message": "交互已结束",
                "data": state.to_public_dict(),
            },
        )
    return {"status": "success", "data": state.to_public_dict()}


@app.post("/api/focus/interactions/{interaction_id}/cancel")
def cancel_focus_interaction(interaction_id: str):
    """取消一个焦点交互。409 = 已结束；404 = 不存在。"""
    interactions = app_state.focus_interactions
    if interactions is None:
        return JSONResponse(
            status_code=404,
            content={"status": "failed", "message": "交互服务未初始化"},
        )
    state = interactions.cancel(interaction_id)
    if state is None:
        return JSONResponse(
            status_code=404,
            content={"status": "failed", "message": "交互不存在或已清理"},
        )
    if state.state != "cancelled":
        return JSONResponse(
            status_code=409,
            content={
                "status": "failed",
                "message": "交互已结束",
                "data": state.to_public_dict(),
            },
        )
    return {"status": "success", "data": state.to_public_dict()}


@app.post("/api/privilege/restart-elevated")
async def restart_elevated():
    """以管理员权限重启当前程序。

    重启前：停止运行中的任务、取消 pending modal、完成已授权的有限遥测收尾。
    不跨进程自动重放任务 payload；用户在新实例中重新启动。
    提权后继续监听 0.0.0.0:5566（用户明确选择保留局域网访问）。
    """
    from services.privilege_service import is_elevated, request_elevation

    if is_elevated():
        return {"status": "failed", "message": "当前已是管理员权限"}
    # 停止运行
    if app_state.worker is not None and app_state.worker.task_state.running:
        app_state.worker.tasks.stop()
    # 取消 pending modal
    if app_state.focus_interactions is not None:
        app_state.focus_interactions.wake_all_for_stop()
    # 已授权遥测的有限收尾（≤2s flush）
    if app_state.telemetry_service is not None:
        app_state.telemetry_service.flush_and_close_limited()
    # 提权重启（服务端构造命令，无客户端输入）
    submitted = await asyncio.to_thread(request_elevation, APP_ROOT_DIR)
    if not submitted:
        return {"status": "failed", "message": "提权请求被拒绝"}

    def _exit():
        time.sleep(1)
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
    return {"status": "success", "message": "提权重启已提交"}


@app.post("/api/internal/scheduler/native-dispatch")
async def native_dispatch(payload: NativeDispatchRequest):
    """冷启动委托入口：由系统级唤醒触发的二次进程将任务移交给本实例"""
    if payload.token != app_state.native_token:
        return JSONResponse(
            status_code=401,
            content={"status": "failed", "message": "无效的 native token"},
        )
    task = await app_state.scheduler_manager.get_task(payload.task_id)
    if task is None:
        return JSONResponse(
            status_code=404,
            content={"status": "failed", "message": "任务不存在"},
        )
    if not task.enabled or not task.wakeup_enabled:
        return JSONResponse(
            status_code=409,
            content={"status": "failed", "message": "任务未启用系统级唤醒"},
        )
    admission = await execution.submit_scheduled(app_state, task, origin="native")
    if admission.accepted:
        return {"status": "success", "run_id": admission.run_id, "skip_status": None}
    return JSONResponse(
        status_code=409,
        content={
            "status": "failed",
            "message": "入场被拒",
            "skip_status": admission.skip_status,
        },
    )


@app.get("/api/logs")
async def stream_logs(request: Request):
    if app_state.broadcaster is None:

        async def empty_generator():
            while (
                not app_state.is_shutting_down and not await request.is_disconnected()
            ):
                yield ": keep-alive\n\n"
                await asyncio.sleep(15)

        return StreamingResponse(empty_generator(), media_type="text/event-stream")

    q = app_state.broadcaster.add_client(app_state.history_message)

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
            if app_state.broadcaster is not None:
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


@app.get("/api/scheduler/tasks")
async def get_scheduler_tasks():
    """获取所有定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        tasks = await app_state.scheduler_manager.get_all_tasks()
        return {"status": "success", "tasks": [task.model_dump() for task in tasks]}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"获取调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.post("/api/scheduler/tasks")
async def create_scheduler_task(task_create: ScheduledTaskCreate):
    """创建定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    invalid = _validate_scheduler_task_names(task_create.task_list)
    if invalid is not None:
        return invalid
    try:
        task = await app_state.scheduler_manager.create_task(task_create)
        return {"status": "success", "task": task.model_dump()}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"创建调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.put("/api/scheduler/tasks/{task_id}")
async def update_scheduler_task(task_id: str, task_update: ScheduledTaskUpdate):
    """更新定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    if task_update.task_list is not None:
        invalid = _validate_scheduler_task_names(task_update.task_list)
        if invalid is not None:
            return invalid
    try:
        task = await app_state.scheduler_manager.update_task(task_id, task_update)
        if task is None:
            msg = "任务不存在"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}
        return {"status": "success", "task": task.model_dump()}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"更新调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.delete("/api/scheduler/tasks/{task_id}")
async def delete_scheduler_task(task_id: str):
    """删除定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        success = await app_state.scheduler_manager.delete_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"删除调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.post("/api/scheduler/tasks/{task_id}/pause")
async def pause_scheduler_task(task_id: str):
    """暂停定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        success = await app_state.scheduler_manager.pause_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"暂停调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.post("/api/scheduler/tasks/{task_id}/resume")
async def resume_scheduler_task(task_id: str):
    """恢复定时任务"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        success = await app_state.scheduler_manager.resume_task(task_id)
        if success:
            return {"status": "success"}
        msg = "任务不存在"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"恢复调度任务失败: {msg}")
        return {"status": "failed", "message": msg}


@app.get("/api/scheduler/executions")
async def get_scheduler_executions(limit: int = 50):
    """获取执行历史"""
    if app_state.scheduler_manager is None:
        msg = "调度器未初始化"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    try:
        executions = await app_state.scheduler_manager.get_executions(limit)
        return {
            "status": "success",
            "executions": [exec.model_dump() for exec in executions],
        }
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"获取调度执行历史失败: {msg}")
        return {"status": "failed", "message": msg}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MWU 启动参数")
    parser.add_argument(
        "--scheduled-task",
        type=str,
        default=None,
        help="系统级调度任务 ID（冷启动时移交给已运行实例或直接执行）",
    )
    args = parser.parse_args()

    if _port_in_use():
        if args.scheduled_task:
            sys.exit(delegate_native_dispatch(args.scheduled_task))
        print("应用已在运行")
        sys.exit(EXIT_FAILED)

    if args.scheduled_task:
        _PENDING_SCHEDULED_TASK_ID = args.scheduled_task

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5566,
        timeout_graceful_shutdown=1,
    )
