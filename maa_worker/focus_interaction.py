"""
焦点交互服务 — dialog / modal 渠道的阻塞等待实现（PI V2 v2.9.2 §9）。

dialog：非阻塞提示（前端 toast/对话框展示，自动消失，不等待）。
modal：阻塞确认 — 在 MAA 节点回调线程内等待 Python threading.Event，
等待期间 GIL 释放；用户在 UI 确认/取消后解除阻塞，流水线继续/停止。

广播规则：只有 pending → acknowledged / cancelled 的终态转换方（用户
ack/cancel 与 stop 兜底 wake_all_for_stop）负责广播 finished；等待与提醒
只观察状态，不广播。wait 超时返回 pending，等待方自行决定处理，不伪造终态。
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
    # 线程内部：阻塞等待事件（提醒起点 = 创建时刻，见 __post_init__）
    _ack_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _reminded_at: float = field(default=0.0, repr=False)
    _reminder_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        # Start the reminder interval at creation; a new modal must not be
        # reminded immediately on the next monitor tick.  Explicit created_at
        # (tests / replay) must behave identically: no second time source.
        if self._reminded_at == 0.0:
            self._reminded_at = self.created_at

    # ---- 公开语义 ------------------------------------------------------------

    def acknowledge(self) -> bool:
        """用户确认；返回是否生效（非 pending 幂等拒绝）。"""
        with self._lock:
            if self.state != "pending":
                return False
            self.state = "acknowledged"
        self._ack_event.set()
        return True

    def cancel(self) -> bool:
        """用户取消（或 stop/shutdown 兜底）；返回是否生效。"""
        with self._lock:
            if self.state != "pending":
                return False
            self.state = "cancelled"
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
        """在回调线程中阻塞等待用户操作；返回当前状态（可能仍为 pending）。"""
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
        # 仅登记仍 pending 的 modal。等待方直接持有 create_modal() 返回的
        # state 对象，不依赖（也不查询）本表；本表只服务 HTTP 与提醒查询。
        self._interactions: dict[str, FocusInteractionState] = {}

    # ---- 查询 ----------------------------------------------------------------

    def get_pending(self) -> list[dict]:
        with self._lock:
            return [
                it.to_public_dict()
                for it in self._interactions.values()
                if it.state == "pending"
            ]

    # ---- 创建与等待 ------------------------------------------------------------

    @staticmethod
    def _new_public_data(run_id: str, mode: str, content: str) -> dict:
        return {
            "id": uuid.uuid4().hex,
            "run_id": run_id,
            "mode": mode,
            "state": "pending",
            "content": content,
            "created_at": time.time(),
        }

    def create_dialog(self, run_id: str, content: str) -> None:
        """创建非阻塞 dialog：只广播一次 created，不登记/确认。"""
        self._notify_created(self._new_public_data(run_id, "dialog", content))

    def create_modal(self, run_id: str, content: str) -> FocusInteractionState:
        """创建阻塞 modal：创建后由调用方直接 wait() 同一对象。"""
        data = self._new_public_data(run_id, "modal", content)
        state = FocusInteractionState(
            id=data["id"],
            run_id=run_id,
            mode="modal",
            content=content,
            created_at=data["created_at"],
        )
        with self._lock:
            self._interactions[state.id] = state
        self._notify_created(data)
        return state

    def wait_modal(
        self, state: FocusInteractionState, timeout: float | None = None
    ) -> str:
        """在回调线程中等待 modal 的用户操作；只等待并返回，不广播。

        绝不在回调线程中调用 MAA 任务/stop/网络；仅 Event.wait。
        """
        return state.wait(timeout)

    # ---- 确认 / 取消 -----------------------------------------------------------

    def acknowledge(self, interaction_id: str) -> FocusInteractionState | None:
        state = self._find(interaction_id)
        if state is None:
            return None
        if not state.acknowledge():
            # 幂等：已结束的交互不重复广播
            return state
        self._remove_pending(state)
        self._notify_finished(state)
        return state

    def cancel(self, interaction_id: str) -> FocusInteractionState | None:
        state = self._find(interaction_id)
        if state is None:
            return None
        if not state.cancel():
            # 幂等：已结束的交互不重复广播
            return state
        self._remove_pending(state)
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
                self._remove_pending(it)
                self._notify_finished(it)

    def _remove_pending(self, state: FocusInteractionState) -> None:
        with self._lock:
            if self._interactions.get(state.id) is state:
                del self._interactions[state.id]

    # ---- 广播 ----------------------------------------------------------------

    def _find(self, interaction_id: str) -> FocusInteractionState | None:
        with self._lock:
            return self._interactions.get(interaction_id)

    def _notify_created(self, payload: dict) -> None:
        if self._on_created is not None:
            try:
                self._on_created(payload)
            except Exception:
                pass

    def _notify_finished(self, state: FocusInteractionState) -> None:
        if self._on_finished is not None:
            try:
                self._on_finished(state.to_public_dict())
            except Exception:
                pass
