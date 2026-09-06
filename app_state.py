import asyncio
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from queue import SimpleQueue
from typing import TYPE_CHECKING, Any

from models.api import RealtimeEvent, RealtimeEventLevel
from models.settings import SettingsModel

if TYPE_CHECKING:
    from maa.agent_client import AgentClient

    from maa_utils import MaaWorker
    from maa_worker.focus_interaction import FocusInteractionService
    from services.telemetry_service import TelemetryService
    from models.scheduler import ExecutionOrigin
    from scheduler_manager import SchedulerManager
    from services.system_scheduler import SystemScheduler


_HISTORY_MAXLEN = 2000


@dataclass
class WorkerContext:
    interface_base_dir: Path
    i18n_text_mapping: dict[str, Any] | None = None


@dataclass
class DeviceRuntimeState:
    controller: Any = None
    controller_type: str | None = None
    controller_name: str | None = None
    current_resource_name: str | None = None
    prepared_resource_name: str | None = None
    portal_helper: Any = None
    connected: bool = False
    configuration_locked: bool = False
    last_device_error: str | None = None
    last_resource_error: str | None = None


@dataclass
class TaskRuntimeState:
    stop_flag: bool = False
    running: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None
    last_status: str = "idle"
    last_error: str | None = None
    current_task_name: str | None = None
    current_pi_task_name: str | None = None
    pre_tasks: list | None = None
    current_pre_task_process: subprocess.Popen | None = None


@dataclass
class AgentRuntimeState:
    start_lock: threading.Lock = field(default_factory=threading.Lock)
    started_once: bool = False
    start_succeeded: bool = False
    start_error: str | None = None
    pi_env: dict[str, str] | None = None
    processes: list[subprocess.Popen] = field(default_factory=list)
    agent_client: "AgentClient" = None


@dataclass
class ActiveRun:
    """当前活跃运行占槽信息"""

    run_id: str
    origin: "ExecutionOrigin"
    task_name: str
    occurrence_id: str | None = None
    started: bool = False


class LogBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def add_client(self, history: deque[RealtimeEvent]) -> asyncio.Queue:
        q = asyncio.Queue()
        for message in history:
            q.put_nowait(message.model_copy(update={"notify": []}))
        self._queues.append(q)
        return q

    def remove_client(self, q: asyncio.Queue):
        if q in self._queues:
            self._queues.remove(q)

    async def broadcast(self, message: RealtimeEvent):
        for q in self._queues:
            await q.put(message)


def build_log_event(msg: str, level: RealtimeEventLevel = "info") -> RealtimeEvent:
    return RealtimeEvent(
        event="log",
        level=level,
        message=msg,
        time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        notify=[],
    )


class AppState:
    worker: "MaaWorker | None"
    broadcaster: LogBroadcaster | None
    scheduler_manager: "SchedulerManager | None"
    settings: SettingsModel | None
    system_scheduler: "SystemScheduler | None"

    def __init__(self):
        self.message_conn: SimpleQueue[RealtimeEvent] = SimpleQueue()
        self.worker = None
        self.is_shutting_down = False
        self.history_message: deque[RealtimeEvent] = deque(maxlen=_HISTORY_MAXLEN)
        self.broadcaster = None
        self.scheduler_manager = None
        self.settings = None
        self.update_status: dict | None = None
        self.update_info: dict | None = None
        # 运行时状态（合并自 maa_worker/runtime.py）
        self.device = DeviceRuntimeState()
        self.task = TaskRuntimeState()
        self.agent = AgentRuntimeState()
        # 薄执行模块状态
        self.active_run: ActiveRun | None = None
        self.active_execution_task: asyncio.Task | None = None
        self.update_in_progress = False
        # 准备临界区：_complete_run 与直接 device/resource API 共用（事件循环拥有）
        self.preparation_lock: asyncio.Lock = asyncio.Lock()
        # 焦点交互服务（dialog/modal 阻塞等待；MaaWorker 构造时绑定）
        self.focus_interactions: "FocusInteractionService | None" = None
        # 用户授权后的独立遥测服务；Worker/SinkHandler 只读取此实例
        self.telemetry_service: "TelemetryService | None" = None
        # 系统级调度状态
        self.pending_scheduled_task_id: str | None = None
        self.native_token: str | None = None
        self.system_scheduler = None
        self.scheduler_db_path = Path("config") / "scheduler.sqlite"

    def send_log(self, msg: str):
        self.message_conn.put(build_log_event(msg))

    def set_update_in_progress(self) -> None:
        self.update_in_progress = True

    def clear_update_in_progress(self) -> None:
        self.update_in_progress = False
