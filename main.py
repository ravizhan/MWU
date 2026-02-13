import asyncio
import json
import threading
import webbrowser
from contextlib import asynccontextmanager
from queue import SimpleQueue
import uvicorn
import os
import signal
import sys
import platform
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from models.interface import InterfaceModel
from models.api import DeviceModel
from models.task_config import TaskConfigModel
from models.settings import SettingsModel
from models.scheduler import ScheduledTaskCreate, ScheduledTaskUpdate
from maa_utils import MaaWorker
from scheduler_manager import SchedulerManager
import httpx
import subprocess
import time
import hashlib

with open("interface.json", "r", encoding="utf-8") as f:
    json_data = json.load(f)

interface = InterfaceModel(**json_data)


class LogBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def add_client(self, history: list[str]) -> asyncio.Queue:
        q = asyncio.Queue()
        for msg in history:
            q.put_nowait(msg)
        self._queues.append(q)
        return q

    def remove_client(self, q: asyncio.Queue):
        if q in self._queues:
            self._queues.remove(q)

    async def broadcast(self, message: str):
        for q in self._queues:
            await q.put(message)


class AppState:
    def __init__(self):
        self.message_conn = SimpleQueue()
        self.worker: MaaWorker | None = None
        self.history_message = []
        self.current_status = None
        self.broadcaster: LogBroadcaster | None = None
        self.scheduler_manager: SchedulerManager | None = None
        self.settings: SettingsModel | None = None
        self.subprocess_pipe: subprocess.Popen | None = None
        self.update_status: dict | None = None
        self.update_info: dict | None = None


app_state = AppState()


async def log_monitor():
    while True:
        while not app_state.message_conn.empty():
            msg = app_state.message_conn.get_nowait()
            app_state.history_message.append(msg)
            if app_state.broadcaster:
                await app_state.broadcaster.broadcast(msg)
        await asyncio.sleep(0.1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.worker = MaaWorker(app_state.message_conn, interface)
    app_state.broadcaster = LogBroadcaster()
    with open("config/settings.json", "r", encoding="utf-8") as f:
        config_data = json.load(f)
    app_state.settings = SettingsModel(**config_data)
    # 初始化调度器
    app_state.scheduler_manager = SchedulerManager()
    app_state.scheduler_manager.set_worker(app_state.worker)
    await app_state.scheduler_manager.initialize()

    monitor_task = asyncio.create_task(log_monitor())
    webbrowser.open_new("http://127.0.0.1:55666")
    yield
    monitor_task.cancel()
    if app_state.worker and app_state.worker.agent_process:
        app_state.worker.agent_process.terminate()
    # 关闭调度器
    if app_state.scheduler_manager:
        await app_state.scheduler_manager.shutdown()


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="page/assets"))
app.mount("/resource", StaticFiles(directory="resource"))


@app.middleware("http")
async def spa_middleware(request: Request, call_next):
    response = await call_next(request)
    if response.status_code == 404 and not (
        request.url.path.startswith("/api/")
        or request.url.path.startswith("/assets/")
        or request.url.path.startswith("/resource/")
    ):
        return FileResponse("page/index.html")
    return response


@app.get("/")
async def serve_homepage():
    return FileResponse("page/index.html")


@app.get("/api/interface")
def get_interface():
    return interface.model_dump()


async def video_stream_generator(fps: int = 15):
    fps = max(1, min(60, fps))
    interval = 1.0 / fps

    while True:
        if app_state.worker and app_state.worker.connected:
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
def get_device():
    devices = app_state.worker.get_device()
    return {"status": "success", "devices": devices}


@app.post("/api/device")
async def connect_device(device: DeviceModel):
    if await asyncio.to_thread(app_state.worker.connect_device, device):
        return {"status": "success"}
    return {"status": "failed"}


@app.get("/api/resource")
def get_resource():
    return {"status": "success", "resource": [i.name for i in interface.resource]}


@app.post("/api/resource")
async def set_resource(name: str):
    # 设置资源
    try:
        await asyncio.to_thread(app_state.worker.set_resource, name)
    except Exception as e:
        return {"status": "failed", "message": str(e)}
    return {"status": "success"}


@app.get("/api/settings")
def get_settings():
    with open("config/settings.json", "r", encoding="utf-8") as f:
        config_data = json.load(f)
    app_state.settings = SettingsModel(**config_data)
    return {"status": "success", "settings": app_state.settings.model_dump()}


@app.post("/api/settings")
def set_settings(settings: SettingsModel):
    with open("config/settings.json", "w", encoding="utf-8") as f:
        json.dump(settings.model_dump(), f, indent=4, ensure_ascii=False)
    return {"status": "success"}


@app.get("/api/task-config")
def get_task_config():
    try:
        with open("config/task_config.json", "r", encoding="utf-8") as f:
            config_data = json.load(f)
        user_config = TaskConfigModel(**config_data)
        return {"status": "success", "config": user_config.model_dump()}
    except FileNotFoundError:
        return {"status": "success", "config": TaskConfigModel().model_dump()}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.post("/api/task-config")
