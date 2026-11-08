"""阻止休眠：Windows 激活失败不能留下等待释放的非守护线程，否则应用关闭时进程卡住。"""

import threading

import pytest
from wakepy.methods import windows

from backend.maa_worker.keep_awake import _WindowsKeepRunning


def test_failed_windows_activation_leaves_no_inhibitor_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_inhibit(flags: int) -> int:
        if flags != windows.Flags.RELEASE.value:
            raise RuntimeError("SetThreadExecutionState returned NULL")
        return flags

    monkeypatch.setattr(windows, "_call_set_thread_execution_state", fail_inhibit)
    method = _WindowsKeepRunning()
    with pytest.raises(RuntimeError):
        method.enter_mode()

    thread = method._inhibiting_thread
    assert isinstance(thread, threading.Thread)
    thread.join(timeout=5)
    assert not thread.is_alive()
