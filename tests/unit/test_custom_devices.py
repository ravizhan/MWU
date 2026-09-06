"""Tests for custom device persistence and scan+custom merge in DeviceService."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from maa.toolkit import Toolkit
from pydantic import ValidationError

from app_state import WorkerContext
from maa_worker.device_service import (
    DeviceService,
    custom_record_to_device,
    is_controller_supported,
)
from models.api import CustomDeviceCreate
from models.device_address import (
    LinuxDeviceAddress,
    canonicalize_custom_device_address,
)


def _controller(name: str, type_: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        type=type_,
        label=name,
        win32=None,
        gamepad=None,
        macos=None,
        linux=None,
    )


def _connectable_controller(name: str, type_: str) -> SimpleNamespace:
    """Controller with display fields defaulting to 720/None/False."""
    controller = _controller(name, type_)
    controller.display_short_side = 720
    controller.display_long_side = None
    controller.display_raw = False
    controller.model_fields_set = set()
    return controller


def _make_worker(
    app_root: Path,
    controller,
    *,
    tasker_bind: Any = True,
):
    worker = _FakeWorker(app_root, [controller])  # type: ignore[arg-type]
    worker.device_state = SimpleNamespace(
        configuration_locked=False,
        connected=False,
        controller=None,
        controller_name=None,
        controller_type=None,
        current_resource_name=None,
        last_device_error=None,
        portal_helper=None,
    )
    worker.events = SimpleNamespace(
        send_log=lambda _message: None,
        show_system_notification=lambda _title, _message: None,
    )
    worker.tasker = SimpleNamespace(bind=lambda _resource, _controller: tasker_bind)
    worker.resource = object()
    worker.interface.title = "MWU"
    return worker


class _FakeWorker:
    def __init__(self, base_dir: Path, controllers: list[Any] | None = None):
        self.context = WorkerContext(interface_base_dir=base_dir)
        self.interface = SimpleNamespace(
            controller=controllers
            or [
                _controller("AdbController", "Adb"),
                _controller("Win32Controller", "Win32"),
                _controller("GamepadController", "Gamepad"),
                _controller("PlayCoverController", "PlayCover"),
            ]
        )


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    return root


@pytest.fixture
def service(app_root: Path) -> DeviceService:
    return DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]


class TestCustomDeviceCreateModel:
    def test_trims_fields(self):
        payload = CustomDeviceCreate(
            controller_name="  AdbController  ",
            type="Adb",
            address="  127.0.0.1:5555  ",
        )
        assert payload.controller_name == "AdbController"
        assert payload.address == "127.0.0.1:5555"

    def test_rejects_empty_address(self):
        with pytest.raises(ValidationError):
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="   ",
            )

    def test_rejects_empty_controller_name(self):
        with pytest.raises(ValidationError):
            CustomDeviceCreate(controller_name="", type="Adb", address="1.2.3.4:5555")


class TestCanonicalizeCustomAddress:
    def test_adb_and_playcover_trim(self):
        assert (
            canonicalize_custom_device_address("Adb", "  1.2.3.4:5555  ")
            == "1.2.3.4:5555"
        )
        assert (
            canonicalize_custom_device_address("PlayCover", " 127.0.0.1:1717 ")
            == "127.0.0.1:1717"
        )

    def test_adb_empty_rejected(self):
        with pytest.raises(ValueError):
            canonicalize_custom_device_address("Adb", "  ")

    def test_win32_positive_decimal_canonical(self):
        assert canonicalize_custom_device_address("Win32", "00123") == "123"
        assert canonicalize_custom_device_address("Win32", " 42 ") == "42"

    def test_win32_zero_negative_malformed_rejected(self):
        for bad in ("0", "-1", "abc", "12.3", "1e2", ""):
            with pytest.raises(ValueError):
                canonicalize_custom_device_address("Win32", bad)

    def test_gamepad_positive_hwnd_type_0_or_1(self):
        assert canonicalize_custom_device_address("Gamepad", "0042|01") == "42|1"
        assert canonicalize_custom_device_address("Gamepad", " 7 | 0 ") == "7|0"

    def test_gamepad_windowless_zero_allowed(self):
        # hWnd=0 表示无窗口手柄（未配置窗口过滤时允许）
        assert canonicalize_custom_device_address("Gamepad", "0|0") == "0|0"

    def test_gamepad_malformed_negative_rejected(self):
        for bad in (
            "-1|0",
            "42|2",
            "42|-1",
            "42",
            "42|0|1",
            "abc|0",
            "42|x",
            "",
        ):
            with pytest.raises(ValueError):
                canonicalize_custom_device_address("Gamepad", bad)

    def test_macos_positive_decimal_canonical(self):
        assert canonicalize_custom_device_address("MacOS", " 0042 ") == "42"

    def test_macos_non_positive_rejected(self):
        for bad in ("0", "-1", "abc", "1.5", ""):
            with pytest.raises(ValueError):
                canonicalize_custom_device_address("MacOS", bad)

    def test_linux_json_round_trip_canonical(self):
        raw = (
            '{ "wlr_socket_path": " /run/user/1000/wayland-1 ",'
            ' "kind": "wlr", "extra": 1 }'
        )
        with pytest.raises(ValueError):
            canonicalize_custom_device_address("Linux", raw)

        canonical = canonicalize_custom_device_address(
            "Linux",
            '{"wlr_socket_path": "/run/user/1000/wayland-1", "kind": "wlr"}',
        )
        assert (
            canonical
            == '{"kind": "wlr", "wlr_socket_path": "/run/user/1000/wayland-1"}'
        )

    def test_linux_invalid_json_rejected(self):
        for bad in ("not json", "", "[]", "42"):
            with pytest.raises(ValueError):
                canonicalize_custom_device_address("Linux", bad)


class TestCustomRecordToDevice:
    def test_adb_shape(self):
        device = custom_record_to_device(
            {
                "controller_name": "AdbController",
                "type": "Adb",
                "address": "10.0.0.1:5555",
            }
        )
        assert device == {
            "name": "",
            "type": "Adb",
            "adb_path": "",
            "address": "10.0.0.1:5555",
            "screencap_methods": 0,
            "input_methods": 0,
            "config": {},
        }

    def test_win32_parses_hwnd(self):
        device = custom_record_to_device(
            {"controller_name": "Win32Controller", "type": "Win32", "address": "123456"}
        )
        assert device["hWnd"] == 123456
        assert device["class_name"] == ""
        assert device["window_name"] == ""

    def test_gamepad_parses_hwnd_and_type(self):
        device = custom_record_to_device(
            {
                "controller_name": "GamepadController",
                "type": "Gamepad",
                "address": "42|1",
            }
        )
        assert device["hWnd"] == 42
        assert device["gamepad_type"] == 1

    def test_playcover_address(self):
        device = custom_record_to_device(
            {
                "controller_name": "PlayCoverController",
                "type": "PlayCover",
                "address": "127.0.0.1:1717",
            }
        )
        assert device == {"type": "PlayCover", "address": "127.0.0.1:1717"}

    def test_macos_address(self):
        device = custom_record_to_device(
            {
                "controller_name": "MacOSController",
                "type": "MacOS",
                "address": "1234",
            }
        )
        assert device == {
            "type": "MacOS",
            "name": "1234",
            "address": "1234",
            "screencap_methods": 1,
            "input_methods": 1,
        }


class _FakeControllerHandle:
    connected = True

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    def post_connection():
        return SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True))

    # display-target setters（测试通过 connect 路径被调用）
    def set_screenshot_target_short_side(self, _value: int) -> bool:
        return True

    def set_screenshot_target_long_side(self, _value: int) -> bool:
        return True

    def set_screenshot_use_raw_size(self, _value: bool) -> bool:
        return True


class _FakeSdkMacOSController(_FakeControllerHandle):
    def __init__(self, window_id: int, screencap_method: int, input_method: int):
        super().__init__()
        self.window_id = window_id
        self.screencap_method = screencap_method
        self.input_method = input_method


class TestLinuxSupport:
    def test_platform_capability(self):
        controller = _controller("LinuxController", "Linux")
        with patch("maa_worker.device_service.sys.platform", "linux"):
            assert is_controller_supported(controller) == (True, "")
        with patch("maa_worker.device_service.sys.platform", "win32"):
            assert is_controller_supported(controller) == (
                False,
                "platform_not_supported",
            )

    def test_scans_wlr_socket_paths(self, app_root: Path):
        controller = _connectable_controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="Wlr",
            input="Wlr",
            pipewire_source="Gamescope",
            use_win32_vk_code=False,
        )
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]
        scanned = [
            SimpleNamespace(
                class_name="/run/user/1000/wayland-1",
                window_name="Wayland compositor",
            ),
            SimpleNamespace(
                class_name="/run/user/1000/wayland-1",
                window_name="duplicate",
            ),
        ]

        with (
            patch("maa_worker.device_service.sys.platform", "linux"),
            patch.object(Toolkit, "find_desktop_windows", return_value=scanned),
        ):
            devices = service._find_devices_for_controller(controller)

        assert devices == [
            {
                "type": "Linux",
                "name": "Wayland compositor",
                "address": '{"kind": "wlr", "wlr_socket_path": "/run/user/1000/wayland-1"}',
            }
        ]

    def test_scans_gamescope_instances(self, app_root: Path):
        controller = _connectable_controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="Wlr",
            pipewire_source="Gamescope",
            use_win32_vk_code=False,
        )
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]
        instances = [
            SimpleNamespace(display_no=0, pipewire_node_id=12, eis_socket_path=""),
            SimpleNamespace(display_no=1, pipewire_node_id=0, eis_socket_path="x"),
        ]

        with (
            patch("maa_worker.device_service.sys.platform", "linux"),
            patch.object(Toolkit, "find_gamescope_instances", return_value=instances),
        ):
            devices = service._find_devices_for_controller(controller)

        assert devices == [
            {
                "type": "Linux",
                "name": "gamescope-0",
                "address": '{"display_no": 0, "kind": "gamescope"}',
            },
            {
                "type": "Linux",
                "name": "gamescope-1",
                "address": '{"display_no": 1, "kind": "gamescope"}',
            },
        ]

    def test_portal_single_candidate(self, app_root: Path):
        controller = _connectable_controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="Libei",
            pipewire_source="Portal",
            use_win32_vk_code=False,
        )
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]

        with patch("maa_worker.device_service.sys.platform", "linux"):
            devices = service._find_devices_for_controller(controller)

        assert devices == [
            {
                "type": "Linux",
                "name": "通过系统选择屏幕",
                "address": '{"kind": "portal"}',
            }
        ]

    def test_builds_linux_device_model(self):
        address = LinuxDeviceAddress(
            kind="wlr", wlr_socket_path="/run/user/1000/wayland-1"
        ).to_compact_json()
        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            address,
        )

        assert model.type == "Linux"
        assert model.address == address

    def test_connect_wlr_passes_config(self, app_root: Path):
        captured: dict[str, Any] = {}

        class _FakeLinuxController(_FakeControllerHandle):
            def __init__(self, config):
                captured["config"] = config

            def post_connection(self):
                return SimpleNamespace(
                    wait=lambda: SimpleNamespace(succeeded=True),
                )

        controller = _connectable_controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="Wlr",
            input="Wlr",
            pipewire_source="Gamescope",
            use_win32_vk_code=True,
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            LinuxDeviceAddress(
                kind="wlr", wlr_socket_path="/run/user/1000/wayland-1"
            ).to_compact_json(),
        )
        with (
            patch("maa_worker.device_service.LinuxController", _FakeLinuxController),
            patch("maa_worker.device_service.time.sleep"),
            patch.object(worker.tasker, "bind", return_value=True) as bind,
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured["config"] == {
            "screencap_method": 1,
            "input_method": 1,
            "wlr_socket_path": "/run/user/1000/wayland-1",
            "use_win32_vk_code": True,
        }
        bind.assert_called_once()

    def test_connect_gamescope_resolves_instance_per_connect(self, app_root: Path):
        captured: dict[str, Any] = {}

        class _FakeLinuxController(_FakeControllerHandle):
            def __init__(self, config):
                captured["config"] = config

        controller = _connectable_controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="Libei",
            pipewire_source="Gamescope",
            use_win32_vk_code=False,
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            LinuxDeviceAddress(kind="gamescope", display_no=0).to_compact_json(),
        )
        instance = SimpleNamespace(
            display_no=0,
            pipewire_node_id=77,
            eis_socket_path="/run/user/1000/gamescope-0-ei",
        )
        with (
            patch("maa_worker.device_service.LinuxController", _FakeLinuxController),
            patch("maa_worker.device_service.time.sleep"),
            patch.object(Toolkit, "find_gamescope_instances", return_value=[instance]),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured["config"] == {
            "screencap_method": 4,
            "input_method": 4,
            "pw_node_id": 77,
            "eis_socket_path": "/run/user/1000/gamescope-0-ei",
            "use_win32_vk_code": False,
        }

    def test_connect_gamescope_missing_instance_fails(self, app_root: Path):
        controller = _connectable_controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="Wlr",
            pipewire_source="Gamescope",
            use_win32_vk_code=False,
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            LinuxDeviceAddress(kind="gamescope", display_no=9).to_compact_json(),
        )
        with (
            patch("maa_worker.device_service.time.sleep"),
            patch.object(Toolkit, "find_gamescope_instances", return_value=[]),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is False
        assert worker.device_state.last_device_error == "linux_device_unavailable"

    def test_connect_portal_user_cancel_fails_without_fallback(self, app_root: Path):
        controller = _connectable_controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="Wlr",
            pipewire_source="Portal",
            use_win32_vk_code=False,
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            LinuxDeviceAddress(kind="portal").to_compact_json(),
        )
        helper = SimpleNamespace(
            open_stream=lambda: False,
        )
        with (
            patch("maa_worker.device_service.time.sleep"),
            patch.object(Toolkit, "portal_helper_create", return_value=helper),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is False
        assert worker.device_state.last_device_error == "linux_portal_cancelled"
        assert worker.device_state.portal_helper is None

    def test_connect_portal_injects_fd_and_node(self, app_root: Path):
        captured: dict[str, Any] = {}

        class _FakeLinuxController(_FakeControllerHandle):
            def __init__(self, config):
                captured["config"] = config

        controller = _connectable_controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="Wlr",
            pipewire_source="Portal",
            use_win32_vk_code=False,
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            LinuxDeviceAddress(kind="portal").to_compact_json(),
        )
        helper = SimpleNamespace(
            open_stream=lambda: True,
            get_pipewire_fd=lambda: 12,
            get_pipewire_node_id=lambda: 99,
        )
        with (
            patch("maa_worker.device_service.LinuxController", _FakeLinuxController),
            patch("maa_worker.device_service.time.sleep"),
            patch.object(Toolkit, "portal_helper_create", return_value=helper),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured["config"] == {
            "screencap_method": 4,
            "input_method": 1,
            "pw_socket_fd": 12,
            "pw_node_id": 99,
            "use_win32_vk_code": False,
        }
        # PortalHelper 保留在运行态，供 reset/shutdown 释放
        assert worker.device_state.portal_helper is helper

    def test_reset_releases_portal_helper(self, app_root: Path):
        controller = _connectable_controller("LinuxController", "Linux")
        worker = _make_worker(app_root, controller)
        worker.device_state.portal_helper = object()
        worker.device_state.controller = object()
        worker.device_state.connected = True
        worker.sinks = SimpleNamespace(
            unregister_controller_sink=lambda _controller: None,
        )
        DeviceService(worker).reset_connection_state()  # type: ignore[arg-type]
        assert worker.device_state.portal_helper is None
        assert worker.device_state.controller is None


class TestMacOSSupport:
    def test_platform_capability(self):
        controller = _controller("MacOSController", "MacOS")
        controller.macos = SimpleNamespace(title_regex=None, input=None)
        with patch("maa_worker.device_service.sys.platform", "darwin"):
            assert is_controller_supported(controller) == (True, "")
        with patch("maa_worker.device_service.sys.platform", "win32"):
            assert is_controller_supported(controller) == (
                False,
                "platform_not_supported",
            )

    def test_macos_missing_config_unsupported_on_darwin(self):
        controller = _controller("MacOSController", "MacOS")
        with patch("maa_worker.device_service.sys.platform", "darwin"):
            assert is_controller_supported(controller) == (
                False,
                "controller_config_missing",
            )

    def test_scans_cg_window_ids_by_title_regex(self, app_root: Path):
        controller = _connectable_controller("MacOSController", "MacOS")
        controller.macos = SimpleNamespace(
            title_regex=None, input=None, screencap="ScreenCaptureKit"
        )
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]
        scanned = [
            SimpleNamespace(hwnd=1001, class_name="", window_name="My Game"),
            SimpleNamespace(hwnd=1001, class_name="", window_name="duplicate"),
            SimpleNamespace(hwnd=1002, class_name="", window_name="Other App"),
        ]
        with (
            patch("maa_worker.device_service.sys.platform", "darwin"),
            patch.object(Toolkit, "find_desktop_windows", return_value=scanned),
        ):
            devices = service._find_devices_for_controller(controller)

        assert devices == [
            {
                "type": "MacOS",
                "name": "My Game",
                "address": "1001",
                "screencap_methods": 1,
                "input_methods": 1,
            },
            {
                "type": "MacOS",
                "name": "Other App",
                "address": "1002",
                "screencap_methods": 1,
                "input_methods": 1,
            },
        ]

    def test_builds_macos_device_model(self):
        model = DeviceService.build_device_model_from_config(
            "MacOSController", "MacOS", "1234"
        )
        assert model.type == "MacOS"
        assert model.address == "1234"

    def test_connect_permission_granted_passes_methods(self, app_root: Path):
        controller = _connectable_controller("MacOSController", "MacOS")
        controller.macos = SimpleNamespace(
            title_regex=None, input="PostToPid", screencap="ScreenCaptureKit"
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "MacOSController", "MacOS", "4321"
        )
        captured: dict[str, Any] = {}

        class _RecordingSdkMacOSController(_FakeSdkMacOSController):
            def __init__(self, window_id, screencap_method, input_method):
                super().__init__(window_id, screencap_method, input_method)
                captured.update(
                    window_id=window_id,
                    screencap_method=screencap_method,
                    input_method=input_method,
                )

        with (
            patch(
                "maa_worker.device_service.SdkMacOSController",
                _RecordingSdkMacOSController,
            ),
            patch("maa_worker.device_service.time.sleep"),
            patch.object(
                Toolkit,
                "macos_check_permission",
                return_value=True,
            ),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured == {
            "window_id": 4321,
            "screencap_method": 1,
            "input_method": 2,  # PostToPid
        }

    def test_connect_denied_permission_opens_settings_and_fails(self, app_root: Path):
        controller = _connectable_controller("MacOSController", "MacOS")
        controller.macos = SimpleNamespace(
            title_regex=None, input="GlobalEvent", screencap="ScreenCaptureKit"
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "MacOSController", "MacOS", "4321"
        )
        calls: list[str] = []

        def check(_perm):
            return False

        def request(perm):
            calls.append(f"request:{int(perm)}")
            return True

        def reveal(perm):
            calls.append(f"reveal:{int(perm)}")

        with (
            patch("maa_worker.device_service.time.sleep"),
            patch.object(Toolkit, "macos_check_permission", side_effect=check),
            patch.object(Toolkit, "macos_request_permission", side_effect=request),
            patch.object(
                Toolkit, "macos_reveal_permission_settings", side_effect=reveal
            ),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is False
        assert worker.device_state.last_device_error == "macos_permission_required"
        assert "request:1" in calls
        assert "reveal:1" in calls


class TestGamepadWindowlessSupport:
    def test_windowless_candidate_when_no_filter(self, app_root: Path):
        controller = _connectable_controller("GamepadController", "Gamepad")
        controller.gamepad = SimpleNamespace(
            class_regex=None,
            window_regex=None,
            screencap=None,
            gamepad_type=None,
        )
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]
        with (
            patch("maa_worker.device_service.sys.platform", "win32"),
            patch.object(Toolkit, "find_desktop_windows", return_value=[]),
        ):
            devices = service._find_devices_for_controller(controller)

        assert devices == [
            {
                "type": "Gamepad",
                "hWnd": 0,
                "class_name": "",
                "window_name": "",
                "screencap_methods": 2,
                "gamepad_type": 0,
            }
        ]

    def test_connect_passes_none_hwnd(self, app_root: Path):
        captured: dict[str, Any] = {}

        class _FakeGamepadController(_FakeControllerHandle):
            def __init__(self, hWnd, gamepad_type, screencap_method):
                captured.update(
                    hWnd=hWnd,
                    gamepad_type=gamepad_type,
                    screencap_method=screencap_method,
                )

        controller = _connectable_controller("GamepadController", "Gamepad")
        controller.gamepad = SimpleNamespace(
            class_regex=None, window_regex=None, screencap=None, gamepad_type=None
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "GamepadController",
            "Gamepad",
            "0|0",
        )
        with (
            patch(
                "maa_worker.device_service.GamepadController", _FakeGamepadController
            ),
            patch("maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured["hWnd"] is None
        assert captured["gamepad_type"] == 0


class TestCustomDevicePersistence:
    def test_persists_across_service_instances(self, app_root: Path):
        svc1 = DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]
        payload = CustomDeviceCreate(
            controller_name="AdbController",
            type="Adb",
            address="192.168.1.10:5555",
        )
        saved = svc1.add_custom_device(payload)
        assert saved["address"] == "192.168.1.10:5555"

        path = app_root / "config" / "settings.json"
        assert path.exists()

        svc2 = DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]
        records = svc2._load_custom_devices()
        assert records == [
            {
                "controller_name": "AdbController",
                "type": "Adb",
                "address": "192.168.1.10:5555",
            }
        ]

    def test_dedupes_by_identity(self, service: DeviceService):
        payload = CustomDeviceCreate(
            controller_name="AdbController",
            type="Adb",
            address="  10.0.0.2:5555  ",
        )
        service.add_custom_device(payload)
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="10.0.0.2:5555",
            )
        )
        assert len(service._load_custom_devices()) == 1

    def test_win32_canonical_dedup(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="Win32Controller",
                type="Win32",
                address="00100",
            )
        )
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="Win32Controller",
                type="Win32",
                address="100",
            )
        )
        records = service._load_custom_devices()
        assert len(records) == 1
        assert records[0]["address"] == "100"

    def test_gamepad_canonical_dedup(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="GamepadController",
                type="Gamepad",
                address="008|01",
            )
        )
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="GamepadController",
                type="Gamepad",
                address="8|1",
            )
        )
        records = service._load_custom_devices()
        assert len(records) == 1
        assert records[0]["address"] == "8|1"

    def test_macos_canonical_dedup(self, app_root: Path):
        controller = _controller("MacOSController", "MacOS")
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="MacOSController",
                type="MacOS",
                address="0042",
            )
        )
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="MacOSController",
                type="MacOS",
                address="42",
            )
        )
        records = service._load_custom_devices()
        assert len(records) == 1
        assert records[0]["address"] == "42"

    def test_rejects_zero_win32(self, service: DeviceService):
        with pytest.raises(ValueError, match="positive integer"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="Win32Controller",
                    type="Win32",
                    address="0",
                )
            )

    def test_rejects_malformed_gamepad(self, service: DeviceService):
        with pytest.raises(ValueError):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="GamepadController",
                    type="Gamepad",
                    address="42|9",
                )
            )

    def test_rejects_unknown_controller(self, service: DeviceService):
        with pytest.raises(ValueError, match="未找到匹配的控制器配置"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="Missing",
                    type="Adb",
                    address="1.1.1.1:5555",
                )
            )

    def test_rejects_type_mismatch(self, service: DeviceService):
        with pytest.raises(ValueError, match="控制器类型不匹配"):
            service.add_custom_device(
                CustomDeviceCreate(
                    controller_name="AdbController",
                    type="Win32",
                    address="12345",
                )
            )

    def _write_settings(
        self,
        app_root: Path,
        custom_devices: list[dict[str, object]] | None = None,
    ) -> Path:
        """Write a minimal settings.json with optional customDevices."""
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {"panel": {}}
        if custom_devices is not None:
            data["panel"] = {"customDevices": custom_devices}  # type: ignore[dict-item]
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_empty_file_tolerated(self, service: DeviceService, app_root: Path):
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        assert service._load_custom_devices() == []

    def test_corrupt_file_tolerated(self, service: DeviceService, app_root: Path):
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        assert service._load_custom_devices() == []

    def test_non_list_file_tolerated(self, service: DeviceService, app_root: Path):
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"oops": true}', encoding="utf-8")
        assert service._load_custom_devices() == []

    def test_legacy_adb_serial_preserved(self, service: DeviceService, app_root: Path):
        """Persisted Adb serial records (e.g. emulator-5554) must survive loading."""
        self._write_settings(
            app_root,
            [
                {
                    "controller_name": "AdbController",
                    "type": "Adb",
                    "address": "emulator-5554",
                },
                {
                    "controller_name": "AdbController",
                    "type": "Adb",
                    "address": "192.168.1.1:5555",
                },
            ],
        )
        records = service._load_custom_devices()
        assert len(records) == 2
        addresses = {r["address"] for r in records}
        assert "emulator-5554" in addresses
        assert "192.168.1.1:5555" in addresses

    def test_skips_invalid_loaded_entries(self, service: DeviceService, app_root: Path):
        self._write_settings(
            app_root,
            [
                {
                    "controller_name": "Win32Controller",
                    "type": "Win32",
                    "address": "0",
                },
                {
                    "controller_name": "Win32Controller",
                    "type": "Win32",
                    "address": "-5",
                },
                {
                    "controller_name": "GamepadController",
                    "type": "Gamepad",
                    "address": "1|9",
                },
                {
                    "controller_name": "AdbController",
                    "type": "Adb",
                    "address": "10.0.0.9:5555",
                },
                {
                    "controller_name": "Win32Controller",
                    "type": "Win32",
                    "address": "00123",
                },
            ],
        )
        records = service._load_custom_devices()
        assert records == [
            {
                "controller_name": "AdbController",
                "type": "Adb",
                "address": "10.0.0.9:5555",
            },
            {
                "controller_name": "Win32Controller",
                "type": "Win32",
                "address": "123",
            },
        ]

    def test_path_uses_interface_base_dir_not_cwd(
        self, app_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        other_cwd = tmp_path / "other_cwd"
        other_cwd.mkdir()
        monkeypatch.chdir(other_cwd)

        svc = DeviceService(_FakeWorker(app_root))  # type: ignore[arg-type]
        svc.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="8.8.8.8:5555",
            )
        )
        assert (app_root / "config" / "settings.json").exists()
        assert not (other_cwd / "config" / "settings.json").exists()

    def test_atomic_save_no_temp_left(self, service: DeviceService, app_root: Path):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="1.1.1.1:5555",
            )
        )
        config_dir = app_root / "config"
        assert (config_dir / "settings.json").exists()
        temps = list(config_dir.glob(".settings.json.*.tmp"))
        assert temps == []

    def test_concurrent_adds_dedupe_and_valid_json(
        self, service: DeviceService, app_root: Path
    ):
        def add_one(i: int) -> None:
            # Even indices share one canonical Win32 address; odds unique Adb.
            if i % 2 == 0:
                service.add_custom_device(
                    CustomDeviceCreate(
                        controller_name="Win32Controller",
                        type="Win32",
                        address=f"00{100 + (i % 4)}",
                    )
                )
            else:
                service.add_custom_device(
                    CustomDeviceCreate(
                        controller_name="AdbController",
                        type="Adb",
                        address=f"10.0.0.{i}:5555",
                    )
                )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add_one, range(20)))

        path = app_root / "config" / "settings.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        custom_list = data.get("panel", {}).get("customDevices", [])
        assert isinstance(custom_list, list)
        # File must always be valid complete JSON (atomic replace).
        records = service._load_custom_devices()
        identities = {(r["controller_name"], r["type"], r["address"]) for r in records}
        assert len(identities) == len(records)

        # Concurrent readers never see truncated content.
        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(30):
                    loaded = service._load_custom_devices()
                    assert isinstance(loaded, list)
            except Exception as exc:  # pragma: no cover - fail collection
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="9.9.9.9:5555",
            )
        )
        for t in threads:
            t.join()
        assert errors == []


class TestScanCustomMerge:
    def test_merge_appends_custom_only(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="10.0.0.5:5555",
            )
        )
        scanned = [
            {
                "name": "Phone",
                "type": "Adb",
                "adb_path": "/usr/bin/adb",
                "address": "10.0.0.1:5555",
                "screencap_methods": "1",
                "input_methods": "2",
                "config": {"k": "v"},
            }
        ]
        merged = service._merge_custom_devices("AdbController", scanned)
        assert len(merged) == 2
        assert merged[0]["address"] == "10.0.0.1:5555"
        assert merged[1]["address"] == "10.0.0.5:5555"
        assert merged[1]["name"] == ""
        assert merged[1]["adb_path"] == ""

    def test_scan_wins_on_duplicate_identity(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="10.0.0.1:5555",
            )
        )
        scanned = [
            {
                "name": "RichScan",
                "type": "Adb",
                "adb_path": "C:/adb.exe",
                "address": "10.0.0.1:5555",
                "screencap_methods": "99",
                "input_methods": "88",
                "config": {"from": "scan"},
            }
        ]
        merged = service._merge_custom_devices("AdbController", scanned)
        assert len(merged) == 1
        assert merged[0]["name"] == "RichScan"
        assert merged[0]["adb_path"] == "C:/adb.exe"
        assert merged[0]["screencap_methods"] == "99"
        assert merged[0]["config"] == {"from": "scan"}

    def test_win32_scan_wins_canonical(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="Win32Controller",
                type="Win32",
                address="00100",
            )
        )
        scanned = [
            {
                "type": "Win32",
                "hWnd": 100,
                "class_name": "Chrome",
                "window_name": "Browser",
                "screencap_methods": 1,
                "input_methods": 1,
            }
        ]
        merged = service._merge_custom_devices("Win32Controller", scanned)
        assert len(merged) == 1
        assert merged[0]["class_name"] == "Chrome"

    def test_get_device_scan_then_merge(self, service: DeviceService):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name="AdbController",
                type="Adb",
                address="10.99.99.1:5555",
            )
        )
        scanned = [
            {
                "name": "Emulator",
                "type": "Adb",
                "adb_path": "adb",
                "address": "127.0.0.1:5555",
                "screencap_methods": "1",
                "input_methods": "1",
                "config": {},
            }
        ]
        with patch.object(
            DeviceService, "_find_devices_for_controller", return_value=scanned
        ):
            data = service.get_device("AdbController")

        addresses = [d.get("address") for d in data["devices"]]
        assert "127.0.0.1:5555" in addresses
        assert "10.99.99.1:5555" in addresses
        assert data["selected_controller"] == "AdbController"


class TestConnectDisplayTargets:
    def test_default_short_720_when_nothing_set(self, app_root: Path):
        controller = _connectable_controller("AdbController", "Adb")
        controller.model_fields_set = set()
        model = DeviceService.build_device_model_from_config(
            "AdbController", "Adb", "127.0.0.1:5555"
        )
        calls: list[tuple[str, int | bool]] = []

        class _Recorder(_FakeControllerHandle):
            def set_screenshot_target_short_side(self, _value: int) -> bool:
                calls.append(("short", _value))
                return True

            def set_screenshot_target_long_side(self, _value: int) -> bool:
                calls.append(("long", _value))
                return True

            def set_screenshot_use_raw_size(self, _value: bool) -> bool:
                calls.append(("raw", _value))
                return True

        worker = _make_worker(app_root, controller)
        with (
            patch("maa_worker.device_service.AdbController", return_value=_Recorder()),
            patch("maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]
        assert connected is True
        assert calls == [("short", 720)]

    def test_explicit_short_720_counts_as_provided(self, app_root: Path):
        controller = _connectable_controller("AdbController", "Adb")
        controller.model_fields_set = {"display_short_side"}
        model = DeviceService.build_device_model_from_config(
            "AdbController", "Adb", "127.0.0.1:5555"
        )
        calls: list[tuple[str, int | bool]] = []

        class _Recorder(_FakeControllerHandle):
            def set_screenshot_target_short_side(self, _value: int) -> bool:
                calls.append(("short", _value))
                return True

        worker = _make_worker(app_root, controller)
        with (
            patch("maa_worker.device_service.AdbController", return_value=_Recorder()),
            patch("maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]
        assert connected is True
        assert calls == [("short", 720)]

    def test_long_side_uses_long_setter(self, app_root: Path):
        controller = _connectable_controller("AdbController", "Adb")
        controller.model_fields_set = {"display_long_side"}
        controller.display_long_side = 1920
        model = DeviceService.build_device_model_from_config(
            "AdbController", "Adb", "127.0.0.1:5555"
        )
        calls: list[tuple[str, int | bool]] = []

        class _Recorder(_FakeControllerHandle):
            def set_screenshot_target_long_side(self, _value: int) -> bool:
                calls.append(("long", _value))
                return True

        worker = _make_worker(app_root, controller)
        with (
            patch("maa_worker.device_service.AdbController", return_value=_Recorder()),
            patch("maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]
        assert connected is True
        assert calls == [("long", 1920)]

    def test_raw_uses_raw_setter(self, app_root: Path):
        controller = _connectable_controller("AdbController", "Adb")
        controller.model_fields_set = {"display_raw"}
        controller.display_raw = True
        model = DeviceService.build_device_model_from_config(
            "AdbController", "Adb", "127.0.0.1:5555"
        )
        calls: list[tuple[str, int | bool]] = []

        class _Recorder(_FakeControllerHandle):
            def set_screenshot_use_raw_size(self, _value: bool) -> bool:
                calls.append(("raw", _value))
                return True

        worker = _make_worker(app_root, controller)
        with (
            patch("maa_worker.device_service.AdbController", return_value=_Recorder()),
            patch("maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]
        assert connected is True
        assert calls == [("raw", True)]

    def test_sdk_setter_failure_fails_connect(self, app_root: Path):
        controller = _connectable_controller("AdbController", "Adb")
        controller.model_fields_set = {"display_raw"}
        controller.display_raw = True
        model = DeviceService.build_device_model_from_config(
            "AdbController", "Adb", "127.0.0.1:5555"
        )

        class _Failing(_FakeControllerHandle):
            def set_screenshot_use_raw_size(self, _value: bool) -> bool:
                return False

        worker = _make_worker(app_root, controller)
        with (
            patch("maa_worker.device_service.AdbController", return_value=_Failing()),
            patch("maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]
        assert connected is False
        assert "失败" in (worker.device_state.last_device_error or "")


class TestWin32MouseKeyboardSeparation:
    def test_connect_passes_separate_mouse_keyboard(self, app_root: Path):
        captured: dict[str, Any] = {}

        class _FakeWin32Controller(_FakeControllerHandle):
            def __init__(self, hWnd, screencap_method, mouse_method, keyboard_method):
                captured.update(
                    hWnd=hWnd,
                    screencap_method=screencap_method,
                    mouse_method=mouse_method,
                    keyboard_method=keyboard_method,
                )

        controller = _connectable_controller("Win32Controller", "Win32")
        controller.win32 = SimpleNamespace(
            screencap=1, mouse=64, keyboard=8, class_regex=None, window_regex=None
        )
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "Win32Controller", "Win32", "123456"
        )
        with (
            patch("maa_worker.device_service.Win32Controller", _FakeWin32Controller),
            patch("maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured == {
            "hWnd": 123456,
            "screencap_method": 1,
            "mouse_method": 64,
            "keyboard_method": 8,
        }

    def test_missing_win32_object_uses_sdk_defaults(self, app_root: Path):
        captured: dict[str, Any] = {}

        class _FakeWin32Controller(_FakeControllerHandle):
            def __init__(self, hWnd, screencap_method, mouse_method, keyboard_method):
                captured.update(
                    hWnd=hWnd,
                    screencap_method=screencap_method,
                    mouse_method=mouse_method,
                    keyboard_method=keyboard_method,
                )

        controller = _connectable_controller("Win32Controller", "Win32")
        controller.win32 = None
        worker = _make_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "Win32Controller", "Win32", "42"
        )
        with (
            patch("maa_worker.device_service.Win32Controller", _FakeWin32Controller),
            patch("maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured == {
            "hWnd": 42,
            "screencap_method": 18,
            "mouse_method": 1,
            "keyboard_method": 1,
        }


class TestResourceBundleLoading:
    def test_path_resolution_uses_interface_base_dir_and_containment(
        self, app_root: Path
    ):
        resource_dir = app_root / "resource"
        resource_dir.mkdir()
        (resource_dir / "main.bundle").write_text("x", encoding="utf-8")
        controller = _connectable_controller("AdbController", "Adb")
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]

        resolved = service._resource_path("{PROJECT_DIR}/resource/main.bundle")
        assert resolved == (resource_dir / "main.bundle").resolve()

        with pytest.raises(ValueError, match="越界|不允许包含"):
            service._resource_path("{PROJECT_DIR}/../outside.txt")

    def test_set_resource_clear_then_load_then_hash_check_order(self, app_root: Path):
        """切换资源必须先清空旧路径内容，再加载本次 path；
        hash 校验严格保留在所有 path 加载成功后、附加路径之前。"""
        resource_dir = app_root / "resource"
        resource_dir.mkdir()
        (resource_dir / "r1").write_text("x", encoding="utf-8")
        (resource_dir / "r2").write_text("x", encoding="utf-8")

        events: list[str] = []

        class _FakeJob:
            def wait(self):
                return SimpleNamespace(succeeded=True)

        class _FakeResource:
            def __init__(self):
                self.loaded = True
                self._hash = "abc"

            def clear(self):
                events.append("clear")
                return True

            def post_bundle(self, _path):
                events.append(f"load:{_path.name}")
                return _FakeJob()

            @property
            def hash(self):
                events.append("hash-check")
                return self._hash

        controller = _connectable_controller("AdbController", "Adb")
        worker = _make_worker(app_root, controller)
        worker.resource = _FakeResource()
        service = DeviceService(worker)  # type: ignore[arg-type]
        resource_config = SimpleNamespace(
            name="main",
            path=["{PROJECT_DIR}/resource/r1"],
            hash="abc",
        )
        worker.interface.resource = [resource_config]

        ok = service.set_resource("main")
        assert ok is True
        # clear → 主路径加载 → hash 校验 → 附加路径（无）→ 日志
        assert events[0] == "clear"
        assert events[1] == "load:r1"
        assert "hash-check" in events

    def test_hash_mismatch_warns_but_succeeds(self, app_root: Path):
        resource_dir = app_root / "resource"
        resource_dir.mkdir()
        (resource_dir / "r1").write_text("x", encoding="utf-8")
        warnings: list[str] = []

        class _FakeJob:
            def wait(self):
                return SimpleNamespace(succeeded=True)

        class _FakeResource:
            def __init__(self):
                self.loaded = False
                self._hash = "different"

            def clear(self):
                return True

            def post_bundle(self, _path):
                return _FakeJob()

            @property
            def hash(self):
                return self._hash

        controller = _connectable_controller("AdbController", "Adb")
        worker = _make_worker(app_root, controller)
        worker.resource = _FakeResource()
        service = DeviceService(worker)  # type: ignore[arg-type]
        worker.interface.resource = [
            SimpleNamespace(
                name="main",
                path=["{PROJECT_DIR}/resource/r1"],
                hash="expected",
            )
        ]
        worker.events = SimpleNamespace(
            send_log=lambda message: (
                warnings.append(message) if "校验值不匹配" in message else None
            ),
            show_system_notification=lambda _t, _m: None,
        )

        ok = service.set_resource("main")
        assert ok is True
        assert any("校验值不匹配" in w for w in warnings)

    def test_resource_path_without_project_dir_still_resolves(self, app_root: Path):
        resource_dir = app_root / "resource"
        resource_dir.mkdir()
        (resource_dir / "bundle").write_text("x", encoding="utf-8")
        controller = _connectable_controller("AdbController", "Adb")
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]
        resolved = service._resource_path("resource/bundle")
        assert resolved == (resource_dir / "bundle").resolve()
