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
from backend.models.settings import SettingsModel
from backend.runtime import (
    app_state,
    interface,
)
from backend.services.update_service import (
    check_github_update,
    check_mirrorchyan_update,
    download_file,
    get_platform_info,
)

router = APIRouter()


@router.get("/api/update/check")
def check_update():
    try:
        settings = app_state.settings or SettingsModel()
        current_version = interface.version or ""
        mirrorchyan_rid = getattr(interface, "mirrorchyan_rid", None)
        github_url = interface.github or ""
        cdk = settings.update.mirrorchyanCdk
        mirrorchyan_error: str | None = None

        if mirrorchyan_rid:
            try:
                mc_data = check_mirrorchyan_update(
                    mirrorchyan_rid, current_version, cdk, settings
                )
            except RuntimeError as exc:
                # 配置了 MirrorChyan 时仍回退 GitHub，但失败原因必须可见
                app_state.send_log(f"MirrorChyan 更新检查失败，回退 GitHub: {exc}")
                mirrorchyan_error = str(exc)
                mc_data = None
            if mc_data is not None:
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
                    except Exception as exc:
                        # 保留 mirrorchyan 版本信息，但让「拿不到 GitHub 下载链接」可见：
                        # 后续下载将不带代理/CDK。
                        app_state.send_log(f"获取 GitHub 下载链接失败: {exc}")

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

        msg = mirrorchyan_error or "未配置更新源"
        app_state.send_log(msg)
        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"检查更新失败: {msg}")
        return {"status": "failed", "message": msg}


@router.get("/api/update")
async def perform_update():
    try:
        if app_state.update_info is None:
            msg = "暂无可用更新信息"
            app_state.send_log(msg)
            return {"status": "failed", "message": msg}

        update_package_path = Path(app_state.update_info["file_name"])
        download_url = app_state.update_info["download_url"]
        download_source = app_state.update_info.get("download_source", "github")
        await asyncio.to_thread(update_package_path.unlink, missing_ok=True)
        app_state.update_status = {
            "status": "downloading",
            "message": "正在下载更新包...",
        }
        # 更新真正开始：置位准入标志，阻塞 /api/start 与调度准入，防止更新期间启动任务
        app_state.update_in_progress = True

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
                file_bytes = await asyncio.to_thread(update_package_path.read_bytes)
                if hashlib.sha256(file_bytes).hexdigest() != file_hash:
                    raise ValueError("文件哈希校验失败，下载的文件可能已损坏。")
        except Exception as e:
            msg = f"下载失败: {e}"
            app_state.send_log(msg)
            app_state.update_status = {"status": "failed", "message": msg}
            app_state.update_in_progress = False
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
                        str(update_package_path.absolute()),
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
                app_state.update_in_progress = False

        threading.Thread(target=run_updater_loop, daemon=True).start()
        return {"status": "success", "message": "正在后台更新程序..."}
    except Exception as e:
        msg = str(e)
        app_state.send_log(f"更新失败: {msg}")
        app_state.update_status = {"status": "failed", "message": msg}
        app_state.update_in_progress = False
        return {"status": "failed", "message": msg}


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