def save_task_config(config: TaskConfigModel):
    try:
        with open("config/task_config.json", "w", encoding="utf-8") as f:
            json.dump(config.model_dump(), f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.delete("/api/task-config")
def reset_task_config():
    try:
        config_path = "config/task_config.json"
        if os.path.exists(config_path):
            os.remove(config_path)
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.get("/api/update/check")
def check_update():
    # 优先使用 MirrorChyan 更新渠道
    if interface.mirrorchyan_rid:
        return check_update_mirrorchyan()
    # 否则使用 GitHub 更新渠道
    return check_update_github()


def check_update_mirrorchyan():
    """使用 MirrorChyan 检查更新"""
    try:
        plat = "linux"
        arch = "x64"
        match platform.system():
            case "Windows":
                plat = "win"
            case "Darwin":
                plat = "macos"
            case "Linux":
                plat = "linux"

        machine = platform.machine().lower()
        match machine:
            case "x86_64" | "amd64":
                arch = "x86_64"
            case "arm" | "aarch64" | "arm64":
                arch = "aarch64"

        current_version = interface.version
        rid = interface.mirrorchyan_rid

        # 构建 MirrorChyan API 请求
        params = {"current_version": current_version, "user_agent": "MWU"}

        # 如果配置了多平台支持，添加 os_arch 参数
        if interface.mirrorchyan_multiplatform:
            params["os_arch"] = f"{plat}-{arch}"

        # 如果用户配置了 CDK，添加到请求中
        cdk = ""
        proxy = None
        if app_state.settings:
            cdk = app_state.settings.update.mirrorchyanCdk
            proxy = app_state.settings.update.proxy or None
        if cdk:
            params["cdk"] = cdk

        response = httpx.get(
            f"https://mirrorchyan.com/api/resources/{rid}/latest",
            params=params,
            proxy=proxy,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("code") != 0:
            error_msg = data.get("msg", "未知错误")
            # 如果是 CDK 错误，提示用户
            if data.get("code") in [60001, 60002, 60003]:
                return {
                    "status": "failed",
                    "message": f"CDK 错误: {error_msg}",
                }
            return {
                "status": "failed",
                "message": f"MirrorChyan API 错误: {error_msg}",
            }

        result = data.get("data", {})
        latest_version = result.get("version_name")
        release_note = result.get("release_note", "")
        download_url = result.get("url")

        is_update_available = latest_version != current_version

        app_state.update_info = {
            "latest_version": latest_version,
            "current_version": current_version,
            "is_update_available": is_update_available,
            "release_notes": release_note,
            "download_url": download_url,
            "file_hash": "",  # MirrorChyan 使用 URL 签名验证
            "file_name": f"update-{latest_version}.zip",
        }
        return {"status": "success", "update_info": app_state.update_info}
    except httpx.RequestError as e:
        return {"status": "failed", "message": f"网络请求失败: {str(e)}"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


def check_update_github():
    """使用 GitHub 检查更新"""
    try:
        if not interface.github:
            return {"status": "failed", "message": "未配置 GitHub 仓库地址"}

        repo_name = (
            interface.github.split("/")[3] + "/" + interface.github.split("/")[4]
        )
        response = httpx.get(
            f"https://api.github.com/repos/{repo_name}/releases/latest"
        ).json()
        latest_version = response["tag_name"]
        current_version = interface.version

        plat = "linux"
        arch = "x64"
        match platform.system():
            case "Windows":
                plat = "win"
            case "Darwin":
                plat = "macos"
            case "Linux":
                plat = "linux"

        machine = platform.machine().lower()
        match machine:
            case "x86_64" | "amd64":
                arch = "x86_64"
            case "arm" | "aarch64" | "arm64":
                arch = "aarch64"

        for asset in response.get("assets", []):
            if f"{plat}-{arch}" in asset["name"]:
                download_url = asset["browser_download_url"]
                file_hash = asset["digest"].replace("sha256:", "").strip()
                app_state.update_info = {
                    "latest_version": latest_version,
                    "current_version": current_version,
                    "is_update_available": latest_version != current_version,
                    "release_notes": response["body"],
                    "download_url": download_url,
                    "file_hash": file_hash,
                    "file_name": asset["name"],
                }
                return {"status": "success", "update_info": app_state.update_info}
        return {
            "status": "failed",
            "message": f"未找到适合当前平台的更新包:{plat}-{arch}",
        }
    except Exception as e:
        return {"status": "failed", "message": str(e)}


async def download_file(url: str, dest: str):
    async with httpx.AsyncClient(
        follow_redirects=True, proxy=app_state.settings.update.proxy
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)


@app.get("/api/update")
async def perform_update():
    try:
        update_package_path = app_state.update_info["file_name"]
        download_url = app_state.update_info["download_url"]
        if os.path.exists(update_package_path):
            os.remove(update_package_path)
        app_state.update_status = {
            "status": "downloading",
            "message": "正在下载更新包...",
        }

        try:
            await download_file(download_url, update_package_path)
            with open(update_package_path, "rb") as f:
                file_bytes = f.read()
                sha256_hash = hashlib.sha256(file_bytes).hexdigest()
                if sha256_hash != app_state.update_info["file_hash"]:
                    raise ValueError("文件哈希校验失败，下载的文件可能已损坏。")
        except Exception as e:
            app_state.update_status = {"status": "failed", "message": f"下载失败: {e}"}
            return {"status": "failed", "message": str(e)}

        def run_updater_loop():
            app_state.update_status = {
                "status": "updating",
                "message": "正在运行更新器...",
            }
            while True:
                cmd = [
                    "./mwu-updater",
                    "-archive",
                    os.path.abspath(update_package_path),
                    "-webhook",
                    "http://127.0.0.1:55666/api/system/shutdown",
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
                    app_state.update_status = {
                        "status": "failed",
                        "message": f"启动更新器失败: {e}",
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
                        app_state.update_status = {
                            "status": "failed",
                            "message": f"更新器异常退出: {process.returncode}，请查看updater.log",
                        }
                    break

        threading.Thread(target=run_updater_loop, daemon=True).start()
        return {"status": "success", "message": "正在后台更新程序..."}
    except Exception as e:
        app_state.update_status = {"status": "failed", "message": str(e)}
        return {"status": "failed", "message": str(e)}


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
        return {"status": "failed", "message": "Worker未初始化"}
    try:
        app_state.worker.send_notification("测试通知", "这是一条测试通知。")
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.post("/api/start")
def start(tasks: list[str], options: dict[str, str]):
    if app_state.worker and app_state.worker.running:
        return {"status": "failed", "message": "任务已开始"}
    if not app_state.worker.connected:
        return {"status": "failed", "message": "请先连接设备"}
    app_state.worker.start_task(tasks, options)
    return {"status": "success"}


@app.post("/api/stop")
def stop():
    if app_state.worker is None or not app_state.worker.running:
        return {"status": "failed", "message": "任务未开始"}
    app_state.worker.stop_task()
    return {"status": "success"}


@app.get("/api/logs")
async def stream_logs(request: Request):
    q = app_state.broadcaster.add_client(app_state.history_message)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps({'type': 'log', 'message': data}, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
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
        },
    )


@app.get("/api/scheduler/tasks")
async def get_scheduler_tasks():
    """获取所有定时任务"""
    if app_state.scheduler_manager is None:
        return {"status": "failed", "message": "调度器未初始化"}
    try:
        tasks = await app_state.scheduler_manager.get_all_tasks()
        return {"status": "success", "tasks": [task.model_dump() for task in tasks]}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.post("/api/scheduler/tasks")
async def create_scheduler_task(task_create: ScheduledTaskCreate):
    """创建定时任务"""
    if app_state.scheduler_manager is None:
        return {"status": "failed", "message": "调度器未初始化"}
    try:
        task = await app_state.scheduler_manager.create_task(task_create)
        return {"status": "success", "task": task.model_dump()}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.put("/api/scheduler/tasks/{task_id}")
async def update_scheduler_task(task_id: str, task_update: ScheduledTaskUpdate):
    """更新定时任务"""
    if app_state.scheduler_manager is None:
        return {"status": "failed", "message": "调度器未初始化"}
    try:
        task = await app_state.scheduler_manager.update_task(task_id, task_update)
        if task is None:
            return {"status": "failed", "message": "任务不存在"}
        return {"status": "success", "task": task.model_dump()}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.delete("/api/scheduler/tasks/{task_id}")
async def delete_scheduler_task(task_id: str):
    """删除定时任务"""
    if app_state.scheduler_manager is None:
        return {"status": "failed", "message": "调度器未初始化"}
    try:
        success = await app_state.scheduler_manager.delete_task(task_id)
        if success:
            return {"status": "success"}
        return {"status": "failed", "message": "任务不存在"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.post("/api/scheduler/tasks/{task_id}/pause")
async def pause_scheduler_task(task_id: str):
    """暂停定时任务"""
    if app_state.scheduler_manager is None:
        return {"status": "failed", "message": "调度器未初始化"}
    try:
        success = await app_state.scheduler_manager.pause_task(task_id)
        if success:
            return {"status": "success"}
        return {"status": "failed", "message": "任务不存在"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.post("/api/scheduler/tasks/{task_id}/resume")
async def resume_scheduler_task(task_id: str):
    """恢复定时任务"""
    if app_state.scheduler_manager is None:
        return {"status": "failed", "message": "调度器未初始化"}
    try:
        success = await app_state.scheduler_manager.resume_task(task_id)
        if success:
            return {"status": "success"}
        return {"status": "failed", "message": "任务不存在"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@app.get("/api/scheduler/executions")
async def get_scheduler_executions(limit: int = 50):
    """获取执行历史"""
    if app_state.scheduler_manager is None:
        return {"status": "failed", "message": "调度器未初始化"}
    try:
        executions = await app_state.scheduler_manager.get_executions(limit)
        return {
            "status": "success",
            "executions": [exec.model_dump() for exec in executions],
        }
    except Exception as e:
        return {"status": "failed", "message": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=55666)
