import json
import subprocess
import sys
import time

import pytest

from services import privilege_service


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell launcher")
def test_windows_replacement_starts_only_after_old_instance_exits(tmp_path):
    root = tmp_path / "app's & directory"
    root.mkdir()
    marker = root / "started.json"
    (root / "main.py").write_text(
        "import json,os; from pathlib import Path; "
        "Path(__file__).with_name('started.json').write_text(json.dumps(os.getcwd()))"
    )
    # Exercise the real launcher without opening UAC or starting MWU.
    old_code = """
import sys
from pathlib import Path
from services import privilege_service as p

original = p._windows_launcher_script
p._windows_launcher_script = lambda *args: original(*args).replace('-Verb RunAs', '-Verb Open')
print(p.request_elevation(Path(sys.argv[1])).status, flush=True)
sys.stdin.readline()
"""
    old = subprocess.Popen(
        [sys.executable, "-c", old_code, str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert old.stdout.readline().strip() == "success"
        time.sleep(1)
        assert old.poll() is None
        assert not marker.exists()
        old.communicate(input="exit\n", timeout=10)
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert json.loads(marker.read_text()) == str(root)
    finally:
        if old.poll() is None:
            old.terminate()
            old.wait(timeout=10)


def test_request_elevation_submits_detached_launcher_without_waiting(
    monkeypatch, tmp_path
):
    submitted = []

    class DetachedProcess:
        def poll(self):  # pragma: no cover - must never be consulted
            raise AssertionError("旧实例不得等待启动器结果")

        def wait(self, *_args, **_kwargs):  # pragma: no cover
            raise AssertionError("旧实例不得等待启动器退出")

    def fake_popen(argv, **kwargs):
        submitted.append((argv, kwargs))
        return DetachedProcess()

    monkeypatch.setattr(privilege_service.sys, "platform", "linux")
    monkeypatch.setattr(privilege_service.subprocess, "Popen", fake_popen)

    result = privilege_service.request_elevation(tmp_path)

    assert result.status == "success"
    assert len(submitted) == 1


def test_request_elevation_reports_submission_failure_without_recovery(
    monkeypatch, tmp_path
):
    attempts = []

    def failing_popen(argv, **kwargs):
        attempts.append(argv)
        raise OSError("launcher unavailable")

    monkeypatch.setattr(privilege_service.sys, "platform", "win32")
    monkeypatch.setattr(privilege_service.subprocess, "Popen", failing_popen)

    result = privilege_service.request_elevation(tmp_path)

    assert result.status == "failed"
    assert "launcher unavailable" in result.message
    assert len(attempts) == 1
