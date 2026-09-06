"""焦点交互服务（dialog/modal）与 focus 协议 v2.9.2 行为测试。"""

import threading
import time

from maa_worker.focus_interaction import (
    FocusInteractionService,
    FocusInteractionState,
)
from maa_worker.focus_protocol import (
    DISPLAY_DIALOG,
    DISPLAY_LOG,
    DISPLAY_MODAL,
    FocusTemplate,
    UnifiedFocusResolver,
)
from maa_worker.focus_processor import FocusEventProcessor


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


class TestFocusInteractionService:
    def _service(self):
        created: list[dict] = []
        finished: list[dict] = []
        svc = FocusInteractionService(
            on_created=created.append, on_finished=finished.append
        )
        return svc, created, finished

    def test_create_dialog_auto_acknowledges_via_processor(self):
        svc, created, _ = self._service()
        state = svc.create_dialog("r1", "提示内容")
        assert state.mode == "dialog"
        assert len(created) == 1
        assert created[0]["mode"] == "dialog"
        svc.acknowledge(state.id)
        # acknowledge 是二次转换：dialog 创建时是 pending，确认后 acknowledged
        assert state.state == "acknowledged"

    def test_modal_lifecycle_created_waited_finished(self):
        svc, created, finished = self._service()
        state = svc.create_modal("r1", "是否继续?")
        assert state.state == "pending"
        assert created[0]["id"] == state.id
        assert created[0]["state"] == "pending"

        threading.Timer(0.05, svc.acknowledge, args=(state.id,)).start()
        result = svc.wait_modal(state)
        assert result == "acknowledged"
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
        assert len(finished) == 3

    def test_acknowledge_unknown_id_returns_none(self):
        svc, _, _ = self._service()
        assert svc.acknowledge("nope") is None
        assert svc.cancel("nope") is None

    def test_get_pending_only_lists_pending(self):
        svc, _, _ = self._service()
        s1 = svc.create_modal("r1", "A")
        s2 = svc.create_dialog("r1", "B")
        svc.acknowledge(s2.id)
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
