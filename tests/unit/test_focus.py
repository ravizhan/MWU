"""focus.display 的 dialog / modal 行为回归测试。

覆盖协议解析、modal 阻塞与释放、停止路径，以及 main 的 SSE 状态投影。
使用真实 UnifiedFocusResolver / AppState / FocusEventProcessor / EventService /
TaskService，仅替换 worker 的设备、tasker、pipeline 等外围协作者。
"""

import asyncio
import importlib
import json
import sys
import threading
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest

from app_state import AppState, LogBroadcaster
from maa_worker.event_service import EventService
from maa_worker.focus_processor import FocusEventProcessor
from maa_worker.focus_protocol import (
    DISPLAY_DIALOG,
    DISPLAY_LOG,
    DISPLAY_MODAL,
    DISPLAY_TOAST,
    UnifiedFocusResolver,
)
from maa_worker.sink_service import SinkHandler
from maa_worker.task_service import TaskService
from models.api import RealtimeEvent
from models.interface import InterfaceModel
from models.settings import SettingsModel

MSG = "Node.Action.Starting"


@pytest.fixture(autouse=True)
def _default_settings(monkeypatch):
    """进程内关闭系统/外部通知，避免测试读写用户设置或发送 webhook。"""
    monkeypatch.setattr(
        "maa_worker.event_service.load_settings", lambda: SettingsModel()
    )


# ---------------------------------------------------------------------------
# worker 替身
# ---------------------------------------------------------------------------


class _ImmediateJob:
    done = True

    def wait(self):
        return self


class _FakeTasker:
    def __init__(self):
        self.running = False
        self.post_stop_calls = 0
        self.post_task_entries: list[str] = []
        self.job = _ImmediateJob()
        self.on_post_stop = None

    def post_stop(self):
        self.post_stop_calls += 1
        self.running = False
        if self.on_post_stop is not None:
            self.on_post_stop()
        return _ImmediateJob()

    def post_task(self, entry, pipeline_override=None):
        self.post_task_entries.append(entry)
        return self.job


class _FakePretasks:
    def __init__(self):
        self.stop_calls = 0

    def stop_current(self):
        self.stop_calls += 1


class _FakePipeline:
    def build_task_pipeline_override(self, *_args, **_kwargs):
        return {}


class _FakeInterface:
    label = "FocusTest"
    github = "https://example.invalid/focus"
    task: ClassVar[list[SimpleNamespace]] = [
        SimpleNamespace(name="Smoke", entry="EntrySmoke", option=[])
    ]


def make_worker(state: AppState | None = None) -> SimpleNamespace:
    state = state or AppState()
    worker = SimpleNamespace(
        state=state,
        task_state=state.task,
        focus_state=state.focus,
        message_conn=state.message_conn,
        interface=_FakeInterface(),
        http_client=None,
        tasker=_FakeTasker(),
        pretasks=_FakePretasks(),
        pipeline=_FakePipeline(),
    )
    worker.events = EventService(cast(Any, worker))
    worker.focus = FocusEventProcessor(cast(Any, worker))
    worker.tasks = TaskService(cast(Any, worker))
    state.worker = cast(Any, worker)
    return worker


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def focus_details(content, display="modal", *, name="Gate") -> dict:
    return {
        "name": name,
        "focus": {MSG: {"content": content, "display": display}},
    }


def resolve(msg: str, details: dict):
    event = UnifiedFocusResolver.resolve(msg, details)
    assert event is not None
    return event


def pending_ids(worker) -> list[str]:
    snapshot = worker.focus.snapshot()
    assert snapshot.event == "focus.modal"
    assert snapshot.focus_modals is not None
    return [modal.id for modal in snapshot.focus_modals]


def start_modal(
    worker, content: str, display="modal"
) -> tuple[threading.Thread, str, RealtimeEvent]:
    """在独立线程 dispatch 一个 modal，返回线程、focus_id 与登记时的状态变更标记。

    通过 message_conn 上的状态变更标记同步：标记入队发生在 pending 登记之后，
    因此无需 sleep 猜测登记时机。
    需要模拟「标记尚未被 log_monitor 消费」时，把返回的标记重新 put 回队列即可。
    """
    event = resolve(MSG, focus_details(content, display))
    assert event.has_modal
    assert worker.message_conn.empty(), "start_modal 前必须消费完旧的状态变更标记"
    thread = threading.Thread(target=worker.focus.dispatch, args=(event,), daemon=True)
    thread.start()
    marker = worker.message_conn.get(timeout=5)
    assert marker.event == "focus.modal"
    assert marker.message == ""
    assert marker.display is False
    ids = pending_ids(worker)
    assert ids
    return thread, ids[-1], marker


