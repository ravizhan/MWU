"""
MAA Sink 回调协议集成 — 统一 Focus 协议管线。

所有 MAA 底层事件回调通过 UnifiedFocusResolver 解析为
FocusDisplayEvent，再由 FocusEventProcessor 按 display 通道
分发到 SSE / 系统通知。
"""

from typing import TYPE_CHECKING

from maa.event_sink import EventSink

from maa_worker.focus_processor import FocusEventProcessor
from maa_worker.focus_protocol import UnifiedFocusResolver
from maa_worker.focus_protocol import DISPLAY_DIALOG, DISPLAY_MODAL

if TYPE_CHECKING:
    from maa_worker.event_service import EventService
    from services.telemetry_service import TelemetryService


# ---------------------------------------------------------------------------
# Sink 实例类 — 继承 EventSink，转发到共享 handler
# ---------------------------------------------------------------------------


class _SinkBase(EventSink):
    """所有 MWU sink 的公共基类 — 持有 handler 引用并在回调时转发。"""

    def __init__(self, handler: "SinkHandler"):
        super().__init__()
        self._handler = handler

    def _on_raw_notification(self, handle, msg: str, details: dict):
        self._handler.on_event(msg, details)


class MWUResourceSink(_SinkBase):
    """资源加载事件的 sink。"""


class MWUControllerSink(_SinkBase):
    """控制器动作事件的 sink。"""


class MWUTaskerSink(_SinkBase):
    """任务器事件的 sink。"""


class MWUContextSink(_SinkBase):
    """任务上下文（节点）事件的 sink。"""


# ---------------------------------------------------------------------------
# SinkHandler — 核心分发器（统一 Focus 协议管线）
# ---------------------------------------------------------------------------


class SinkHandler:
    """将 MAA 底层回调通过 UnifiedFocusResolver → FocusEventProcessor 统一处理。"""

    def __init__(
        self,
        events: "EventService",
        interactions=None,
        telemetry: "TelemetryService | None" = None,
    ):
        self._resolver = UnifiedFocusResolver()
        self._processor = FocusEventProcessor(events, interactions)
        self._telemetry = telemetry

    def on_event(self, msg: str, details: dict) -> None:
        """统一的 sink 事件入口。

        完全遵循 PI V2 v2.3.0 Client 处理流程：
        1. UnifiedFocusResolver 解析 (msg, details) → FocusDisplayEvent
        2. FocusEventProcessor 按 display_channels 分发到 SSE / 系统通知
        """
        event = self._resolver.resolve(msg, details)

        # Telemetry is strictly observational.  A broken client, scrubber, or
        # transport must never keep a focus modal from being acknowledged or
        # alter the local display/cancellation path.
        node_handle = None
        telemetry = self._telemetry
        try:
            state = getattr(getattr(self._processor, "_events", None), "worker", None)
            state = getattr(state, "state", None)
            active_run = getattr(state, "active_run", None)
            task_name = getattr(
                getattr(state, "task", None), "current_pi_task_name", None
            )
            if telemetry is not None and active_run is not None and event.trace_allowed:
                node_handle = telemetry.node_span(
                    active_run.run_id,
                    task_name=task_name,
                    message_type=msg,
                    details=details,
                    trace_allowed=event.trace_allowed,
                )
        except Exception:
            node_handle = None

        try:
            if event.has_modal:
                # modal：阻塞确认。cancelled → 置 stop_flag 终止流水线
                result = self._processor.handle_modal(event)
                if result == "cancelled":
                    # run_process 轮询分支不再提交 post_stop()；必须走统一 stop
                    # 路径才能真正终止原生任务。TaskService.stop() 已排除
                    # current_thread 自 join，回调线程内调用安全。
                    try:
                        self._processor._events.worker.tasks.stop()
                    except Exception:
                        pass
                return
            if event.has_dialog:
                self._processor.handle_dialog(event)
                return
            self._processor.dispatch(event)
        finally:
            if node_handle is not None and telemetry is not None:
                try:
                    node_result = "failed" if msg.endswith(".Failed") else "success"
                    telemetry.finish_node_span(node_handle, node_result)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# SinkService — 管理 sink 注册 / 注销生命周期
# ---------------------------------------------------------------------------


class SinkService:
    """统一管理 Resource / Controller / Tasker / Context 四类 sink 的注册和清理。"""

    def __init__(self, handler: SinkHandler):
        self._resource_sink = MWUResourceSink(handler)
        self._controller_sink = MWUControllerSink(handler)
        self._tasker_sink = MWUTaskerSink(handler)
        self._context_sink = MWUContextSink(handler)

        # 已注册的 sink_id
        self._resource_sink_id: int | None = None
        self._controller_sink_id: int | None = None
        self._tasker_sink_id: int | None = None
        self._context_sink_id: int | None = None

    # ---- Resource ----------------------------------------------------------

    def register_resource_sink(self, resource) -> int | None:
        if self._resource_sink_id is not None:
            return self._resource_sink_id
        sid = resource.add_sink(self._resource_sink)
        self._resource_sink_id = sid
        return sid

    def unregister_resource_sink(self, resource) -> None:
        if self._resource_sink_id is not None:
            resource.remove_sink(self._resource_sink_id)
            self._resource_sink_id = None

    # ---- Controller --------------------------------------------------------

    def register_controller_sink(self, controller) -> int | None:
        if self._controller_sink_id is not None:
            return self._controller_sink_id
        sid = controller.add_sink(self._controller_sink)
        self._controller_sink_id = sid
        return sid

    def unregister_controller_sink(self, controller) -> None:
        if self._controller_sink_id is not None:
            controller.remove_sink(self._controller_sink_id)
            self._controller_sink_id = None

    # ---- Tasker ------------------------------------------------------------

    def register_tasker_sink(self, tasker) -> int | None:
        if self._tasker_sink_id is not None:
            return self._tasker_sink_id
        sid = tasker.add_sink(self._tasker_sink)
        self._tasker_sink_id = sid
        return sid

    def unregister_tasker_sink(self, tasker) -> None:
        if self._tasker_sink_id is not None:
            tasker.remove_sink(self._tasker_sink_id)
            self._tasker_sink_id = None

    # ---- Context -----------------------------------------------------------

    def register_context_sink(self, tasker) -> int | None:
        if self._context_sink_id is not None:
            return self._context_sink_id
        sid = tasker.add_context_sink(self._context_sink)
        self._context_sink_id = sid
        return sid

    def unregister_context_sink(self, tasker) -> None:
        if self._context_sink_id is not None:
            tasker.remove_context_sink(self._context_sink_id)
            self._context_sink_id = None

    # ---- Batch -------------------------------------------------------------

    def register_all(self, resource, tasker) -> None:
        self.register_resource_sink(resource)
        self.register_tasker_sink(tasker)
        self.register_context_sink(tasker)

    def unregister_all(self, resource, tasker, controller=None) -> None:
        self.unregister_resource_sink(resource)
        self.unregister_tasker_sink(tasker)
        self.unregister_context_sink(tasker)
        if controller is not None:
            self.unregister_controller_sink(controller)
