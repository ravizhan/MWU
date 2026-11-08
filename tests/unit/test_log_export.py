"""日志打包：password 选项明文（含 JSON 转义形式）不得出现在 zip 内任何文本日志中。"""

import zipfile
from pathlib import Path

import pytest

from backend.core import secret_store
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

    bundle = log_export.build_bundle(tmp_path, history, [secret])
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


def test_secret_used_by_earlier_run_stays_masked_after_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(secret_store, "_key_path", lambda: tmp_path / "secret.key")
    secret_store._fernet.cache_clear()
    secrets_file = tmp_path / "log_secrets.json"
    try:
        # 第一次运行用 old-pass，之后配置改成 new-pass 再运行；导出时只剩 new-pass 在配置里
        log_export.remember_secrets(["old-pass"], secrets_file)
        log_export.remember_secrets(["new-pass"], secrets_file)
        assert "old-pass" not in secrets_file.read_text(encoding="utf-8")

        debug = tmp_path / "debug"
        debug.mkdir()
        (debug / "maafw.log").write_text("old-pass new-pass", encoding="utf-8")
        secrets = ["new-pass", *log_export.remembered_secrets(secrets_file)]
        bundle = log_export.build_bundle(tmp_path, [], secrets)
        try:
            with zipfile.ZipFile(bundle) as archive:
                assert archive.read("debug/maafw.log") == b"****** ******"
        finally:
            bundle.unlink()
    finally:
        secret_store._fernet.cache_clear()


def test_tail_cut_never_starts_inside_a_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(log_export, "LOG_TAIL_BYTES", 12)
    log = tmp_path / "maafw.log"
    # 截断点落在 hunter2 中间：不能留下 "er2" 这类无法匹配完整密码的残片
    log.write_bytes(b"pw hunter2\nkept\n")
    assert log_export._read_tail(log) == b"kept\n"
