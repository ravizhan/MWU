import importlib
import sys
from types import SimpleNamespace

import pytest

from models.api import DeviceModel
from models.interface import InterfaceModel
from services import privilege_service


@pytest.fixture
def isolated_main(monkeypatch, tmp_path):
    sys.modules.pop("main", None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "mwu.exe"))
    (tmp_path / "page" / "assets").mkdir(parents=True)
    (tmp_path / "resource").mkdir()

    interface = InterfaceModel.model_validate(
        {
            "interface_version": 2,
            "name": "Test",
            "controller": [
                {"name": "ADB", "label": "ADB", "type": "Adb"},
                {"name": "PC", "label": "PC", "type": "Win32"},
            ],
            "resource": [
                {"name": "none", "path": [], "controller": None},
                {"name": "empty", "path": [], "controller": []},
                {"name": "adb", "path": [], "controller": ["ADB"]},
                {"name": "pc", "path": [], "controller": ["PC"]},
                {"name": "both", "path": [], "controller": ["ADB", "PC"]},
            ],
            "task": [],
        }
    )
    monkeypatch.setattr(
        "models.interface_loader.load_interface_model",
        lambda _app_root: interface,
    )

    module = importlib.import_module("main")
    try:
        yield module
    finally:
        sys.modules.pop("main", None)


@pytest.mark.parametrize(
    ("controller_type", "expected_names"),
    [
        (None, ["none", "empty", "adb", "pc", "both"]),
        ("Win32", ["none", "empty", "pc", "both"]),
        ("Unknown", ["none", "empty"]),
    ],
)
def test_get_resource_filters_by_controller_type(
    isolated_main,
    controller_type,
    expected_names,
):
    isolated_main.app_state.worker = object()

    response = isolated_main.get_resource(controller_type)

    assert response["status"] == "success"
    assert [resource["name"] for resource in response["resource"]] == expected_names


def test_get_resource_requires_worker(isolated_main):
    isolated_main.app_state.worker = None

    assert isolated_main.get_resource(None) == {
        "status": "failed",
        "message": "Worker未初始化",
    }


@pytest.mark.asyncio
async def test_connect_device_keeps_real_connect_semantics(isolated_main):
    calls = []

    class DeviceState:
        connected = False
        last_device_error = None

    class Device:
        def prepare_connection(self, device, resource_name, global_options, pre_tasks):
            calls.append(("prepare", resource_name))
            return True

        def connect(self, device):
            calls.append(("connect", device.address))
            isolated_main.app_state.worker.device_state.connected = True
            return True

    class Worker:
        device_state = DeviceState()
        device = Device()

    isolated_main.app_state.worker = Worker()
    request = isolated_main.DeviceConnectRequest(
        device=DeviceModel(
            type="Adb",
            controller_name="ADB",
            address="127.0.0.1:5555",
        ),
        resource_name="main",
    )

    result = await isolated_main.connect_device(request)

    assert result == {"status": "success"}
    assert calls == [("prepare", "main"), ("connect", "127.0.0.1:5555")]


@pytest.mark.asyncio
async def test_connect_device_reuses_prepared_connection_without_reconnect(
    isolated_main,
):
    calls = []

    class DeviceState:
        connected = True
        last_device_error = None

    class Device:
        def prepare_connection(self, device, resource_name, global_options, pre_tasks):
            calls.append("prepare")
            return True

        def connect(self, device):
            calls.append("connect")
            return False

    class Worker:
        device_state = DeviceState()
        device = Device()

    isolated_main.app_state.worker = Worker()
    request = isolated_main.DeviceConnectRequest(
        device=DeviceModel(
            type="Adb",
            controller_name="ADB",
            address="127.0.0.1:5555",
        ),
        resource_name="main",
    )

    result = await isolated_main.connect_device(request)

    assert result == {"status": "success"}
    assert calls == ["prepare"]


class _LifecycleWorker:
    class _TaskState:
        running = True

    class _Tasks:
        def __init__(self, events):
            self.events = events

        def stop(self):
            self.events.append("worker")

    def __init__(self, events):
        self.task_state = self._TaskState()
        self.tasks = self._Tasks(events)


class _LifecycleFocus:
    def __init__(self, events):
        self.events = events

    def wake_all_for_stop(self):
        self.events.append("modal")


class _LifecycleTelemetry:
    def __init__(self, events):
        self.events = events

    def flush_and_close_limited(self):
        self.events.append("telemetry")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["success", "failed", "exception"])
async def test_elevation_always_finishes_old_instance(
    isolated_main, monkeypatch, status
):
    events = []
    isolated_main.app_state.worker = _LifecycleWorker(events)
    isolated_main.app_state.focus_interactions = _LifecycleFocus(events)
    isolated_main.app_state.telemetry_service = _LifecycleTelemetry(events)
    monkeypatch.setattr(privilege_service, "is_elevated", lambda: False)

    def submit_launcher(_root):
        events.append("launcher")
        if status == "exception":
            raise OSError("launcher unavailable")
        return privilege_service.ElevationResult(status, "启动器提交结果")

    monkeypatch.setattr(privilege_service, "request_elevation", submit_launcher)
    monkeypatch.setattr(isolated_main.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        isolated_main.os,
        "kill",
        lambda _pid, _signal: events.append("exit"),
    )

    class ImmediateThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        isolated_main, "threading", SimpleNamespace(Thread=ImmediateThread)
    )

    if status == "exception":
        with pytest.raises(OSError, match="launcher unavailable"):
            await isolated_main.restart_elevated()
    else:
        result = await isolated_main.restart_elevated()
        assert result["status"] == status
    assert events == ["worker", "modal", "telemetry", "launcher", "exit"]
