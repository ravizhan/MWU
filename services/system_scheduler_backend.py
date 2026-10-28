"""系统级计划任务 OS 后端：Windows schtasks / macOS launchctl / Linux crontab。

统一走 CLI，不引入任何平台专用 Python 依赖（禁止 pywin32）。
"""

import csv
import io
import logging
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from services.native_cron import (
    NativeCron,
    to_crontab_line,
    to_launchd_calendar,
    to_schtasks_args,
)

logger = logging.getLogger(__name__)

TASK_ID_RE = re.compile(r"^[a-f0-9-]{36}$")


def validate_task_id(task_id: str) -> str:
    """校验任务 ID 为 UUID 形式，防止命令注入"""
    if not TASK_ID_RE.fullmatch(task_id):
        raise ValueError(f"非法任务 ID: {task_id!r}")
    return task_id


class CommandError(RuntimeError):
    """外部命令失败；携带 stderr/stdout，供调用方按内容区分可接受失败。"""

    def __init__(self, message: str, stderr: str = "", stdout: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr
        self.stdout = stdout


@dataclass(frozen=True)
class NativeTaskSpec:
    """OS 原生计划任务描述"""

    task_id: str
    task_name: str
    exe_path: str
    cli_args: list[str]
    cron: NativeCron
    working_dir: str


class SystemSchedulerBackend(ABC):
    """系统级计划任务后端抽象基类"""

    supports_native: bool = True

    @abstractmethod
    def register(self, spec: NativeTaskSpec) -> None:
        """注册（或更新）一个系统计划任务"""

    @abstractmethod
    def unregister(self, task_id: str) -> None:
        """删除一个系统计划任务"""

    @abstractmethod
    def list_registered_task_ids(self) -> set[str]:
        """列出当前已注册的本应用任务 ID"""


def _run(args: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """执行外部命令；失败统一抛 CommandError（携带 stderr/stdout）"""
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            check=check,
            **kwargs,
        )
    except subprocess.CalledProcessError as exc:
        raise CommandError(
            f"命令执行失败: {' '.join(args)}；{(exc.stderr or exc.stdout or '').strip()}",
            stderr=exc.stderr or "",
            stdout=exc.stdout or "",
        ) from exc
    except OSError as exc:
        raise CommandError(
            f"命令启动失败: {' '.join(args)}；{exc}",
            stderr="",
            stdout="",
        ) from exc


_SCHTASKS_NO_TASK_MARKERS = (
    "no scheduled tasks",
    "no tasks are scheduled",
    "没有计划任务",
    "找不到计划任务",
)


def _is_schtasks_no_tasks(stderr: str) -> bool:
    """schtasks 报告“无任何计划任务”的判断（不同语言环境）。"""
    if not stderr:
        return False
    lowered = stderr.lower()
    return any(marker in lowered for marker in _SCHTASKS_NO_TASK_MARKERS)


def _is_schtasks_task_not_found(stderr: str) -> bool:
    """schtasks 报告“任务不存在”的判断（不同语言环境）。"""
    if not stderr:
        return False
    lowered = stderr.lower()
    return (
        "cannot find" in lowered
        or "not found" in lowered
        or "找不到" in stderr
        or "没有找到" in stderr
    )


class WindowsBackend(SystemSchedulerBackend):
    """Windows 系统计划任务后端（schtasks.exe CLI，禁止 pywin32）"""

    def register(self, spec: NativeTaskSpec) -> None:
        task_id = validate_task_id(spec.task_id)
        command = subprocess.list2cmdline([spec.exe_path, *spec.cli_args])
        _run(
            [
                "schtasks",
                "/Create",
                "/F",
                "/TN",
                f"MWU\\{task_id}",
                "/TR",
                command,
                *to_schtasks_args(spec.cron),
            ]
        )
        logger.info("已注册 Windows 计划任务 MWU\\%s", task_id)

    def unregister(self, task_id: str) -> None:
        task_id = validate_task_id(task_id)
        try:
            _run(["schtasks", "/Delete", "/F", "/TN", f"MWU\\{task_id}"])
        except CommandError as exc:
            # 任务本就不存在（正常删除或并发竞态）视为删除成功
            if _is_schtasks_task_not_found(exc.stderr):
                logger.info("Windows 计划任务 MWU\\%s 已不存在，视为删除成功", task_id)
                return
            raise
        logger.info("已删除 Windows 计划任务 MWU\\%s", task_id)

    def list_registered_task_ids(self) -> set[str]:
        try:
            result = _run(["schtasks", "/Query", "/FO", "CSV", "/NH"])
        except CommandError as exc:
            # 无任何计划任务时 schtasks 非零退出：视为空集合；其它（权限/瞬时）
            # 错误必须上抛，避免把未知状态当空而误清孤儿
            if _is_schtasks_no_tasks(exc.stderr):
                return set()
            logger.warning("查询 Windows 计划任务失败: %s", exc)
            raise
        task_ids: set[str] = set()
        for row in csv.reader(io.StringIO(result.stdout)):
            if not row:
                continue
            match = re.search(r"MWU\\([a-f0-9-]{36})", row[0])
            if match:
                task_ids.add(match.group(1))
        return task_ids


class MacOSBackend(SystemSchedulerBackend):
    """macOS 系统计划任务后端（launchctl + LaunchAgents plist）"""

    _PLIST_DIR = Path.home() / "Library" / "LaunchAgents"
    _PLIST_PREFIX = "com.mwu.scheduler."

    def _plist_path(self, task_id: str) -> Path:
        return self._PLIST_DIR / f"{self._PLIST_PREFIX}{task_id}.plist"

    def _bootout(self, uid: int, label: str) -> None:
        """bootout 已加载服务；未加载（'not loaded'/'No such process'）视为成功。"""
        result = _run(["launchctl", "bootout", f"gui/{uid}/{label}"], check=False)
        if result.returncode == 0:
            return
        detail = (result.stderr or "").strip().lower()
        not_loaded = (
            not detail
            or "no such process" in detail
            or "not loaded" in detail
            or "not found" in detail
            or "没有该进程" in detail
            or "未加载" in detail
        )
        if not_loaded:
            return
        raise CommandError(
            f"launchctl bootout 失败: gui/{uid}/{label}；{result.stderr or ''}",
            stderr=result.stderr or "",
            stdout=result.stdout or "",
        )

    def register(self, spec: NativeTaskSpec) -> None:
        task_id = validate_task_id(spec.task_id)
        label = f"com.mwu.scheduler.{task_id}"
        plist_path = self._plist_path(task_id)
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": label,
            "ProgramArguments": [spec.exe_path, *spec.cli_args],
            "StartCalendarInterval": to_launchd_calendar(spec.cron),
            "WorkingDirectory": spec.working_dir,
            "RunAtLoad": False,
        }
        with plist_path.open("wb") as f:
            plistlib.dump(payload, f)
        uid = os.getuid()
        # 覆盖更新时旧任务可能仍被加载：先 bootout（不存在则忽略错误），再 bootstrap
        self._bootout(uid, label)
        _run(["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)])
        logger.info("已注册 macOS 计划任务 %s", plist_path)

    def unregister(self, task_id: str) -> None:
        task_id = validate_task_id(task_id)
        plist_path = self._plist_path(task_id)
        self._bootout(os.getuid(), f"com.mwu.scheduler.{task_id}")
        plist_path.unlink(missing_ok=True)
        logger.info("已删除 macOS 计划任务 %s", plist_path)

    def list_registered_task_ids(self) -> set[str]:
        task_ids: set[str] = set()
        plist_dir = self._PLIST_DIR
        if not plist_dir.is_dir():
            return task_ids
        try:
            for plist_path in plist_dir.glob(f"{self._PLIST_PREFIX}*.plist"):
                match = re.search(
                    r"com\.mwu\.scheduler\.([a-f0-9-]{36})\.plist", plist_path.name
                )
                if match:
                    task_ids.add(match.group(1))
        except OSError as exc:
            # 未知错误必须上抛，避免把未知状态当空而误清孤儿
            raise RuntimeError(f"查询 macOS 计划任务失败: {exc}") from exc
        return task_ids


class LinuxBackend(SystemSchedulerBackend):
    """Linux 系统计划任务后端（crontab）"""

    def _read_crontab(self) -> str:
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                errors="replace",
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            # “no crontab for <user>” 是正常状态（尚无 crontab），视为空内容
            if "no crontab for" in stderr.lower():
                return ""
            # 其它（权限/瞬时）错误必须上抛，避免把用户整个 crontab 覆写成应用内容
            raise RuntimeError(
                f"读取 crontab 失败: {' '.join(exc.cmd)}；{stderr}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"读取 crontab 失败: {exc}") from exc
        return result.stdout

    def _write_crontab(self, content: str) -> None:
        _run(["crontab", "-"], input=content)

    def _filtered_lines(self, task_id: str) -> list[str]:
        marker = f"# MWU:{task_id}"
        return [
            line for line in self._read_crontab().splitlines() if marker not in line
        ]

    def register(self, spec: NativeTaskSpec) -> None:
        task_id = validate_task_id(spec.task_id)
        lines = self._filtered_lines(task_id)
        cmd = " ".join(shlex.quote(t) for t in [spec.exe_path, *spec.cli_args])
        lines.append(f"{to_crontab_line(spec.cron)} {cmd} # MWU:{task_id}")
        self._write_crontab("\n".join(lines) + "\n")
        logger.info("已注册 Linux 计划任务 %s", task_id)

    def unregister(self, task_id: str) -> None:
        task_id = validate_task_id(task_id)
        self._write_crontab("\n".join(self._filtered_lines(task_id)) + "\n")
        logger.info("已删除 Linux 计划任务 %s", task_id)

    def list_registered_task_ids(self) -> set[str]:
        content = self._read_crontab()
        return {
            match.group(1) for match in re.finditer(r"# MWU:([a-f0-9-]{36})", content)
        }


class NullBackend(SystemSchedulerBackend):
    """空后端：不支持系统级调度的平台，注册/删除均为 no-op"""

    supports_native: bool = False

    def register(self, spec: NativeTaskSpec) -> None:
        logger.info(
            "系统级调度后端不可用，跳过注册任务 %s 的 OS 计划任务", spec.task_id
        )

    def unregister(self, task_id: str) -> None:
        logger.info("系统级调度后端不可用，跳过删除任务 %s 的 OS 计划任务", task_id)

    def list_registered_task_ids(self) -> set[str]:
        return set()


def get_backend() -> SystemSchedulerBackend:
    """按当前平台返回系统计划任务后端；不支持或 CLI 缺失时返回 NullBackend，绝不抛错"""
    if sys.platform == "win32":
        if shutil.which("schtasks"):
            return WindowsBackend()
    elif sys.platform == "darwin":
        if shutil.which("launchctl"):
            return MacOSBackend()
    elif sys.platform == "linux":
        if shutil.which("crontab"):
            return LinuxBackend()
    return NullBackend()


def build_native_command(app_root: Path, task_id: str) -> tuple[str, list[str]]:
    """构造 OS 原生任务要执行的命令（可执行文件路径 + 参数列表）"""
    validate_task_id(task_id)
    if getattr(sys, "frozen", False):
        return sys.executable, ["--scheduled-task", task_id]
    return sys.executable, [str(app_root / "main.py"), "--scheduled-task", task_id]