def drain(worker) -> list[RealtimeEvent]:
    events = []
    while not worker.message_conn.empty():
        events.append(worker.message_conn.get_nowait())
    return events


# ---------------------------------------------------------------------------
# 1. resolver + dispatch：dialog 不阻塞，modal 阻塞到确认
# ---------------------------------------------------------------------------


class TestDialogAndModalDispatch:
    def test_dialog_returns_immediately_and_emits_notify(self):
        worker = make_worker()

        event = resolve(MSG, focus_details("  {name} 等待\n", DISPLAY_DIALOG))

        assert event.has_dialog is True
        assert event.has_modal is False
        finished = threading.Event()

        def run():
            worker.focus.dispatch(event)
            # 返回即代表 Maa 线程可以继续执行后续节点
            finished.set()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        assert finished.wait(timeout=2)
        thread.join(5)
        assert not thread.is_alive()

        assert pending_ids(worker) == []
        displayed = worker.message_conn.get(timeout=5)
        assert displayed.event == "focus.display"
        assert displayed.message == "  Gate 等待\n"
        assert displayed.notify == [DISPLAY_DIALOG]
        assert displayed.display is False
        assert worker.message_conn.empty()

    def test_modal_blocks_until_correct_id_is_confirmed(self):
        worker = make_worker()
        thread, focus_id, _ = start_modal(worker, "{name} 等待")
        try:
            modals = worker.focus.snapshot().focus_modals
            assert modals is not None
            assert [modal.message for modal in modals] == ["Gate 等待"]
            assert thread.is_alive()

            worker.focus.confirm("does-not-exist")
            assert thread.is_alive()
            assert pending_ids(worker) == [focus_id]

            worker.focus.confirm(focus_id)
            thread.join(5)
            assert not thread.is_alive()
            assert pending_ids(worker) == []
        finally:
            worker.focus.cancel_pending()
            thread.join(5)

    def test_duplicate_confirm_does_not_release_next_modal(self):
        worker = make_worker()
        first, first_id, _ = start_modal(worker, "第一条")
        second: threading.Thread | None = None
        try:
            worker.focus.confirm(first_id)
            first.join(5)
            assert not first.is_alive()
            assert [event.event for event in drain(worker)] == ["focus.modal"]

            second, second_id, _ = start_modal(worker, "第二条")
            assert second_id != first_id
            worker.focus.confirm(first_id)
            assert second.is_alive()
            assert pending_ids(worker) == [second_id]

            worker.focus.confirm(second_id)
            second.join(5)
            assert not second.is_alive()
            assert pending_ids(worker) == []
        finally:
            worker.focus.cancel_pending()
            first.join(5)
            if second is not None:
                second.join(5)


# ---------------------------------------------------------------------------
# 2. 渠道组合与协议边界
# ---------------------------------------------------------------------------


