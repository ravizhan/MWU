"""
MAA Sink 回调协议集成 — 统一 Focus 协议管线。

所有 MAA 底层事件回调通过 UnifiedFocusResolver 解析为
FocusDisplayEvent，再由 FocusEventProcessor 按 display 通道
分发到 SSE / 系统通知。
"""

from collections.abc import Callable

from maa.event_sink import EventSink

from maa_worker.focus_processor import FocusEventProcessor
from maa_worker.focus_protocol import UnifiedFocusResolver

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
        focus: FocusEventProcessor,
        translate: Callable[[str], str | None] = lambda s: s,
    ):
        self._resolver = UnifiedFocusResolver()
        self._processor = focus
        self._translate = translate

    def on_event(self, msg: str, details: dict) -> None:
        """统一的 sink 事件入口。

        完全遵循 PI V2 v2.3.0 Client 处理流程：
        1. UnifiedFocusResolver 解析 (msg, details) → FocusDisplayEvent
        2. FocusEventProcessor 按 display_channels 分发到 SSE / 系统通知
        """
        event = self._resolver.resolve(msg, details, self._translate)
        if event is None:
            return
        self._processor.dispatch(event)


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
