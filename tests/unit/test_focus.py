"""focus.display 的 dialog / modal 行为测试。

使用真实 UnifiedFocusResolver / FocusEventProcessor / EventService / TaskService，
仅替换 tasker、pretasks、pipeline 等外围协作者。
"""

import threading
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest

from app_state import AppState
from maa_worker.event_service import EventService
from maa_worker.focus_processor import FocusEventProcessor
from maa_worker.focus_protocol import DISPLAY_DIALOG, DISPLAY_LOG, DISPLAY_MODAL
from maa_worker.sink_service import SinkHandler
from maa_worker.task_service import TaskService
from models.api import RealtimeEvent
from models.settings import SettingsModel

MSG = "Node.Action.Starting"


@pytest.fixture(autouse=True)
def _default_settings(monkeypatch):
    """关闭系统/外部通知，避免测试读写用户设置或发送 webhook。"""
    monkeypatch.setattr(
        "maa_worker.event_service.load_settings", lambda: SettingsModel()
    )


class _ImmediateJob:
    done = True

    def wait(self):
        return self


class _FakeTasker:
    def __init__(self):
        self.running = False
        self.job: Any = _ImmediateJob()
        self.on_post_stop = None

    def post_stop(self):
        self.running = False
        if self.on_post_stop is not None:
            self.on_post_stop()
        return _ImmediateJob()

    def post_task(self, *_args, **_kwargs):
        return self.job


class _FakeInterface:
    label = "FocusTest"
    github = "https://example.invalid/focus"
    task: ClassVar[list[SimpleNamespace]] = [
        SimpleNamespace(name="Smoke", entry="EntrySmoke", option=[])
    ]


def make_worker() -> SimpleNamespace:
    state = AppState()
    worker = SimpleNamespace(
        state=state,
        task_state=state.task,
        focus_state=state.focus,
        message_conn=state.message_conn,
        interface=_FakeInterface(),
        http_client=None,
        tasker=_FakeTasker(),
        pretasks=SimpleNamespace(stop_current=lambda: None),
        pipeline=SimpleNamespace(build_task_pipeline_override=lambda *_a, **_k: {}),
    )
    worker.events = EventService(cast(Any, worker))
    worker.focus = FocusEventProcessor(cast(Any, worker))
    worker.tasks = TaskService(cast(Any, worker))
    return worker


def focus_details(content, display=DISPLAY_MODAL) -> dict:
    return {"name": "Gate", "focus": {MSG: {"content": content, "display": display}}}


def drain(worker) -> list[RealtimeEvent]:
    events = []
    while not worker.message_conn.empty():
        events.append(worker.message_conn.get_nowait())
    return events


def pending_ids(worker) -> list[str]:
    return [modal.id for modal in worker.focus.snapshot().focus_modals or []]


def start_modal(worker, content: str = "{name} 等待", display=DISPLAY_MODAL):
    """在独立线程触发 modal 回调，等到 pending 登记后返回线程与 focus_id。"""
    handler = SinkHandler(worker.focus)
    thread = threading.Thread(
        target=handler.on_event,
        args=(MSG, focus_details(content, display)),
        daemon=True,
    )
    thread.start()
    # 登记时在锁内入队快照，拿到即说明已登记
    snapshot = worker.message_conn.get(timeout=5)
    assert snapshot.event == "focus.modal"
    assert snapshot.focus_modals
    return thread, snapshot.focus_modals[-1].id


def test_modal_blocks_until_its_id_is_confirmed():
    worker = make_worker()
    thread, focus_id = start_modal(worker)
    try:
        assert worker.focus.snapshot().focus_modals[0].message == "Gate 等待"

        worker.focus.confirm("unknown")
        assert thread.is_alive()

        worker.focus.confirm(focus_id)
        thread.join(5)
        assert not thread.is_alive()
        assert pending_ids(worker) == []
        # 确认后推送空快照，供其他标签页关闭弹窗
        assert drain(worker)[-1].focus_modals == []
    finally:
        worker.focus.cancel_pending()
        thread.join(5)


def test_modal_with_other_channels_still_emits_them():
    worker = make_worker()
    thread, _ = start_modal(
        worker, "混合", [DISPLAY_LOG, DISPLAY_DIALOG, DISPLAY_MODAL]
    )
    try:
        displayed = worker.message_conn.get(timeout=5)
        assert displayed.event == "focus.display"
        assert displayed.display is True
        assert displayed.notify == [DISPLAY_DIALOG]
        assert thread.is_alive()
    finally:
        worker.focus.cancel_pending()
        thread.join(5)


@pytest.mark.parametrize("content", ["", "{entry}", " \t{entry}\n", 1, None])
def test_empty_or_invalid_content_neither_displays_nor_blocks(content):
    worker = make_worker()

    SinkHandler(worker.focus).on_event(
        MSG, focus_details(content, [DISPLAY_LOG, DISPLAY_MODAL])
    )

    assert worker.message_conn.empty()
    assert pending_ids(worker) == []


def test_stop_posts_native_stop_before_releasing_modal():
    worker = make_worker()
    worker.tasker.running = True
    released_at_stop: list[bool] = []

    def on_post_stop():
        pending = list(worker.focus_state.pending.values())
        released_at_stop.append(pending[0].released.is_set())

    worker.tasker.on_post_stop = on_post_stop
    thread, _ = start_modal(worker)
    try:
        assert worker.tasks.stop() is True
        thread.join(5)
        assert not thread.is_alive()
        assert released_at_stop == [False]
        assert pending_ids(worker) == []
    finally:
        worker.focus.cancel_pending()
        thread.join(5)


def test_modal_after_stop_does_not_block():
    worker = make_worker()
    worker.task_state.stop_flag = True

    SinkHandler(worker.focus).on_event(MSG, focus_details("等待"))

    assert pending_ids(worker) == []
    assert worker.message_conn.empty()


class _BlockingDoneJob:
    """首次检查 done 时阻塞，模拟任务已提交但尚未结束。"""

    def __init__(self):
        self.done_checked = threading.Event()
        self.release_done = threading.Event()

    @property
    def done(self) -> bool:
        if not self.done_checked.is_set():
            self.done_checked.set()
            self.release_done.wait(timeout=5)
        return True


def test_stop_during_last_task_reports_stopped_not_success():
    worker = make_worker()
    worker.task_state.running = True
    worker.tasker.running = True
    job = _BlockingDoneJob()
    worker.tasker.job = job
    thread = threading.Thread(
        target=worker.tasks.run_process, args=(["Smoke"], {}, [], {}), daemon=True
    )
    thread.start()
    try:
        assert job.done_checked.wait(timeout=5)
        worker.tasks.stop()
        job.release_done.set()
        thread.join(5)

        assert worker.task_state.last_status == "stopped"
        # 终端事件统一由 execution._complete_run 在清槽后发布，run_process 只落状态
        assert "task.completed" not in [event.event for event in drain(worker)]
    finally:
        job.release_done.set()
        thread.join(5)
