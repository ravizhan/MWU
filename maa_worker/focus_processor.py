"""
Focus 事件处理器 — 按 display_channels 将 FocusDisplayEvent 分发到对应通道。
"""

import webbrowser
from typing import TYPE_CHECKING

from maa_worker.focus_protocol import (
    DISPLAY_DIALOG,
    DISPLAY_MODAL,
    DISPLAY_NOTIFICATION,
    DISPLAY_TOAST,
    FocusDisplayEvent,
)

if TYPE_CHECKING:
    from maa_worker.event_service import EventService
    from maa_worker.focus_interaction import FocusInteractionService

# modal 提醒：打开页面目标
_MODAL_PAGE_URL = "http://127.0.0.1:5566/tasks"


class FocusEventProcessor:
    """将 FocusDisplayEvent 按 display_channels 分发。

    - "log":          SSE 日志推送
    - "toast":        SSE toast 推送（前端 Naive UI 渲染）
    - "notification": 系统通知 (plyer / browser Notification)
    - "dialog":       非阻塞提示（SSE focus.interaction，前端展示后自动确认）
    - "modal":        阻塞确认（SSE focus.interaction，等待用户确认/取消）
    """

    def __init__(
        self,
        events: "EventService",
        interactions: "FocusInteractionService | None" = None,
    ) -> None:
        self._events = events
        self._interactions = interactions
        self._modal_page_opened = False

    # ---- 普通渠道 ------------------------------------------------------------

    def dispatch(self, event: FocusDisplayEvent) -> None:
        notify: list[str] = []
        if event.has_toast:
            notify.append(DISPLAY_TOAST)
        if event.has_notification:
            notify.append(DISPLAY_NOTIFICATION)

        self._events.emit(
            "focus.display",
            event.content,
            display=event.has_log,
            notify=notify,
            level=event.level,
        )

    # ---- 交互渠道 ------------------------------------------------------------

    def handle_dialog(self, event: FocusDisplayEvent) -> None:
        """dialog：非阻塞。创建后立即视为已确认，不等待。"""
        if self._interactions is None:
            self.dispatch(event)
            return
        state = self._interactions.create_dialog(self._current_run_id(), event.content)
        # dialog 展示即确认
        self._interactions.acknowledge(state.id)

    def handle_modal(self, event: FocusDisplayEvent) -> str:
        """modal：阻塞确认。在回调线程中调用，Event.wait 期间 GIL 释放。

        返回 "acknowledged" / "cancelled"。
        """
        if self._interactions is None:
            # 无交互服务（未注入）：退化为 toast，不阻塞流水线
            self.dispatch(
                FocusDisplayEvent(
                    content=event.content,
                    display_channels=[DISPLAY_TOAST],
                    level=event.level,
                    raw_msg=event.raw_msg,
                )
            )
            return "acknowledged"
        state = self._interactions.create_modal(self._current_run_id(), event.content)
        self._open_modal_page_once()
        return self._interactions.wait_modal(state)

    def _current_run_id(self) -> str:
        task_state = getattr(self._events.worker, "task_state", None)
        if task_state is not None and task_state.running:
            return str(getattr(task_state, "current_run_id", "") or "manual")
        return "manual"

    def _open_modal_page_once(self) -> None:
        """首个 pending modal 时打开 MWU 页面一次（每批任务一次）。"""
        if self._modal_page_opened:
            return
        self._modal_page_opened = True
        try:
            webbrowser.open_new(_MODAL_PAGE_URL)
        except Exception:
            pass

    def reset_modal_page_state(self) -> None:
        self._modal_page_opened = False
