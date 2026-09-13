"""焦点交互服务（dialog/modal）与 focus 协议 v2.9.2 行为测试。"""

import threading
import time

from maa_worker.focus_interaction import (
    MODAL_REMINDER_INTERVAL,
    FocusInteractionService,
    FocusInteractionState,
)
from maa_worker.focus_processor import FocusEventProcessor
from maa_worker.focus_protocol import (
    DISPLAY_DIALOG,
    DISPLAY_LOG,
    DISPLAY_MODAL,
    DISPLAY_NOTIFICATION,
    DISPLAY_TOAST,
    FocusTemplate,
    UnifiedFocusResolver,
)
from maa_worker.sink_service import SinkHandler


class TestFocusInteractionState:
    def test_acknowledge_transitions_and_sets_event(self):
        state = FocusInteractionState(
            id="i1", run_id="r1", mode="modal", content="继续?"
        )
        assert state.state == "pending"
        assert state.acknowledge() is True
        assert state.state == "acknowledged"
        # 幂等：二次确认被拒绝
        assert state.acknowledge() is False
        assert state.cancel() is False

    def test_cancel_transitions_and_sets_event(self):
        state = FocusInteractionState(
            id="i2", run_id="r1", mode="modal", content="停止?"
        )
        assert state.cancel() is True
        assert state.state == "cancelled"
        assert state.acknowledge() is False

    def test_wait_returns_after_acknowledge(self):
        state = FocusInteractionState(
            id="i3", run_id="r1", mode="modal", content="等待"
        )

        def _ack_later():
            time.sleep(0.05)
            state.acknowledge()

        threading.Thread(target=_ack_later, daemon=True).start()
        result = state.wait(timeout=5)
        assert result == "acknowledged"

    def test_wait_timeout_returns_pending(self):
        state = FocusInteractionState(
            id="i4", run_id="r1", mode="modal", content="永不确认"
        )
        assert state.wait(timeout=0.05) == "pending"

    def test_reminder_starts_at_creation(self):
        state = FocusInteractionState(
            id="i5", run_id="r1", mode="modal", content="稍后提醒"
        )
        assert state.reminder_due is False

    def test_reminder_starts_at_explicit_created_at(self):
        """提醒起点 = 显式 created_at，不另取独立时钟起点。"""
        created = time.time() - MODAL_REMINDER_INTERVAL - 1
        state = FocusInteractionState(
            id="i6",
            run_id="r1",
            mode="modal",
            content="旧创建时间",
            created_at=created,
        )
        assert state.reminder_due is True


