"""日志打包：password 选项明文（含 JSON 转义形式）不得出现在 zip 内任何文本日志中。"""

import zipfile
from pathlib import Path

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
