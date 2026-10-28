"""
Focus 事件处理器 — 按 display_channels 分发展示渠道，并管理 modal 的阻塞生命周期。
"""

import uuid
from typing import TYPE_CHECKING

from app_state import PendingFocusModal
from maa_worker.event_service import current_time
from maa_worker.focus_protocol import (
    DISPLAY_DIALOG,
    DISPLAY_NOTIFICATION,
    DISPLAY_TOAST,
    FocusDisplayEvent,
)
from models.api import FocusModal, RealtimeEvent

if TYPE_CHECKING:
    from maa_utils import MaaWorker


class FocusEventProcessor:
    """将 FocusDisplayEvent 按 display_channels 分发。

    - "log":          SSE 日志推送
    - "toast":        SSE toast 推送（前端 Naive UI 渲染）
    - "notification": 系统通知 (plyer / browser Notification)
    - "dialog":       前端非阻塞信息框（focus.display 的 notify 渠道）
    - "modal":        前端阻塞确认框，等待 confirm() 或 cancel_pending() 才放行
    """

    def __init__(self, worker: "MaaWorker") -> None:
        self.worker = worker

    def dispatch(self, event: FocusDisplayEvent) -> None:
        if event.has_modal:
            self._dispatch_modal(event)
            return
        self._emit_common(event)

    def confirm(self, focus_id: str) -> None:
        """确认并放行指定 modal；未知或已解除的 ID 直接忽略。"""
        focus_state = self.worker.focus_state
        with focus_state.lock:
            pending = focus_state.pending.pop(focus_id, None)
            if pending is None:
                return
            self.worker.message_conn.put(self._snapshot_locked())
            pending.released.set()

    def cancel_pending(self) -> None:
        """停止/退出时解除全部等待中的 modal。"""
        focus_state = self.worker.focus_state
        with focus_state.lock:
            if not focus_state.pending:
                return
            pending = list(focus_state.pending.values())
            focus_state.pending.clear()
            self.worker.message_conn.put(self._snapshot_locked())
            for entry in pending:
                entry.released.set()

    def snapshot(self) -> RealtimeEvent:
        """当前未确认 modal 的完整状态快照。"""
        with self.worker.focus_state.lock:
            return self._snapshot_locked()

    # ---- 内部方法 ------------------------------------------------------------

    def _snapshot_locked(self) -> RealtimeEvent:
        return RealtimeEvent(
            event="focus.modal",
            message="",
            time=current_time(),
            display=False,
            focus_modals=[
                entry.modal for entry in self.worker.focus_state.pending.values()
            ],
        )

    def _dispatch_modal(self, event: FocusDisplayEvent) -> None:
        focus_state = self.worker.focus_state
        with focus_state.lock:
            # stop() 在同一把锁下置位 stop_flag 后才 cancel_pending，
            # 停止之后到达的 modal 必须直接跳过，否则无人放行。
            if self.worker.task_state.stop_flag:
                return
            focus_id = uuid.uuid4().hex
            pending = PendingFocusModal(
                modal=FocusModal(
                    id=focus_id,
                    message=event.content,
                    level=event.level,
                )
            )
            focus_state.pending[focus_id] = pending
            self.worker.message_conn.put(self._snapshot_locked())

        self._emit_common(event)
        pending.released.wait()

    def _emit_common(self, event: FocusDisplayEvent) -> None:
        notify: list[str] = []
        if event.has_toast:
            notify.append(DISPLAY_TOAST)
        if event.has_notification:
            notify.append(DISPLAY_NOTIFICATION)
        if event.has_dialog:
            notify.append(DISPLAY_DIALOG)

        if not event.has_log and not notify:
            return

        self.worker.events.emit(
            "focus.display",
            event.content,
            display=event.has_log,
            notify=notify,
            level=event.level,
        )
