"""日志打包：MaaFramework 日志、MWU 运行日志、updater 日志与 debug 图片写入 zip。

文本日志按尾部截断并抹掉 password 选项的明文（pipeline override 会把它写进 maafw.log）。
明文来源除当前保存的配置外，还有每次运行实际用过的值（加密记录在 config/log_secrets.json），
这样改过、删掉或未保存就运行过的密码仍会被抹掉。
运行在密码进入日志前先写记录，因此导出先快照文本日志、再读记录，快照里的密码都已在记录中。
记录损坏、无法解密或写入失败时记录不再完整，日志里可能有无法识别的密码：
这一状态持久化在记录里，导出一直拒绝，直到用户清理日志并删除记录。
截断点对齐到下一行开头：password 输入是单行值，整行起截就不会留下跨截断点的明文残片。
图片按修改时间从新到旧收录，放不进剩余总量的跳过，继续尝试更旧的小图。
"""

import logging
import os
import tempfile
import threading
import zipfile
from collections.abc import Iterable
from pathlib import Path

from backend.core import json_utils as json
from backend.core import secret_store
from backend.core.paths import resolve_app_root
from backend.core.settings_io import atomic_write_json
from backend.models.api import RealtimeEvent

logger = logging.getLogger(__name__)

LOG_TAIL_BYTES = 32 * 1024 * 1024
IMAGE_BUDGET_BYTES = 64 * 1024 * 1024
SECRETS_FILE = resolve_app_root() / "config" / "log_secrets.json"
_IMAGE_DIRS = ("on_error", "vision")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_MASK = b"******"
# 运行被取消后 to_thread 里的写入仍会继续，下一次运行可能同时合并记录；串行化整个读改写，
# 避免旧写入覆盖新值。导出的读取也要持锁：Windows 上打开中的文件会让 replace 失败。
_SECRETS_LOCK = threading.Lock()
# 写入失败且尚未把不完整状态落进记录；下一次成功写入时持久化后清除。
_write_failed = False


class SecretRecordIncomplete(Exception):
    """密码记录不完整，日志中可能有无法抹掉的密码。"""

    def __init__(self) -> None:
        super().__init__(
            "密码记录不完整（config/log_secrets.json 损坏、无法解密或写入失败），"
            "日志中可能有无法抹掉的密码，已拒绝导出。"
            "请退出 MWU，删除 debug 目录中的日志和 config/log_secrets.json 后重新启动"
        )


def _read_record(path: Path) -> tuple[set[str], bool]:
    """返回（明文集合, 是否不完整）；文件损坏或有值无法解密（密钥丢失）都算不完整。"""
    if not path.exists():
        return set(), False
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        sealed, incomplete = data["secrets"], data["incomplete"]
    except (ValueError, KeyError, TypeError):
        sealed, incomplete = None, None
    if not isinstance(sealed, list) or not isinstance(incomplete, bool):
        logger.warning("%s 无法解析，密码记录已不完整", path.name)
        return set(), True
    revealed = secret_store.reveal(sealed)
    secrets = {value for value in revealed if value}
    return secrets, incomplete or len(secrets) < len(revealed)


def remembered_secrets(path: Path = SECRETS_FILE) -> list[str]:
    """读取运行用过的 password 明文；记录不完整时抛出 SecretRecordIncomplete。"""
    with _SECRETS_LOCK:
        secrets, incomplete = _read_record(path)
        if incomplete or _write_failed:
            raise SecretRecordIncomplete
    return sorted(secrets)


