"""日志打包：MaaFramework 日志、MWU 运行日志、updater 日志与 debug 图片写入 zip。

文本日志按尾部截断并抹掉 password 选项的明文（pipeline override 会把它写进 maafw.log）。
/明文由调用方提供：当前保存的配置加上本进程内运行实际用过的值。
截断点对齐到下一行开头：password 输入是单行值，整行起截就不会留下跨截断点的明文残片。
图片按修改时间从新到旧收录，放不进剩余总量的跳过，继续尝试更旧的小图。
"""

import os
import stat
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
        start = size - LOG_TAIL_BYTES
        if start <= 0:
            f.seek(0)
            return f.read()
        # 多读截断点前一字节：截断点恰好在行首时保留该行
        f.seek(start - 1)
        data = f.read()
    return data[data.find(b"\n") + 1 :] if b"\n" in data else b""


def _newest_images(debug_dir: Path) -> list[tuple[Path, int]]:
    """(路径, 大小)，按修改时间从新到旧；扫描后被 MaaFramework 轮换删除的图片直接跳过。"""
    images: list[tuple[Path, os.stat_result]] = []
    for name in _IMAGE_DIRS:
        if not (debug_dir / name).is_dir():
            continue
        for path in (debug_dir / name).rglob("*"):
            if path.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            try:
                info = path.stat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                images.append((path, info))
    images.sort(key=lambda item: item[1].st_mtime, reverse=True)
    return [(path, info.st_size) for path, info in images]


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
        for path, size in _newest_images(app_root / "debug"):
            if size > remaining:
                continue
            try:
                data = path.read_bytes()
            except FileNotFoundError:
                continue
            if len(data) > remaining:
                continue
            bundle.writestr(
                path.relative_to(app_root).as_posix(),
                data,
                compress_type=zipfile.ZIP_STORED,
            )
            remaining -= len(data)
