"""日志打包：MaaFramework 日志、MWU 运行日志、updater 日志与 debug 图片写入 zip。

文本日志按尾部截断并抹掉 password 选项的明文（pipeline override 会把它写进 maafw.log）。
明文来源除当前保存的配置外，还有每次运行实际用过的值（加密记录在 config/log_secrets.json），
这样改过、删掉或未保存就运行过的密码仍会被抹掉。
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
# 运行被取消后 to_thread 里的写入仍会继续，下一次运行可能同时合并记录；
# 串行化整个读改写，避免旧写入覆盖新值。
_SECRETS_LOCK = threading.Lock()


def remembered_secrets(path: Path = SECRETS_FILE) -> list[str]:
    """读取运行用过的 password 明文；无法解密的值（密钥丢失）被 reveal 清空后丢弃。

    记录只辅助脱敏：文件损坏时记录警告并按空记录处理，不阻断导出和运行，下次记录时重写。
    """
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            sealed = json.load(f)["secrets"]
    except (ValueError, KeyError, TypeError):
        sealed = None
    if not isinstance(sealed, list):
        logger.warning("%s 无法解析，已忽略其中的密码记录", path.name)
        return []
    return [value for value in secret_store.reveal(sealed) if value]


def remember_secrets(values: Iterable[str], path: Path = SECRETS_FILE) -> None:
    """把本次运行用到的 password 明文并入记录，加密后原子落盘；没有新值时不写。"""
    new = set(values)
    if not new:
        return
    with _SECRETS_LOCK:
        known = set(remembered_secrets(path))
        if new <= known:
            return
        secrets = [secret_store.seal_value(value) for value in sorted(known | new)]
        atomic_write_json(path, {"secrets": secrets})


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


def build_bundle(
    app_root: Path,
    history: Iterable[RealtimeEvent],
    secrets: Iterable[str],
) -> Path:
    """写入临时 zip 并返回路径，由调用方在发送后删除；失败时不留临时文件。"""
    fd, name = tempfile.mkstemp(prefix="mwu-logs-", suffix=".zip")
    os.close(fd)
    dest = Path(name)
    try:
        _write_bundle(dest, app_root, history, secrets)
    except BaseException:
        dest.unlink()
        raise
    return dest


def _write_bundle(
    dest: Path,
    app_root: Path,
    history: Iterable[RealtimeEvent],
    secrets: Iterable[str],
) -> None:
    patterns = _secret_patterns(secrets)
    debug_dir = app_root / "debug"
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        mwu_log = "".join(f"{event.time} {event.message}\n" for event in history)
        bundle.writestr("mwu.log", _redact(mwu_log.encode("utf-8"), patterns))

        text_logs = sorted(debug_dir.glob("*.log")) if debug_dir.is_dir() else []
        updater_log = app_root / "updater.log"
        if updater_log.is_file():
            text_logs.append(updater_log)
        for path in text_logs:
            arcname = path.relative_to(app_root).as_posix()
            bundle.writestr(arcname, _redact(_read_tail(path), patterns))

        remaining = IMAGE_BUDGET_BYTES
        for path in _newest_images(debug_dir):
            size = path.stat().st_size
            if size > remaining:
                continue
            remaining -= size
            bundle.write(
                path,
                path.relative_to(app_root).as_posix(),
                compress_type=zipfile.ZIP_STORED,
            )