def remember_secrets(values: Iterable[str], path: Path = SECRETS_FILE) -> bool:
    """把本次运行用到的 password 明文并入记录，加密后原子落盘；无需写入时不写。

    读写失败只返回 False 并记住不完整状态，不阻断运行；不完整状态在下次写入时落盘。
    """
    global _write_failed
    new = set(values)
    with _SECRETS_LOCK:
        try:
            known, incomplete = _read_record(path)
            if new <= known and not _write_failed:
                return True
            # 记录里只有明文，不能用按前缀跳过的 seal_value：以加密前缀开头的密码会被原样落盘
            secrets = [
                secret_store.encrypt_value(value) for value in sorted(known | new)
            ]
            atomic_write_json(
                path,
                {"secrets": secrets, "incomplete": incomplete or _write_failed},
            )
        except OSError as exc:
            logger.warning("写入 %s 失败: %s", path.name, exc)
            _write_failed = True
            return False
        _write_failed = False
        return True


def _secret_patterns(values: Iterable[str]) -> list[bytes]:
    """明文及其 JSON 转义形式；长的优先替换，避免短值先命中长值的片段。"""
    patterns: set[bytes] = set()
    for value in values:
        patterns.add(value.encode("utf-8"))
        patterns.add(json.dumps(value, ensure_ascii=False)[1:-1].encode("utf-8"))
        patterns.add(json.dumps(value)[1:-1].encode("utf-8"))
    return sorted(patterns, key=len, reverse=True)


def _redact(data: bytes, patterns: list[bytes]) -> bytes:
    for pattern in patterns:
        data = data.replace(pattern, _MASK)
    return data


def _read_tail(path: Path) -> bytes:
    with path.open("rb") as f:
        size = f.seek(0, os.SEEK_END)
        start = size - LOG_TAIL_BYTES
        if start <= 0:
            f.seek(0)
            return f.read()
        # 多读截断点前一字节：截断点恰好在行首时保留该行
        f.seek(start - 1)
        data = f.read()
    return data[data.find(b"\n") + 1 :] if b"\n" in data else b""


def _newest_images(debug_dir: Path) -> list[Path]:
    images = [
        path
        for name in _IMAGE_DIRS
        if (debug_dir / name).is_dir()
        for path in (debug_dir / name).rglob("*")
        if path.suffix.lower() in _IMAGE_SUFFIXES and path.is_file()
    ]
    return sorted(images, key=lambda path: path.stat().st_mtime, reverse=True)


def snapshot_text_logs(
    app_root: Path, history: Iterable[RealtimeEvent]
) -> list[tuple[str, bytes]]:
    """读取待导出文本日志（zip 内路径, 尾部内容）；须在收集密码之前调用。"""
    mwu_log = "".join(f"{event.time} {event.message}\n" for event in history)
    snapshot = [("mwu.log", mwu_log.encode("utf-8"))]
    debug_dir = app_root / "debug"
    text_logs = sorted(debug_dir.glob("*.log")) if debug_dir.is_dir() else []
    updater_log = app_root / "updater.log"
    if updater_log.is_file():
        text_logs.append(updater_log)
    snapshot.extend(
        (path.relative_to(app_root).as_posix(), _read_tail(path)) for path in text_logs
    )
    return snapshot


def build_bundle(
    app_root: Path,
    text_logs: list[tuple[str, bytes]],
    secrets: Iterable[str],
) -> Path:
    """写入临时 zip 并返回路径，由调用方在发送后删除；失败时不留临时文件。"""
    fd, name = tempfile.mkstemp(prefix="mwu-logs-", suffix=".zip")
    os.close(fd)
    dest = Path(name)
    try:
        _write_bundle(dest, app_root, text_logs, secrets)
    except BaseException:
        dest.unlink()
        raise
    return dest


def _write_bundle(
    dest: Path,
    app_root: Path,
    text_logs: list[tuple[str, bytes]],
    secrets: Iterable[str],
) -> None:
    patterns = _secret_patterns(secrets)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for arcname, data in text_logs:
            bundle.writestr(arcname, _redact(data, patterns))

        remaining = IMAGE_BUDGET_BYTES
        for path in _newest_images(app_root / "debug"):
            size = path.stat().st_size
            if size > remaining:
                continue
            remaining -= size
            bundle.write(
                path,
                path.relative_to(app_root).as_posix(),
                compress_type=zipfile.ZIP_STORED,
            )
