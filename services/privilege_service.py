"""
权限提权服务 — Controller 声明 permission_required 时的管理员重启流程。

平台策略：
- Windows: 系统 UAC runas（ShellExecuteW "runas"）
- Linux:   pkexec
- macOS:   系统授权对话框启动原命令

安全边界：重启命令只由服务端当前可执行路径、固定启动参数和 app 根 CWD
构成，不接收客户端任意 shell 字符串。重启前停止运行、取消 pending modal、
完成已授权的有限遥测收尾；不跨进程自动重放任务 payload。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def is_elevated() -> bool:
    """当前进程是否已具备管理员/root 权限。"""
    if sys.platform == "win32":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0 if hasattr(os, "geteuid") else False


def build_restart_command(app_root: Path) -> list[str]:
    """构造当前程序的重启命令（服务端控制，不含客户端输入）。

    Nuitka 打包：直接运行当前可执行文件；
    源码运行：以当前解释器运行 main.py。
    """
    if (
        getattr(sys, "frozen", False)
        or "__compiled__" in globals()
        or hasattr(sys, "_MEIPASS")
    ):
        return [sys.executable]
    return [sys.executable, str(app_root / "main.py")]


def request_elevation(app_root: Path) -> bool:
    """请求以管理员权限重启当前程序。

    返回 True 表示提权请求已提交（新进程已启动，调用方应退出当前进程）；
    False 表示用户拒绝或系统拒绝，本次准备失败。

    提权后继续监听 0.0.0.0:5566（用户明确选择保留局域网访问）。
    """
    args = build_restart_command(app_root)

    if sys.platform == "win32":
        # ShellExecuteW "runas"：标准 UAC 提示，不构造 shell 字符串
        import ctypes

        params = subprocess.list2cmdline(args[1:]) if len(args) > 1 else ""
        executable = args[0]
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            str(app_root),
            1,  # SW_SHOWNORMAL
        )
        # ShellExecuteW 返回值 >32 表示成功
        return int(ret) > 32

    if sys.platform == "linux":
        try:
            proc = subprocess.Popen(
                ["pkexec", *args],
                cwd=str(app_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return proc.poll() is None or proc.returncode == 0
        except OSError:
            return False

    if sys.platform == "darwin":
        # osascript 授权对话框启动原命令；参数固定，不接受客户端输入
        try:
            quoted = " ".join(
                arg if all(c not in arg for c in " \"'\t\\") else repr(arg)
                for arg in args
            )
            script = f'do shell script "{quoted}" with administrator privileges'
            proc = subprocess.Popen(
                ["osascript", "-e", script],
                cwd=str(app_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return proc.poll() is None or proc.returncode == 0
        except OSError:
            return False

    return False


def controller_requires_privilege(controller) -> bool:
    """PI Controller 是否声明需要管理员权限。"""
    return bool(getattr(controller, "permission_required", False))


def check_permission(controller) -> str | None:
    """执行准备程序前的权限检查。

    返回 None 表示权限足够；返回 "permission_required" 表示不足。
    """
    if not controller_requires_privilege(controller):
        return None
    if is_elevated():
        return None
    return "permission_required"