class TestDisplayChannels:
    def test_log_toast_modal_share_one_display_and_one_pending(self):
        worker = make_worker()
        thread, focus_id, _ = start_modal(
            worker, "混合渠道", [DISPLAY_LOG, None, DISPLAY_TOAST, {}, DISPLAY_MODAL]
        )
        try:
            displayed = worker.message_conn.get(timeout=5)
            assert displayed.event == "focus.display"
            assert displayed.message == "混合渠道"
            assert displayed.display is True
            assert displayed.notify == [DISPLAY_TOAST]
            # 同一输入的 log/toast 只执行一次，且没有多余事件
            assert worker.message_conn.empty()
            assert pending_ids(worker) == [focus_id]

            worker.focus.confirm(focus_id)
            thread.join(5)
            assert not thread.is_alive()
            # 确认只投递一次状态变更标记，不追加展示消息
            assert worker.message_conn.get(timeout=5).event == "focus.modal"
            assert worker.message_conn.empty()
        finally:
            worker.focus.cancel_pending()
            thread.join(5)

    def test_modal_only_does_not_add_log_message(self):
        worker = make_worker()
        thread, focus_id, _ = start_modal(worker, "仅 modal")
        try:
            assert worker.message_conn.empty()
            assert pending_ids(worker) == [focus_id]
        finally:
            worker.focus.cancel_pending()
            thread.join(5)

    @pytest.mark.parametrize(
        "raw",
        ["{name} 开始", {"content": "{name} 开始"}],
        ids=["string-shorthand", "object-default-display"],
    )
    def test_string_shorthand_and_default_display_are_log(self, raw):
        worker = make_worker()

        event = resolve(MSG, {"name": "Gate", "focus": {MSG: raw}})

        assert event.has_log is True
        assert event.has_dialog is False
        assert event.has_modal is False
        worker.focus.dispatch(event)

        displayed = worker.message_conn.get(timeout=5)
        assert displayed.event == "focus.display"
        assert displayed.message == "Gate 开始"
        assert displayed.display is True
        assert displayed.notify == []
        assert pending_ids(worker) == []

    def test_trace_only_and_empty_content_never_register_modal(self):
        worker = make_worker()

        trace_event = resolve(MSG, focus_details("无渠道", "trace"))
        assert trace_event.has_modal is False
        worker.focus.dispatch(trace_event)

        unknown_event = resolve(MSG, focus_details("未知渠道", "banner"))
        assert unknown_event.has_modal is False
        worker.focus.dispatch(unknown_event)

        assert worker.message_conn.empty()
        assert pending_ids(worker) == []

        handler = SinkHandler(worker.focus)
        handler.on_event(MSG, focus_details("", DISPLAY_MODAL))
        handler.on_event(
            MSG,
            {"name": "Gate", "focus": {MSG: {"display": DISPLAY_MODAL}}},
        )

        assert worker.message_conn.empty()
        assert pending_ids(worker) == []

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            {"content": 1, "display": DISPLAY_MODAL},
            {"content": "忽略", "display": None},
            {"content": "忽略", "display": {"modal": True}},
            {"content": "忽略", "display": []},
        ],
    )
    def test_invalid_templates_and_empty_channels_do_not_display(self, raw):
        worker = make_worker()
        details = {"name": "Gate", "focus": {MSG: raw}}
        event = UnifiedFocusResolver.resolve(MSG, details)
        assert event is None or not event.has_modal

        SinkHandler(worker.focus).on_event(MSG, details)

        assert worker.message_conn.empty()
        assert pending_ids(worker) == []

    @pytest.mark.parametrize("content", ["{entry}", " \t{entry}{task_id}\n"])
    def test_blank_substitution_does_not_display_or_block(self, content):
        worker = make_worker()
        details = focus_details(content, [DISPLAY_LOG, DISPLAY_DIALOG, DISPLAY_MODAL])
        assert UnifiedFocusResolver.resolve(MSG, details) is None

        SinkHandler(worker.focus).on_event(MSG, details)

        assert worker.message_conn.empty()
        assert pending_ids(worker) == []

    @pytest.mark.parametrize("alias", ["Gate", "Starting"])
    def test_name_and_status_suffix_are_not_focus_keys(self, alias):
        worker = make_worker()

        event = resolve(
            MSG,
            {
                "name": "Gate",
                "focus": {alias: {"content": "别名", "display": DISPLAY_MODAL}},
            },
        )

        assert event.has_modal is False
        assert event.has_log is True
        assert event.content == "Gate 开始"
        worker.focus.dispatch(event)
        assert pending_ids(worker) == []
        assert worker.message_conn.get(timeout=5).message == "Gate 开始"


# ---------------------------------------------------------------------------
# 3. 停止路径
# ---------------------------------------------------------------------------


