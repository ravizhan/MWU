import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path so that imports like `from models.xxx import yyy` work.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


@pytest.fixture(autouse=True)
def _isolated_app_root(monkeypatch, tmp_path):
    """应用根指向临时目录：测试不读写仓库内的 config/ 与 interface.json（CI 中不存在）。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "mwu.exe"))