class TestFocusInteractionService:
    def _service(self):
        created: list[dict] = []
        finished: list[dict] = []
        svc = FocusInteractionService(
            on_created=created.append, on_finished=finished.append
        )
        return svc, created, finished

    def test_modal_lifecycle_created_waited_finished(self):
        svc, created, finished = self._service()
        state = svc.create_modal("r1", "是否继续?")
        assert state.state == "pending"
        assert created[0]["id"] == state.id
        assert created[0]["state"] == "pending"

        threading.Timer(0.05, svc.acknowledge, args=(state.id,)).start()
        result = svc.wait_modal(state)
        assert result == "acknowledged"
        # wait 只等待；finished 由唯一的终态转换方（acknowledge）广播一次
        assert [entry["state"] for entry in finished] == ["acknowledged"]

    def test_wait_modal_timeout_returns_pending_without_finished(self):
        svc, created, finished = self._service()
        state = svc.create_modal("r1", "永不确认")

        result = svc.wait_modal(state, timeout=0.05)

        assert result == "pending"
        assert created and created[0]["state"] == "pending"
        # 等待超时不广播 finished（等待不承担终态转换）
        assert finished == []
        assert [item["id"] for item in svc.get_pending()] == [state.id]

    def test_ack_before_wait_uses_direct_state(self):
        svc, _, finished = self._service()
        state = svc.create_modal("r1", "已经确认")

        # ack 可能在创建广播后、回调线程进入 wait_modal 前到达；等待方
        # 直接持有 state，不通过 pending 字典重新查找。
        assert svc.acknowledge(state.id) is state
        assert svc.wait_modal(state) == "acknowledged"
        assert svc.get_pending() == []
        assert len(finished) == 1

    def test_acknowledge_broadcasts_finished_exactly_once(self):
        svc, _, finished = self._service()
        state = svc.create_modal("r1", "继续?")

        assert svc.acknowledge(state.id) is state
        assert svc.acknowledge(state.id) is None
        assert svc.cancel(state.id) is None

        assert [entry["id"] for entry in finished] == [state.id]
        assert finished[-1]["state"] == "acknowledged"

    def test_wake_all_for_stop_cancels_pending(self):
        svc, _, finished = self._service()
        s1 = svc.create_modal("r1", "A")
        s2 = svc.create_modal("r2", "B")
        acked = svc.create_modal("r3", "C")
        svc.acknowledge(acked.id)

        svc.wake_all_for_stop()

        assert s1.state == "cancelled"
        assert s2.state == "cancelled"
        assert acked.state == "acknowledged"
        assert [entry["id"] for entry in finished] == [acked.id, s1.id, s2.id]
        assert [entry["state"] for entry in finished] == [
            "acknowledged",
            "cancelled",
            "cancelled",
        ]
        assert svc.get_pending() == []

    def test_acknowledge_unknown_id_returns_none(self):
        svc, _, _ = self._service()
        assert svc.acknowledge("nope") is None
        assert svc.cancel("nope") is None

    def test_get_pending_only_lists_pending(self):
        svc, _, _ = self._service()
        s1 = svc.create_modal("r1", "A")
        svc.create_dialog("r1", "B")
        pending = svc.get_pending()
        assert [p["id"] for p in pending] == [s1.id]


class TestResolverStrictness:
    def test_dialog_and_modal_channels_pass_through(self):
        resolver = UnifiedFocusResolver()
        event = resolver.resolve(
            "Node.Action.Starting",
            {
                "focus": {
                    "Node.Action.Starting": {
                        "content": "请选择",
                        "display": ["modal", "log"],
                    }
                },
                "name": "N",
            },
        )
        assert event.has_modal
        assert event.has_log

    def test_trace_explicit_true(self):
        event = UnifiedFocusResolver().resolve(
            "Node.Action.Starting",
            {
                "focus": {
                    "Node.Action.Starting": {
                        "content": "x",
                        "display": ["log"],
                        "trace": True,
                    }
                },
            },
        )
        assert event.trace_allowed is True

    def test_trace_explicit_false(self):
        event = UnifiedFocusResolver().resolve(
            "Node.PipelineNode.Failed",
            {
                "focus": {
                    "Node.PipelineNode.Failed": {
                        "content": "x",
                        "display": ["log"],
                        "trace": False,
                    }
                },
            },
        )
        assert event.trace_allowed is False

    def test_trace_default_true_only_for_pipeline_node_failed(self):
        resolver = UnifiedFocusResolver()
        failed = resolver.resolve(
            "Node.PipelineNode.Failed",
            {"focus": {"Node.PipelineNode.Failed": {"content": "x"}}},
        )
        starting = resolver.resolve(
            "Node.Action.Starting",
            {"focus": {"Node.Action.Starting": {"content": "x"}}},
        )
        assert failed.trace_allowed is True
        assert starting.trace_allowed is False

    def test_name_fallback_removed(self):
        """严格新格式：不再按 name / 状态后缀回退查找模板。"""
        event = UnifiedFocusResolver().resolve(
            "Node.Action.Starting",
            {
                "focus": {"MyNode": {"content": "命中了旧回退"}},
                "name": "MyNode",
            },
        )
        assert "旧回退" not in event.content
        assert event.display_channels == [DISPLAY_LOG]

    def test_suffix_fallback_removed(self):
        event = UnifiedFocusResolver().resolve(
            "Node.Action.Starting",
            {"focus": {"Starting": {"content": "命中了后缀回退"}}},
        )
        assert "后缀回退" not in event.content

    def test_focus_template_raw_shapes(self):
        plain = FocusTemplate.from_raw("文本")
        assert plain.display == [DISPLAY_LOG]
        assert plain.trace is None
        obj = FocusTemplate.from_raw(
            {"content": "c", "display": ["modal"], "trace": True}
        )
        assert obj.display == [DISPLAY_MODAL]
        assert obj.trace is True
        # display 无效值回退 log
        bad = FocusTemplate.from_raw({"content": "c", "display": ["bogus"]})
        assert bad.display == [DISPLAY_LOG]


