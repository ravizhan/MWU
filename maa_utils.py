import io
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from PIL import Image

from app_state import WorkerContext
from maa_worker.focus_interaction import FocusInteractionService
from maa_worker.agent_service import AgentService
from maa_worker.device_service import DeviceService
from maa_worker.event_service import EventService
from maa_worker.pipeline_override import PipelineOverrideService
from maa_worker.pretask_service import PretaskService
from maa_worker.sink_service import SinkHandler, SinkService
from maa_worker.task_service import TaskService
from models.interface import InterfaceModel
from services.runtime_info import app_root

if TYPE_CHECKING:
    from app_state import AppState

resource = Resource()
resource.set_cpu()


class MaaWorker:
    def __init__(
        self,
        state: "AppState",
        interface: InterfaceModel,
    ):
        self.state = state
        self.interface = interface
        self.message_conn = state.message_conn
        self.resource = resource
        self.tasker = Tasker()
        self.http_client = httpx.Client(timeout=30)

        self.context = WorkerContext(interface_base_dir=app_root())
        self.device_state = state.device
        self.task_state = state.task
        self.agent_state = state.agent
        self.telemetry = state.telemetry_service

        Toolkit.init_option(str(self.context.interface_base_dir))

        self.events = EventService(self)

        def _broadcast_interaction(phase: str):
            def _hook(payload: dict):
                self.events.emit(
                    "focus.interaction",
                    payload.get("content", ""),
                    display=False,
                    title="任务交互",
                    details={
                        "phase": phase,
                        "id": payload.get("id"),
                        "mode": payload.get("mode"),
                        "state": payload.get("state"),
                        "run_id": payload.get("run_id"),
                    },
                )

            return _hook

        self.interactions = FocusInteractionService(
            on_created=_broadcast_interaction("created"),
            on_finished=_broadcast_interaction("finished"),
        )
        state.focus_interactions = self.interactions
        self.device = DeviceService(self)
        self.pipeline = PipelineOverrideService(self)
        self.agents = AgentService(self)
        self.pretasks = PretaskService(self)
        self.tasks = TaskService(self)

        self.sinks = SinkService(
            SinkHandler(
                self.events,
                interactions=self.interactions,
                telemetry=self.telemetry,
            )
        )
        self.sinks.register_all(self.resource, self.tasker)

        self.events.send_log("MAA初始化成功")

    def get_screencap_bytes(self):
        controller = self.device_state.controller
        if not self.device_state.connected or controller is None:
            return None
        try:
            image = controller.post_screencap().wait().get()
            if image is not None:
                image_pil = Image.fromarray(image[:, :, ::-1])
                img_byte_arr = io.BytesIO()
                image_pil.save(img_byte_arr, format="JPEG")
                return img_byte_arr.getvalue()
        except Exception:
            self.device.reset_connection_state(
                "检测到设备连接已断开，已解除设备与资源锁定"
            )
        return None

    def shutdown(self):
        if self.task_state.running:
            self.tasks.stop()
        else:
            # 前置任务阶段 running 尚未置位：兜底置停止标志并终止正在运行的前置进程，
            # 避免关闭/更新时用户前置命令一直阻塞到超时。
            self.task_state.stop_flag = True
            self.pretasks.stop_current()
        # 先释放 controller 与 portal helper（reset_connection_state 清空 device_state），
        # 再注销 sink，保证 PortalHelper 生命周期不越过控制器。
        self.device.reset_connection_state()
        self.sinks.unregister_all(
            self.resource,
            self.tasker,
            controller=self.device_state.controller,
        )
        if self.agent_state.agent_client is not None:
            self.agent_state.agent_client.disconnect()
        for process in self.agent_state.processes:
            process.terminate()
        self.http_client.close()
