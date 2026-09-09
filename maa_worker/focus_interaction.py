"""
焦点交互服务 — dialog / modal 渠道的阻塞等待实现（PI V2 v2.9.2 §9）。

dialog：非阻塞提示（前端 toast/对话框展示，自动消失，不等待）。
modal：阻塞确认 — 在 MAA 节点回调线程内等待 Python threading.Event，
等待期间 GIL 释放；用户在 UI 确认/取消后解除阻塞，流水线继续/停止。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

# modal 提醒周期：未确认时每 5 分钟提醒一次
MODAL_REMINDER_INTERVAL = 300.0


@dataclass
class FocusInteractionState:
    """一次焦点交互的后端状态（不持久化，进程内生命周期）。"""

    id: str
    run_id: str
    mode: str  # "dialog" | "modal"
    content: str
    created_at: float = field(default_factory=time.time)
    state: str = "pending"  # pending | acknowledged | cancelled
    # 线程内部：阻塞等待事件与提醒时间戳
    _ack_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _acknowledged: bool = False
    _cancelled: bool = False
    _reminded_at: float = 0.0
    _reminder_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- 公开语义 ------------------------------------------------------------

    def acknowledge(self) -> bool:
        """用户确认；返回是否生效（非 pending 幂等拒绝）。"""
        with self._lock:
            if self.state != "pending":
                return False
            self.state = "acknowledged"
            self._acknowledged = True
        self._ack_event.set()
        return True

    def cancel(self) -> bool:
        """用户取消（或 stop/shutdown 兜底）；返回是否生效。"""
        with self._lock:
            if self.state != "pending":
                return False
            self.state = "cancelled"
            self._cancelled = True
        self._ack_event.set()
        return True

    def mark_reminded(self) -> None:
        with self._lock:
            self._reminded_at = time.time()
            self._reminder_count += 1

    @property
    def reminder_due(self) -> bool:
        return (time.time() - self._reminded_at) >= MODAL_REMINDER_INTERVAL

    @property
    def reminder_count(self) -> int:
        with self._lock:
            return self._reminder_count

    def wait(self, timeout: float | None = None) -> str:
        """在回调线程中阻塞等待用户操作；返回最终状态。"""
        self._ack_event.wait(timeout)
        with self._lock:
            return self.state

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "mode": self.mode,
            "state": self.state,
            "content": self.content,
            "created_at": self.created_at,
        }


class FocusInteractionService:
    """管理 dialog / modal 交互的创建、等待、确认与广播钩子。"""

    def __init__(self, on_created=None, on_finished=None) -> None:
        # 广播钩子（EventService 注入）：on_created(state_dict), on_finished(state_dict)
        self._on_created = on_created
        self._on_finished = on_finished
        self._lock = threading.Lock()
        self._interactions: dict[str, FocusInteractionState] = {}

    # ---- 查询 ----------------------------------------------------------------

    def get_pending(self) -> list[dict]:
        with self._lock:
            return [
                it.to_public_dict()
                for it in self._interactions.values()
                if it.state == "pending"
            ]

    def _find(self, interaction_id: str) -> FocusInteractionState | None:
        with self._lock:
            return self._interactions.get(interaction_id)

    # ---- 创建与等待 ------------------------------------------------------------

    def create_dialog(self, run_id: str, content: str) -> FocusInteractionState:
        """创建非阻塞 dialog：广播后立即返回 acknowledged。"""
        state = FocusInteractionState(
            id=uuid.uuid4().hex,
            run_id=run_id,
            mode="dialog",
            content=content,
        )
        with self._lock:
            self._interactions[state.id] = state
        self._notify_created(state)
        return state

    def create_modal(self, run_id: str, content: str) -> FocusInteractionState:
        """创建阻塞 modal：创建后由回调线程 wait()。"""
        state = FocusInteractionState(
            id=uuid.uuid4().hex,
            run_id=run_id,
            mode="modal",
            content=content,
        )
        with self._lock:
            self._interactions[state.id] = state
        self._notify_created(state)
        return state

    def wait_modal(
        self, state: FocusInteractionState, timeout: float | None = None
    ) -> str:
        """在回调线程中等待 modal 的用户操作。

        绝不在回调线程中调用 MAA 任务/stop/网络；仅 Event.wait。
        """
        if state.mode != "modal":
            return state.state
        result = state.wait(timeout)
        self._notify_finished(state)
        return result

    # ---- 确认 / 取消 -----------------------------------------------------------

    def acknowledge(self, interaction_id: str) -> FocusInteractionState | None:
        state = self._find(interaction_id)
        if state is None:
            return None
        if not state.acknowledge():
            # 幂等：已结束的交互不重复广播
            return state
        self._notify_finished(state)
        return state

    def cancel(self, interaction_id: str) -> FocusInteractionState | None:
        state = self._find(interaction_id)
        if state is None:
            return None
        if not state.cancel():
            return state
        self._notify_finished(state)
        return state

    # ---- stop / shutdown 兜底 ---------------------------------------------------

    def wake_all_for_stop(self) -> None:
        """统一 stop / shutdown：将所有 pending modal 标记 cancelled 并唤醒。

        在回调线程外调用（TaskService.stop / shutdown）。
        """
        with self._lock:
            pending = [
                it for it in self._interactions.values() if it.state == "pending"
            ]
        for it in pending:
            if it.cancel():
                self._notify_finished(it)

    def prune_finished(self, keep: int = 200) -> None:
        """清理已结束交互，控制内存。"""
        with self._lock:
            if len(self._interactions) <= keep:
                return
            finished = [
                k for k, v in self._interactions.items() if v.state != "pending"
            ]
            for k in finished[: len(finished) - keep // 2]:
                del self._interactions[k]

    # ---- 广播 ----------------------------------------------------------------

    def _notify_created(self, state: FocusInteractionState) -> None:
        if self._on_created is not None:
            try:
                self._on_created(state.to_public_dict())
            except Exception:
                pass

    def _notify_finished(self, state: FocusInteractionState) -> None:
        if self._on_finished is not None:
            try:
                self._on_finished(state.to_public_dict())
            except Exception:
                pass