class TestProcessorInteractions:
    def _events(self):
        sent: list[dict] = []

        class _FakeEvents:
            def emit(self, event, message, **kwargs):
                sent.append({"event": event, "message": message, **kwargs})

            worker = None

        return _FakeEvents(), sent

    def test_dialog_without_interactions_degrades_to_dispatch(self):
        events, sent = self._events()
        processor = FocusEventProcessor(events)
        from maa_worker.focus_protocol import FocusDisplayEvent

        processor.handle_dialog(
            FocusDisplayEvent(content="提示", display_channels=[DISPLAY_DIALOG])
        )
        assert sent and sent[0]["event"] == "focus.display"

    def test_dialog_with_interactions_broadcasts_created_without_ack(self):
        events, _ = self._events()
        created: list[dict] = []
        finished: list[dict] = []
        svc = FocusInteractionService(
            on_created=created.append, on_finished=finished.append
        )
        processor = FocusEventProcessor(events, svc)
        from maa_worker.focus_protocol import FocusDisplayEvent

        processor.handle_dialog(
            FocusDisplayEvent(content="提示", display_channels=[DISPLAY_DIALOG])
        )

        assert len(created) == 1
        assert created[0]["mode"] == "dialog"
        assert created[0]["content"] == "提示"
        # 非阻塞 dialog：只有一次 created，无确认状态机、无 finished 广播
        assert finished == []
        assert svc.get_pending() == []

    def test_modal_without_interactions_degrades_to_acknowledged(self):
        events, _ = self._events()
        processor = FocusEventProcessor(events)
        from maa_worker.focus_protocol import FocusDisplayEvent

        result = processor.handle_modal(
            FocusDisplayEvent(content="确认?", display_channels=[DISPLAY_MODAL])
        )
        assert result == "acknowledged"

    def test_modal_with_interactions_blocks_until_ack(self):
        events, _ = self._events()
        created: list[dict] = []
        svc = FocusInteractionService(on_created=created.append)
        processor = FocusEventProcessor(events, svc)
        from maa_worker.focus_protocol import FocusDisplayEvent

        # 用户在 modal 创建后确认（on_created 钩子里延迟 ack）
        original_hook = svc._on_created

        def _hook_then_ack(payload):
            original_hook(payload)
            threading.Timer(0.05, svc.acknowledge, args=(payload["id"],)).start()

        svc._on_created = _hook_then_ack
        result = processor.handle_modal(
            FocusDisplayEvent(content="继续?", display_channels=[DISPLAY_MODAL])
        )
        assert result == "acknowledged"
        assert created and created[0]["mode"] == "modal"


class TestSinkHandlerChannels:
    def test_mixed_channels_dispatch_before_dialog_and_modal(self):
        events, _ = TestProcessorInteractions()._events()
        handler = SinkHandler(events)
        calls: list[str] = []

        handler._processor.dispatch = lambda event: calls.append("dispatch")
        handler._processor.handle_dialog = lambda event: calls.append("dialog")
        handler._processor.handle_modal = lambda event: (
            calls.append("modal") or "acknowledged"
        )

        handler.on_event(
            "Node.Action.Starting",
            {
                "focus": {
                    "Node.Action.Starting": {
                        "content": "请选择",
                        "display": [
                            DISPLAY_DIALOG,
                            DISPLAY_LOG,
                            DISPLAY_NOTIFICATION,
                            DISPLAY_TOAST,
                            DISPLAY_MODAL,
                        ],
                    }
                }
            },
        )

        assert calls == ["dispatch", "dialog", "modal"]