class TestStopReleasesPendingModals:
    @pytest.mark.parametrize("stop_fails", [False, True])
    def test_stop_native_stop_precedes_release(self, stop_fails):
        worker = make_worker()
        worker.tasker.running = True
        observed: list[str] = []

        def on_post_stop():
            with worker.focus_state.lock:
                pending = list(worker.focus_state.pending.values())
                assert pending
                observed.append(
                    "released" if pending[0].released.is_set() else "blocked"
                )
            if stop_fails:
                worker.tasker.running = True
                raise RuntimeError("native stop failed")

        worker.tasker.on_post_stop = on_post_stop
        thread, focus_id, _ = start_modal(worker, "Gate 等待")
        with worker.focus_state.lock:
            pending = worker.focus_state.pending[focus_id]
        try:
            if stop_fails:
                with pytest.raises(RuntimeError, match="native stop failed"):
                    worker.tasks.stop()
            else:
                assert worker.tasks.stop() is True
            thread.join(5)
            assert not thread.is_alive()
            assert observed == ["blocked"]
            assert worker.tasker.post_stop_calls == 1
            assert worker.pretasks.stop_calls == 1
            assert worker.task_state.stop_flag is True
            assert pending_ids(worker) == []
            assert pending.released.is_set()
        finally:
            worker.focus.cancel_pending()
            thread.join(5)

    @pytest.mark.parametrize("flag", ["stop_flag", "shutting_down"])
    def test_dispatch_after_stop_registers_nothing(self, flag):
        worker = make_worker()
        if flag == "stop_flag":
            worker.task_state.stop_flag = True
        else:
            worker.state.is_shutting_down = True

        event = resolve(MSG, focus_details("Gate 等待", DISPLAY_MODAL))
        worker.focus.dispatch(event)

        assert pending_ids(worker) == []
        assert worker.message_conn.empty()

    def test_confirm_after_stop_flag_published_is_noop(self):
        worker = make_worker()
        worker.tasker.running = True
        native_stop_entered = threading.Event()
        allow_native_stop = threading.Event()

        def on_post_stop():
            worker.tasker.running = False
            native_stop_entered.set()
            assert allow_native_stop.wait(timeout=5)

        worker.tasker.on_post_stop = on_post_stop
        thread, focus_id, _ = start_modal(worker, "Gate 等待")
        stop_thread = threading.Thread(target=worker.tasks.stop, daemon=True)
        stop_thread.start()
        try:
            assert native_stop_entered.wait(timeout=5)
            assert worker.task_state.stop_flag is True

            worker.focus.confirm(focus_id)

            assert pending_ids(worker) == [focus_id]
            with worker.focus_state.lock:
                assert worker.focus_state.pending[focus_id].released.is_set() is False
            assert worker.message_conn.empty()
            assert thread.is_alive()

            allow_native_stop.set()
            stop_thread.join(5)
            thread.join(5)
            assert not stop_thread.is_alive()
            assert not thread.is_alive()
            assert pending_ids(worker) == []
        finally:
            allow_native_stop.set()
            worker.focus.cancel_pending()
            thread.join(5)
            stop_thread.join(5)

    def test_run_process_stopped_after_post_loop_check(self):
        worker = make_worker()
        worker.task_state.running = True
        worker.tasker.running = True
        job = _BlockingDoneJob()
        worker.tasker.job = job
        thread = threading.Thread(
            target=worker.tasks.run_process,
            args=(["Smoke"], {}, [], {}),
            daemon=True,
        )
        thread.start()
        try:
            assert job.done_checked.wait(timeout=5)

            assert worker.tasks.stop() is True
            job.release_done.set()
            thread.join(5)

            assert not thread.is_alive()
            assert worker.task_state.last_status == "stopped"
            assert worker.task_state.last_error == "任务已终止"
            assert worker.tasker.post_stop_calls == 1
            events = drain(worker)
            names = [event.event for event in events]
            assert names.count("task.failed") == 1
            assert "task.completed" not in names
            assert "task.started" in names
        finally:
            job.release_done.set()
            worker.focus.cancel_pending()
            thread.join(5)


class _BlockingDoneJob:
    """首次检查 done 时阻塞，模拟任务已提交但尚未结束。"""

    def __init__(self):
        self.done_checked = threading.Event()
        self.release_done = threading.Event()
        self._checks = 0

    @property
    def done(self) -> bool:
        self._checks += 1
        if self._checks == 1:
            self.done_checked.set()
            if not self.release_done.wait(timeout=5):
                return False
        return True


# ---------------------------------------------------------------------------
# 4. pending 快照与 main 的 SSE 投影
# ---------------------------------------------------------------------------


class TestPendingSnapshots:
    def test_snapshot_keeps_only_unconfirmed_ids_and_cancel_clears_all(self):
        worker = make_worker()
        first, first_id, _ = start_modal(worker, "A")
        second, second_id, _ = start_modal(worker, "B")
        try:
            snapshot = worker.focus.snapshot()
            modals = snapshot.focus_modals
            assert modals is not None
            assert [modal.id for modal in modals] == [
                first_id,
                second_id,
            ]
            assert [modal.message for modal in modals] == ["A", "B"]

            worker.focus.confirm(first_id)
            first.join(5)
            assert not first.is_alive()
            assert pending_ids(worker) == [second_id]
            assert second.is_alive()

            worker.focus.cancel_pending()
            second.join(5)
            assert not second.is_alive()
            assert pending_ids(worker) == []
            assert worker.focus.snapshot().focus_modals == []
        finally:
            worker.focus.cancel_pending()
            first.join(5)
            second.join(5)


@pytest.fixture
def isolated_main(monkeypatch, tmp_path):
    sys.modules.pop("main", None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "mwu.exe"))
    (tmp_path / "page" / "assets").mkdir(parents=True)
    (tmp_path / "resource").mkdir()

    interface = InterfaceModel(
        interface_version=2,
        name="FocusTest",
        controller=[],
        resource=[],
        task=[],
    )
    monkeypatch.setattr(
        "models.interface_loader.load_interface_model",
        lambda _app_root: interface,
    )

    module = importlib.import_module("main")
    try:
        yield module
    finally:
        sys.modules.pop("main", None)


