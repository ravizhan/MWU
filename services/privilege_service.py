"""
权限提权服务 — Controller 声明 permission_required 时的管理员重启流程。

``request_elevation`` 只派生一个脱离当前进程的启动器后立即返回；启动器等待
旧实例进程退出，再以系统标准授权方式启动替换实例：

- Windows: PowerShell ``Wait-Process`` 等待旧 pid 退出，``Start-Process -Verb
  RunAs`` 触发系统 UAC。
- Linux:   POSIX shell 等待旧 pid 退出后 ``exec pkexec``。
- macOS:   POSIX shell 等待旧 pid 退出后 ``exec osascript``（系统授权对话框）。

安全边界：替换命令只由服务端当前可执行路径、固定启动参数和 app 根 CWD
构成，不接收客户端输入。Windows 脚本整体经 ``-EncodedCommand`` 传递，路径
只出现在单引号字面量中；POSIX 命令逐参数经 ``shlex.quote`` 引用，不拼接客户
端字符串。``request_elevation`` 的结果只表示启动器是否成功提交，不代表授权
结果：授权被拒绝或失败都没有恢复路径，也不会跨进程自动重放任务 payload。
"""

from __future__ import annotations

import base64
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from services import runtime_info

ElevationStatus = Literal["success", "failed"]
# 启动器等待旧实例退出的轮询间隔（POSIX shell 等待循环）。
_LAUNCHER_POLL_INTERVAL = 0.2


@dataclass(frozen=True)
class ElevationResult:
    """一次提权请求的结果。

    ``success`` 只表示启动器已成功提交。授权由启动器在旧实例退出后向系统
    请求，被拒绝或失败都不会恢复旧实例。
    """

    status: ElevationStatus
    message: str


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
    if runtime_info.is_packaged_build():
        return [sys.executable]
    return [sys.executable, str(app_root / "main.py")]


def _powershell_literal(value: str) -> str:
    """把任意字符串编码为 PowerShell 单引号字面量（内部单引号翻倍）。"""
    return "'" + value.replace("'", "''") + "'"


def _powershell_executable() -> str:
    """系统 Windows PowerShell 的绝对路径，不经过 PATH/当前目录解析。"""
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    return str(
        Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )


def _windows_launcher_script(pid: int, command: list[str], cwd: Path) -> str:
    """等待旧 pid 退出后再以 UAC 启动替换实例的 PowerShell 脚本。

    参数用 ``subprocess.list2cmdline`` 引用（Windows 命令行规则），路径用
    PowerShell 单引号字面量承载，因此不会提前结束字面量或触发变量/子表达式
    展开。
    """
    parts = ["Start-Process", "-FilePath", _powershell_literal(command[0])]
    arguments = subprocess.list2cmdline(command[1:]) if len(command) > 1 else ""
    if arguments:
        parts += ["-ArgumentList", _powershell_literal(arguments)]
    parts += ["-WorkingDirectory", _powershell_literal(str(cwd)), "-Verb", "RunAs"]
    return f"Wait-Process -Id {pid} -ErrorAction SilentlyContinue; " + " ".join(parts)


def _posix_launcher_script(pid: int, argv: list[str]) -> str:
    """等待旧 pid 退出后 exec 授权启动命令的 POSIX shell 脚本。"""
    wait = f"while kill -0 {pid} 2>/dev/null; do sleep {_LAUNCHER_POLL_INTERVAL}; done"
    return f"{wait}; exec {' '.join(shlex.quote(arg) for arg in argv)}"


def _applescript_argv(command: list[str]) -> list[str]:
    """macOS 系统授权对话框启动 argv（AppleScript 内再走 POSIX shell 引用）。"""
    shell_command = " ".join(shlex.quote(arg) for arg in command)
    applescript_command = shell_command.replace("\\", "\\\\").replace('"', '\\"')
    return [
        "osascript",
        "-e",
        f'do shell script "{applescript_command}" with administrator privileges',
    ]


def _launcher_argv(pid: int, command: list[str], cwd: Path, platform: str) -> list[str]:
    """构造等待旧 pid 退出后再请求系统授权的启动器 argv（服务端构造）。"""
    if platform == "win32":
        script = _windows_launcher_script(pid, command, cwd)
        return [
            _powershell_executable(),
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
        ]
    if platform == "linux":
        return ["/bin/sh", "-c", _posix_launcher_script(pid, ["pkexec", *command])]
    if platform == "darwin":
        return [
            "/bin/sh",
            "-c",
            _posix_launcher_script(pid, _applescript_argv(command)),
        ]
    raise ValueError(f"当前平台不支持管理员重启: {platform}")


def request_elevation(app_root: Path) -> ElevationResult:
    """提交管理员重启启动器；只报告提交结果，不等待授权。

    启动器脱离当前进程运行，只等待当前 pid 退出后再请求系统授权，因此旧实例
    从不为授权结果阻塞。无论返回什么状态，调用方都应继续退出旧实例。
    """
    command = build_restart_command(app_root)
    try:
        argv = _launcher_argv(os.getpid(), command, app_root, sys.platform)
    except ValueError as exc:
        return ElevationResult("failed", str(exc))
    try:
        if sys.platform == "win32":
            # PowerShell 在 DETACHED_PROCESS 下可能直接退出；使用无窗口独立进程组。
            subprocess.Popen(
                argv,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # start_new_session：脱离当前会话；cwd 固定为 app 根。
            subprocess.Popen(
                argv,
                cwd=str(app_root),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError as exc:
        return ElevationResult("failed", f"无法启动管理员授权程序: {exc}")
    return ElevationResult("success", "已提交管理员重启，旧实例退出后请求系统授权")


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
