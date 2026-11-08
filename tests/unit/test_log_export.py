"""日志打包：password 选项明文（含 JSON 转义形式）不得出现在 zip 内任何文本日志中。"""

import zipfile
from pathlib import Path

import pytest

from backend.core.state import build_log_event
from backend.services import log_export


def test_bundle_redacts_secrets_in_all_text_logs(tmp_path: Path) -> None:
    secret = 'p"ss\\密码'
    debug = tmp_path / "debug"
    debug.mkdir()
    # pipeline override 以 JSON 写入 maafw.log，明文以转义形式出现
    (debug / "maafw.log").write_text(
        '{"input": "p\\"ss\\\\\\u5bc6\\u7801"} {"input": "p\\"ss\\\\密码"}',
        encoding="utf-8",
    )
    (tmp_path / "updater.log").write_text(f"raw {secret}", encoding="utf-8")
    history = [build_log_event(f"登录 {secret}")]

    text_logs = log_export.snapshot_text_logs(tmp_path, history)
    bundle = log_export.build_bundle(tmp_path, text_logs, [secret])
    try:
        with zipfile.ZipFile(bundle) as archive:
            assert set(archive.namelist()) == {
                "mwu.log",
                "debug/maafw.log",
                "updater.log",
            }
            for name in archive.namelist():
                text = archive.read(name).decode("utf-8")
                assert "ss" not in text, name
                assert "******" in text, name
    finally:
        bundle.unlink()


def test_snapshot_excludes_log_lines_written_afterwards(tmp_path: Path) -> None:
    debug = tmp_path / "debug"
    debug.mkdir()
    log = debug / "maafw.log"
    log.write_bytes(b"before\n")
    text_logs = log_export.snapshot_text_logs(tmp_path, [])
    # 快照后新运行写入的密码不在收集到的密码里，也不能出现在 zip 中
    log.write_bytes(b"before\nnew-run-pass\n")

    bundle = log_export.build_bundle(tmp_path, text_logs, [])
    try:
        with zipfile.ZipFile(bundle) as archive:
            assert archive.read("debug/maafw.log") == b"before\n"
    finally:
        bundle.unlink()


def test_tail_cut_never_starts_inside_a_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(log_export, "LOG_TAIL_BYTES", 12)
    log = tmp_path / "maafw.log"
    # 截断点落在 hunter2 中间：不能留下 "er2" 这类无法匹配完整密码的残片
    log.write_bytes(b"pw hunter2\nkept\n")
    assert log_export._read_tail(log) == b"kept\n"


def test_bundle_skips_images_deleted_after_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_error = tmp_path / "debug" / "on_error"
    on_error.mkdir(parents=True)
    kept = on_error / "kept.png"
    kept.write_bytes(b"png")
    gone = on_error / "gone.png"
    gone.write_bytes(b"png")
    scan = log_export._newest_images

    def scan_then_rotate(debug_dir: Path) -> list[tuple[Path, int]]:
        images = scan(debug_dir)
        gone.unlink()  # MaaFramework 在扫描后轮换删除图片
        return images

    monkeypatch.setattr(log_export, "_newest_images", scan_then_rotate)
    bundle = log_export.build_bundle(tmp_path, [], [])
    try:
        with zipfile.ZipFile(bundle) as archive:
            assert archive.namelist() == ["debug/on_error/kept.png"]
    finally:
        bundle.unlink()
