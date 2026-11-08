"""日志打包：password 选项明文（含 JSON 转义形式）不得出现在 zip 内任何文本日志中。"""

import zipfile
from pathlib import Path

import pytest

from backend.core import secret_store
from backend.core.state import build_log_event
from backend.services import log_export


@pytest.fixture
def secret_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(secret_store, "_key_path", lambda: tmp_path / "secret.key")
    monkeypatch.setattr(log_export, "_write_failed", False)
    secret_store._fernet.cache_clear()
    yield
    secret_store._fernet.cache_clear()


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


@pytest.mark.usefixtures("secret_key")
def test_secret_used_by_earlier_run_stays_masked_after_change(tmp_path: Path) -> None:
    secrets_file = tmp_path / "log_secrets.json"
    # 第一次运行用旧密码，之后配置改成 new-pass 再运行；导出时只剩 new-pass 在配置里。
    # 旧密码恰好带加密前缀，也必须加密落盘并能还原
    old = "mwu-secret:v1:old-pass"
    assert log_export.remember_secrets([old], secrets_file)
    assert log_export.remember_secrets(["new-pass"], secrets_file)
    assert "old-pass" not in secrets_file.read_text(encoding="utf-8")

    debug = tmp_path / "debug"
    debug.mkdir()
    (debug / "maafw.log").write_text(f"{old} new-pass", encoding="utf-8")
    text_logs = log_export.snapshot_text_logs(tmp_path, [])
    secrets = ["new-pass", *log_export.remembered_secrets(secrets_file)]
    bundle = log_export.build_bundle(tmp_path, text_logs, secrets)
    try:
        with zipfile.ZipFile(bundle) as archive:
            assert archive.read("debug/maafw.log") == b"****** ******"
    finally:
        bundle.unlink()


@pytest.mark.usefixtures("secret_key")
def test_corrupt_record_blocks_export_even_after_rewrite(tmp_path: Path) -> None:
    secrets_file = tmp_path / "log_secrets.json"
    # 截断的记录里原有的旧密码已无法识别：后续运行照常记录，但导出一直拒绝
    secrets_file.write_text('{"secrets": ["mwu-sec', encoding="utf-8")
    with pytest.raises(log_export.SecretRecordIncomplete):
        log_export.remembered_secrets(secrets_file)

    assert log_export.remember_secrets(["pass"], secrets_file)
    with pytest.raises(log_export.SecretRecordIncomplete):
        log_export.remembered_secrets(secrets_file)

    # 用户清理日志并删除记录后恢复导出
    secrets_file.unlink()
    assert log_export.remember_secrets(["pass"], secrets_file)
    assert log_export.remembered_secrets(secrets_file) == ["pass"]


@pytest.mark.usefixtures("secret_key")
def test_failed_write_blocks_export_and_persists_on_next_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets_file = tmp_path / "log_secrets.json"
    assert log_export.remember_secrets(["old"], secrets_file)

    def fail_write(*_args) -> None:
        raise PermissionError("locked")

    with monkeypatch.context() as patch:
        patch.setattr(log_export, "atomic_write_json", fail_write)
        assert not log_export.remember_secrets(["lost"], secrets_file)
    with pytest.raises(log_export.SecretRecordIncomplete):
        log_export.remembered_secrets(secrets_file)

    # 下一次成功写入把不完整状态落盘，重启（进程内状态清空）后仍拒绝导出
    assert log_export.remember_secrets([], secrets_file)
    monkeypatch.setattr(log_export, "_write_failed", False)
    with pytest.raises(log_export.SecretRecordIncomplete):
        log_export.remembered_secrets(secrets_file)


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