class _FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


def decode_chunk(chunk) -> RealtimeEvent:
    text = chunk.decode() if isinstance(chunk, bytes) else chunk
    assert text.startswith("data: ")
    return RealtimeEvent.model_validate(json.loads(text[len("data: ") :].strip()))


async def test_log_monitor_projects_latest_snapshot_for_queued_markers(isolated_main):
    main = isolated_main
    state = main.app_state
    worker = make_worker(state)
    state.broadcaster = LogBroadcaster()
    client = state.broadcaster.add_client(state.history_message)

    first, first_id, first_marker = start_modal(worker, "A")
    second, second_id, second_marker = start_modal(worker, "B")
    # 模拟登记标记尚未被 log_monitor 消费：先放回队列，再改变 pending 状态。
    state.message_conn.put(first_marker)
    state.message_conn.put(second_marker)
    try:
        # 标记入队后 A 已被确认：消费标记时必须投影「发送当时」的状态。
        worker.focus.confirm(first_id)
        first.join(5)
        assert not first.is_alive()

        state.is_shutting_down = False
        monitor = asyncio.create_task(main.log_monitor())
        try:
            received = [
                await asyncio.wait_for(client.get(), timeout=5) for _ in range(3)
            ]
        finally:
            state.is_shutting_down = True
            await asyncio.wait_for(monitor, timeout=5)

        assert all(event.event == "focus.modal" for event in received)
        assert all(event.message == "" for event in received)
        assert all(event.display is False for event in received)
        assert all(event.notify == [] for event in received)
        for event in received:
            assert event.focus_modals is not None
            assert [modal.id for modal in event.focus_modals] == [second_id]
        # 状态事件不进入历史，避免重连时重放旧 modal
        assert list(state.history_message) == []

        worker.focus.cancel_pending()
        second.join(5)
        assert not second.is_alive()

        state.is_shutting_down = False
        monitor = asyncio.create_task(main.log_monitor())
        try:
            cleared = await asyncio.wait_for(client.get(), timeout=5)
        finally:
            state.is_shutting_down = True
            await asyncio.wait_for(monitor, timeout=5)

        assert cleared.event == "focus.modal"
        assert cleared.focus_modals == []
        assert list(state.history_message) == []
    finally:
        worker.focus.cancel_pending()
        first.join(5)
        second.join(5)
        state.broadcaster.remove_client(client)


async def test_stream_logs_sends_snapshot_after_cleared_history(isolated_main):
    main = isolated_main
    state = main.app_state
    worker = make_worker(state)
    state.broadcaster = LogBroadcaster()
    state.history_message.append(
        RealtimeEvent(
            event="focus.display",
            message="旧 dialog",
            time="2026-01-01 00:00:00",
            notify=[DISPLAY_DIALOG],
            display=False,
        )
    )
    state.history_message.append(
        RealtimeEvent(
            event="focus.display",
            message="旧 toast",
            time="2026-01-01 00:00:00",
            notify=[DISPLAY_TOAST],
            display=False,
        )
    )
    thread, focus_id, _ = start_modal(worker, "等待中")
    try:
        response = await main.stream_logs(_FakeRequest())
        generator = response.body_iterator
        try:
            chunks = [
                await asyncio.wait_for(anext(generator), timeout=5) for _ in range(3)
            ]
        finally:
            await generator.aclose()

        events = [decode_chunk(chunk) for chunk in chunks]
        # 历史回放清空 notify，因此过去的 dialog/toast 不会重新弹出
        assert [event.message for event in events[:2]] == ["旧 dialog", "旧 toast"]
        assert all(event.notify == [] for event in events[:2])

        snapshot = events[2]
        assert snapshot.event == "focus.modal"
        assert snapshot.message == ""
        assert snapshot.display is False
        assert snapshot.focus_modals is not None
        assert [modal.id for modal in snapshot.focus_modals] == [focus_id]
    finally:
        worker.focus.cancel_pending()
        thread.join(5)


async def test_stream_logs_sends_empty_snapshot_without_pending(isolated_main):
    main = isolated_main
    state = main.app_state
    make_worker(state)
    state.broadcaster = LogBroadcaster()

    response = await main.stream_logs(_FakeRequest())
    generator = response.body_iterator
    try:
        first = await asyncio.wait_for(anext(generator), timeout=5)
    finally:
        await generator.aclose()

    snapshot = decode_chunk(first)
    assert snapshot.event == "focus.modal"
    assert snapshot.focus_modals == []
    assert list(state.history_message) == []
