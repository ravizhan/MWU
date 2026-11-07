"""日志打包：MaaFramework 日志、MWU 运行日志、updater 日志与 debug 图片写入 zip。

文本日志按尾部截断并抹掉 password 选项的明文（pipeline override 会把它写进 maafw.log）；
图片按修改时间从新到旧收录，超出总量上限的旧图片不再收录。
"""

import os
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path

from backend.core import json_utils as json
from backend.models.api import RealtimeEvent

LOG_TAIL_BYTES = 32 * 1024 * 1024
IMAGE_BUDGET_BYTES = 64 * 1024 * 1024
_IMAGE_DIRS = ("on_error", "vision")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_MASK = b"******"


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
        f.seek(max(0, size - LOG_TAIL_BYTES))
        return f.read()


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
                break
            remaining -= size
            bundle.write(
                path,
                path.relative_to(app_root).as_posix(),
                compress_type=zipfile.ZIP_STORED,
            )
