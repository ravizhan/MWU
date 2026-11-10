"""应用更新与进程退出。"""

import asyncio
import hashlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter

from backend.core import json_utils as json
from backend.core.install_manifest import read_install_manifest
from backend.models.settings import SettingsModel
from backend.runtime import APP_ROOT_DIR, app_state, interface
from backend.services.update_service import check_update, download_file

router = APIRouter()


@router.get("/api/update/check")
def check_update_route():
    try:
        plan = check_update(
            current_version=interface.version or "",
            mirrorchyan_rid=interface.mirrorchyan_rid,
            github_url=interface.github,
            settings=app_state.settings or SettingsModel(),
            manifest=read_install_manifest(APP_ROOT_DIR),
            log=app_state.send_log,
        )
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"检查更新失败: {msg}")
        return {"status": "failed", "message": msg}
    app_state.update_info = plan
    return {"status": "success", "update_info": plan.model_dump()}


@router.get("/api/update")
async def perform_update():
    try:
        plan = app_state.update_info
        if plan is None or not plan.download_url:
            msg = "暂无可用更新信息"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}

        update_package_path = APP_ROOT_DIR / plan.file_name
        await asyncio.to_thread(update_package_path.unlink, missing_ok=True)
        app_state.update_status = {
            "status": "downloading",
            "message": "正在下载更新包...",
        }
        # 更新真正开始：置位准入标志，阻塞 /api/start 与调度准入，防止更新期间启动任务
        app_state.update_in_progress = True

        try:
            proxy = (
                None
                if plan.download_source == "mirrorchyan"
                else (app_state.settings or SettingsModel()).update.proxy.strip()
                or None
            )
            await download_file(plan.download_url, update_package_path, proxy)
            if plan.file_hash:
                file_bytes = await asyncio.to_thread(update_package_path.read_bytes)
                if hashlib.sha256(file_bytes).hexdigest() != plan.file_hash:
                    raise ValueError("文件哈希校验失败，下载的文件可能已损坏。")
        except Exception as e:
            msg = f"下载失败: {e}"
            app_state.send_log(msg)
            app_state.update_status = {"status": "failed", "message": msg}
            app_state.update_in_progress = False
            return {"status": "failed", "message": str(e)}

        threading.Thread(
            target=_run_updater_loop,
            args=(update_package_path, plan.package_type),
            daemon=True,
        ).start()
        return {"status": "success", "message": "正在后台更新程序..."}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"更新失败: {msg}")
        app_state.update_status = {"status": "failed", "message": msg}
        app_state.update_in_progress = False
        return {"status": "failed", "message": msg}


def _run_updater_loop(package_path: Path, package_type: str) -> None:
    app_state.update_status = {
        "status": "updating",
        "message": "正在运行更新器...",
    }
    # 更新器循环仅在终态分支（启动失败 / 异常退出 / 正常退出）通过 break 退出；
    # 自更新（returncode 10）用 continue 继续，不触发 finally。
    try:
        while True:
            cmd = [
                str(APP_ROOT_DIR / "mwu-updater"),
                "-archive",
                str(package_path),
                "-type",
                package_type,
                "-webhook",
                "http://127.0.0.1:5566/api/system/shutdown",
                "-restart-cmd",
                sys.executable,
            ]

            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=APP_ROOT_DIR,
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
                app_state.update_status = {"status": "failed", "message": msg}
                break

            process.wait()

            if process.returncode == 10:
                app_state.update_status = {
                    "status": "updating",
                    "message": "更新器自更新完成，正在重启更新器...",
                }
                continue
            if process.returncode != 0:
                msg = f"更新器异常退出: {process.returncode}，请查看updater.log"
                app_state.send_log(msg)
                app_state.update_status = {"status": "failed", "message": msg}
            break
    finally:
        # 更新器线程终态：无论失败还是正常退出，均放行任务准入。
        # 成功自更新时进程被 webhook 杀除，此 finally 不执行（进程随 flag 消亡），符合预期。
        app_state.update_in_progress = False


@router.get("/api/update/status")
def get_update_status():
    if app_state.update_status is None:
        return {"status": "idle", "message": "没有正在进行的更新"}
    return app_state.update_status


@router.get("/api/system/shutdown")
def system_shutdown():
    def _shutdown():
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_shutdown, daemon=True).start()
    return {"status": "success", "message": "Shutting down"}
