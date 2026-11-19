"""Tests for custom device persistence and scan+custom merge in DeviceService."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from maa.define import MaaMacOSPermissionEnum
from maa.toolkit import Toolkit
from pydantic import ValidationError

from backend.core.state import WorkerContext
from backend.maa_worker.device_service import (
    _UNSUPPORTED_REASON_TEXT,
    DeviceService,
    custom_record_to_device,
    is_controller_supported,
)
from backend.models.api import CustomDeviceCreate
from backend.models.device_address import canonicalize_custom_device_address


def _controller(name: str, type_: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        type=type_,
        label=name,
        icon=None,
        display_short_side=720,
        display_long_side=None,
        display_expand=None,
        display_raw=False,
        permission_required=False,
        win32=None,
        gamepad=None,
        linux=None,
        macos=None,
    )


class _FakeWorker:
    def __init__(self, base_dir: Path, controllers: list[Any] | None = None):
        self.context = WorkerContext(app_root=base_dir, interface_base_dir=base_dir)
        self.interface = SimpleNamespace(
            controller=controllers
            or [
                _controller("AdbController", "Adb"),
                _controller("Win32Controller", "Win32"),
                _controller("GamepadController", "Gamepad"),
                _controller("PlayCoverController", "PlayCover"),
            ]
        )
        self.text = SimpleNamespace(
            app_name=lambda: "MWU", resolve=lambda v: v, language=lambda: "zh_cn"
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


@pytest.mark.parametrize(
    ("device_type", "raw", "expected"),
    [
        ("Adb", "  1.2.3.4:5555  ", "1.2.3.4:5555"),
        ("PlayCover", " 127.0.0.1:1717 ", "127.0.0.1:1717"),
        ("Linux", " /run/user/1000/wayland-1 ", "/run/user/1000/wayland-1"),
        ("Win32", "00123", "123"),
        ("Win32", " 42 ", "42"),
        ("MacOS", " 0077 ", "77"),
        ("Gamepad", "0042|01", "42|1"),
        ("Gamepad", " 7 | 0 ", "7|0"),
    ],
)
def test_canonicalize_custom_address_accepts(device_type: str, raw: str, expected: str):
    assert canonicalize_custom_device_address(device_type, raw) == expected


@pytest.mark.parametrize(
    ("device_type", "raw"),
    [
        ("Adb", "  "),
        ("Linux", "   "),
        ("Win32", "0"),
        ("Win32", "-1"),
        ("Win32", "abc"),
        ("Win32", "12.3"),
        ("Win32", "1e2"),
        ("Win32", ""),
        ("MacOS", "0"),
        ("MacOS", "abc"),
        ("Gamepad", "0|0"),
        ("Gamepad", "-1|0"),
        ("Gamepad", "42|2"),
        ("Gamepad", "42|-1"),
        ("Gamepad", "42"),
        ("Gamepad", "42|0|1"),
        ("Gamepad", "abc|0"),
        ("Gamepad", "42|x"),
        ("Gamepad", ""),
    ],
)
def test_canonicalize_custom_address_rejects(device_type: str, raw: str):
    with pytest.raises(ValueError):
        canonicalize_custom_device_address(device_type, raw)


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (
            {"type": "Adb", "address": "10.0.0.1:5555"},
            {
                "name": "",
                "type": "Adb",
                "adb_path": "",
                "address": "10.0.0.1:5555",
                "screencap_methods": 0,
                "input_methods": 0,
                "config": {},
            },
        ),
        (
            {"type": "Win32", "address": "123456"},
            {
                "type": "Win32",
                "hWnd": 123456,
                "class_name": "",
                "window_name": "",
                "screencap_methods": 0,
                "input_methods": 0,
            },
        ),
        (
            {"type": "Gamepad", "address": "42|1"},
            {
                "type": "Gamepad",
                "hWnd": 42,
                "class_name": "",
                "window_name": "",
                "screencap_methods": 0,
                "gamepad_type": 1,
            },
        ),
        (
            {"type": "PlayCover", "address": "127.0.0.1:1717"},
            {"type": "PlayCover", "address": "127.0.0.1:1717"},
        ),
        (
            {"type": "Linux", "address": "/run/user/1000/wayland-1"},
            {"type": "Linux", "address": "/run/user/1000/wayland-1"},
        ),
    ],
)
def test_custom_record_to_device(record: dict[str, Any], expected: dict[str, Any]):
    assert custom_record_to_device(record) == expected


def _fake_linux_controller(
    captured: dict[str, Any],
    screenshot_calls: list[tuple[Any, ...]] | None = None,
):
    """替代 maa.controller.LinuxController，捕获构造参数与截图参数。"""

    class _FakeLinuxController:
        connected = True

        def __init__(self, config):
            captured.update(config)

        @staticmethod
        def post_connection():
            return SimpleNamespace(wait=lambda: SimpleNamespace(succeeded=True))

        def set_screenshot_target_expand(self, width: int, height: int) -> None:
            if screenshot_calls is not None:
                screenshot_calls.append(("expand", width, height))

        def set_screenshot_target_short_side(self, short_side: int) -> None:
            pass

    return _FakeLinuxController


class TestLinuxSupport:
    @pytest.fixture(autouse=True)
    def _linux_platform(self):
        with patch("backend.maa_worker.device_service.sys.platform", "linux"):
            yield

    def test_platform_capability(self):
        controller = _controller("LinuxController", "Linux")
        with patch("backend.maa_worker.device_service.sys.platform", "linux"):
            assert is_controller_supported(controller) == (True, "")
        with patch("backend.maa_worker.device_service.sys.platform", "win32"):
            assert is_controller_supported(controller) == (
                False,
                "platform_not_supported",
            )

    def test_scans_wayland_socket_paths(self, app_root: Path):
        controller = _controller("LinuxController", "Linux")
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
            patch("backend.maa_worker.device_service.sys.platform", "linux"),
            patch.object(Toolkit, "find_desktop_windows", return_value=scanned),
        ):
            devices = service._find_devices_for_controller(controller)

        assert devices == [
            {
                "type": "Linux",
                "name": "Wayland compositor",
                "address": "/run/user/1000/wayland-1",
            }
        ]

    def test_scans_gamescope_instances(self, app_root: Path):
        controller = _controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="Libei",
            pipewire_source="Gamescope",
        )
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]
        instances = [
            SimpleNamespace(display_no=1, pipewire_node_id=0, eis_socket_path=""),
            SimpleNamespace(
                display_no=0,
                pipewire_node_id=70,
                eis_socket_path="/run/user/1000/gamescope-0-ei",
            ),
        ]

        with (
            patch("backend.maa_worker.device_service.sys.platform", "linux"),
            patch.object(Toolkit, "find_gamescope_instances", return_value=instances),
        ):
            devices = service._find_devices_for_controller(controller)

        assert devices == [
            {
                "type": "Linux",
                "name": "Gamescope (display 0)",
                "address": "gamescope-0",
            }
        ]

    @staticmethod
    def _linux_worker(app_root: Path, controller: SimpleNamespace):
        worker = _FakeWorker(app_root, [controller])
        worker.device_state = SimpleNamespace(
            configuration_locked=False,
            connected=False,
            controller=None,
            controller_name=None,
            controller_type=None,
            current_resource_name=None,
            last_device_error=None,
        )
        worker.events = SimpleNamespace(
            send_log=lambda _message: None,
        )
        worker.sinks = SimpleNamespace(
            register_controller_sink=lambda _controller: None,
            unregister_controller_sink=lambda _controller: None,
        )
        worker.tasker = SimpleNamespace(bind=lambda _resource, _controller: True)
        worker.resource = object()
        worker.interface.title = "MWU"
        return worker

    def test_connect_uses_socket_path_and_keycode_mode(self, app_root: Path):
        captured: dict[str, Any] = {}
        controller = _controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap=None,
            input=None,
            pipewire_source=None,
            use_win32_vk_code=True,
        )
        worker = self._linux_worker(app_root, controller)

        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            "/run/user/1000/wayland-1",
        )
        with (
            patch(
                "backend.maa_worker.device_service.LinuxController",
                _fake_linux_controller(captured),
            ),
            patch("backend.maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured == {
            "screencap_method": 1,
            "input_method": 1,
            "use_win32_vk_code": True,
            "wlr_socket_path": "/run/user/1000/wayland-1",
        }

    def test_connect_uses_gamescope_pipewire_and_libei(self, app_root: Path):
        captured: dict[str, Any] = {}
        controller = _controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="Libei",
            pipewire_source="Gamescope",
            use_win32_vk_code=False,
        )
        worker = self._linux_worker(app_root, controller)
        instances = [
            SimpleNamespace(
                display_no=0,
                pipewire_node_id=70,
                eis_socket_path="/run/user/1000/gamescope-0-ei",
            ),
        ]

        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            "gamescope-0",
        )
        with (
            patch(
                "backend.maa_worker.device_service.LinuxController",
                _fake_linux_controller(captured),
            ),
            patch.object(Toolkit, "find_gamescope_instances", return_value=instances),
            patch("backend.maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert captured == {
            "screencap_method": 4,
            "input_method": 4,
            "use_win32_vk_code": False,
            "pw_node_id": 70,
            "eis_socket_path": "/run/user/1000/gamescope-0-ei",
        }
        assert "wlr_socket_path" not in captured

    def test_connect_explicit_gamescope_address_never_falls_back(self, app_root: Path):
        controller = _controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input=None,
            pipewire_source="Gamescope",
            use_win32_vk_code=False,
        )
        worker = self._linux_worker(app_root, controller)
        instances = [
            SimpleNamespace(
                display_no=1,
                pipewire_node_id=70,
                eis_socket_path="/run/user/1000/gamescope-1-ei",
            ),
        ]

        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            "gamescope-2",
        )
        with patch.object(Toolkit, "find_gamescope_instances", return_value=instances):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is False
        assert "gamescope" in worker.device_state.last_device_error

    def test_connect_rejects_gamescope_address_with_wlr_input(self, app_root: Path):
        controller = _controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input=None,  # 默认 Wlr
            pipewire_source="Gamescope",
            use_win32_vk_code=False,
        )
        worker = self._linux_worker(app_root, controller)
        instances = [
            SimpleNamespace(
                display_no=0,
                pipewire_node_id=70,
                eis_socket_path="/run/user/1000/gamescope-0-ei",
            ),
        ]

        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            "gamescope-0",
        )
        with patch.object(Toolkit, "find_gamescope_instances", return_value=instances):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is False
        assert "Wlr" in worker.device_state.last_device_error

    def test_connect_applies_display_expand(self, app_root: Path):
        captured: dict[str, Any] = {}
        screenshot_calls: list[tuple[Any, ...]] = []
        controller = _controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap=None,
            input=None,
            pipewire_source=None,
            use_win32_vk_code=False,
        )
        controller.display_expand = (1280, 720)
        worker = self._linux_worker(app_root, controller)

        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            "/run/user/1000/wayland-1",
        )
        with (
            patch(
                "backend.maa_worker.device_service.LinuxController",
                _fake_linux_controller(captured, screenshot_calls),
            ),
            patch("backend.maa_worker.device_service.time.sleep"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is True
        assert screenshot_calls == [("expand", 1280, 720)]

    def test_connect_requires_elevation(self, app_root: Path):
        controller = _controller("LinuxController", "Linux")
        controller.permission_required = True
        worker = self._linux_worker(app_root, controller)

        model = DeviceService.build_device_model_from_config(
            "LinuxController",
            "Linux",
            "/run/user/1000/wayland-1",
        )
        with patch(
            "backend.maa_worker.device_service._is_elevated", return_value=False
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is False
        assert "管理员权限" in worker.device_state.last_device_error

    def test_connect_uinput_uses_saved_screen_size(self, app_root: Path):
        controller = _controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire",
            input="UInput",
            pipewire_source="Gamescope",
            use_win32_vk_code=False,
        )
        worker = self._linux_worker(app_root, controller)
        instances = [
            SimpleNamespace(display_no=0, pipewire_node_id=70, eis_socket_path="")
        ]
        model = DeviceService.build_device_model_from_config(
            "LinuxController", "Linux", "gamescope-0"
        )
        patches = (
            patch(
                "backend.maa_worker.device_service.LinuxController",
                _fake_linux_controller({}),
            ),
            patch.object(Toolkit, "find_gamescope_instances", return_value=instances),
            patch("backend.maa_worker.device_service.time.sleep"),
        )

        with patches[0], patches[1], patches[2]:
            assert DeviceService(worker).connect(model) is False  # type: ignore[arg-type]
        assert "屏幕宽高" in worker.device_state.last_device_error

        settings_path = app_root / "config" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps(
                {"panel": {"uinputScreenWidth": 1920, "uinputScreenHeight": 1080}}
            ),
            encoding="utf-8",
        )
        with patches[0], patches[1], patches[2]:
            assert DeviceService(worker).connect(model) is True  # type: ignore[arg-type]
        assert worker.device_state.connected is True

    @pytest.mark.parametrize(
        ("input_method", "expected"),
        [
            (
                "UInput",
                [{"type": "Linux", "name": "xdg-desktop-portal", "address": "portal"}],
            ),
            # Libei 需要 gamescope EIS socket，Portal 设备无法连接，不应出现在列表中
            ("Libei", []),
        ],
    )
    def test_scans_portal_device_only_for_uinput(
        self, app_root: Path, input_method: str, expected: list[dict[str, str]]
    ):
        controller = _controller("LinuxController", "Linux")
        controller.linux = SimpleNamespace(
            screencap="PipeWire", input=input_method, pipewire_source="Portal"
        )
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]

        devices = service._find_devices_for_controller(controller)

        assert devices == expected


class TestMacOSSupport:
    def test_platform_capability(self):
        controller = _controller("MacController", "MacOS")
        with patch("backend.maa_worker.device_service.sys.platform", "darwin"):
            assert is_controller_supported(controller) == (True, "")
        with patch("backend.maa_worker.device_service.sys.platform", "win32"):
            assert is_controller_supported(controller) == (
                False,
                "platform_not_supported",
            )

    def test_scans_windows_filtered_by_title_regex(self, app_root: Path):
        controller = _controller("MacController", "MacOS")
        controller.macos = SimpleNamespace(title_regex=re.compile("^Game"))
        service = DeviceService(_FakeWorker(app_root, [controller]))  # type: ignore[arg-type]
        windows = [
            SimpleNamespace(hwnd=12, class_name="com.example.game", window_name="Game"),
            SimpleNamespace(hwnd=12, class_name="com.example.game", window_name="Game"),
            SimpleNamespace(hwnd=13, class_name="com.apple.finder", window_name="Docs"),
            SimpleNamespace(
                hwnd=None, class_name="com.example.game", window_name="Game"
            ),
        ]

        with (
            patch("backend.maa_worker.device_service.sys.platform", "darwin"),
            patch.object(Toolkit, "macos_check_permission", return_value=True),
            patch.object(Toolkit, "find_desktop_windows", return_value=windows),
        ):
            devices = service._find_devices_for_controller(controller)

        assert devices == [
            {
                "type": "MacOS",
                "hWnd": 12,
                "class_name": "com.example.game",
                "window_name": "Game",
                "screencap_methods": 0,
                "input_methods": 0,
            }
        ]

    def test_scan_requests_missing_permissions(self, app_root: Path):
        controller = _controller("MacController", "MacOS")
        worker = TestLinuxSupport._linux_worker(app_root, controller)

        with (
            patch("backend.maa_worker.device_service.sys.platform", "darwin"),
            patch.object(Toolkit, "macos_check_permission", return_value=False),
            patch.object(Toolkit, "macos_request_permission"),
        ):
            devices = DeviceService(worker)._find_devices_for_controller(controller)  # type: ignore[arg-type]

        assert devices == []
        assert "屏幕录制" in worker.device_state.last_device_error
        assert "辅助功能" in worker.device_state.last_device_error

    def test_connect_rejects_unsupported_platform(self, app_root: Path):
        controller = _controller("MacController", "MacOS")
        worker = TestLinuxSupport._linux_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "MacController", "MacOS", "42"
        )

        with patch("backend.maa_worker.device_service.sys.platform", "win32"):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is False
        assert (
            worker.device_state.last_device_error
            == _UNSUPPORTED_REASON_TEXT["platform_not_supported"]
        )

    def test_connect_requests_missing_permissions(self, app_root: Path):
        controller = _controller("MacController", "MacOS")
        worker = TestLinuxSupport._linux_worker(app_root, controller)
        model = DeviceService.build_device_model_from_config(
            "MacController", "MacOS", "42"
        )

        with (
            patch("backend.maa_worker.device_service.sys.platform", "darwin"),
            patch.object(
                Toolkit,
                "macos_check_permission",
                side_effect=lambda perm: perm == MaaMacOSPermissionEnum.ScreenCapture,
            ),
            patch.object(Toolkit, "macos_request_permission"),
        ):
            connected = DeviceService(worker).connect(model)  # type: ignore[arg-type]

        assert connected is False
        assert "辅助功能" in worker.device_state.last_device_error
        assert "屏幕录制" not in worker.device_state.last_device_error


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

    @pytest.mark.parametrize(
        ("controller_name", "device_type", "first", "second", "expected"),
        [
            (
                "AdbController",
                "Adb",
                "  10.0.0.2:5555  ",
                "10.0.0.2:5555",
                "10.0.0.2:5555",
            ),
            ("Win32Controller", "Win32", "00100", "100", "100"),
            ("GamepadController", "Gamepad", "008|01", "8|1", "8|1"),
        ],
    )
    def test_dedupes_by_canonical_identity(
        self,
        service: DeviceService,
        controller_name: str,
        device_type: str,
        first: str,
        second: str,
        expected: str,
    ):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name=controller_name, type=device_type, address=first
            )
        )
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name=controller_name, type=device_type, address=second
            )
        )
        records = service._load_custom_devices()
        assert len(records) == 1
        assert records[0]["address"] == expected

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

    @staticmethod
    def _write_settings(
        app_root: Path,
        custom_devices: list[dict[str, object]] | None = None,
    ) -> Path:
        """Write a minimal settings.json with optional customDevices."""
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        panel: dict[str, object] = {}
        if custom_devices is not None:
            panel["customDevices"] = custom_devices
        path.write_text(json.dumps({"panel": panel}), encoding="utf-8")
        return path

    @pytest.mark.parametrize(
        "content",
        ["", "{not-json", '{"oops": true}', '{"panel": {"customDevices": "nope"}}'],
    )
    def test_unreadable_settings_tolerated(
        self, service: DeviceService, app_root: Path, content: str
    ):
        path = app_root / "config" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
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

    def test_path_uses_app_root_not_cwd(
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

    @pytest.mark.parametrize(
        ("controller_name", "device_type", "custom_address", "scanned"),
        [
            (
                "AdbController",
                "Adb",
                "10.0.0.1:5555",
                [
                    {
                        "name": "RichScan",
                        "type": "Adb",
                        "adb_path": "C:/adb.exe",
                        "address": "10.0.0.1:5555",
                        "screencap_methods": "99",
                        "input_methods": "88",
                        "config": {"from": "scan"},
                    }
                ],
            ),
            (
                "Win32Controller",
                "Win32",
                "00100",
                [
                    {
                        "type": "Win32",
                        "hWnd": 100,
                        "class_name": "Chrome",
                        "window_name": "Browser",
                        "screencap_methods": 1,
                        "input_methods": 1,
                    }
                ],
            ),
        ],
    )
    def test_scan_wins_on_duplicate_identity(
        self,
        service: DeviceService,
        controller_name: str,
        device_type: str,
        custom_address: str,
        scanned: list[dict[str, Any]],
    ):
        service.add_custom_device(
            CustomDeviceCreate(
                controller_name=controller_name,
                type=device_type,
                address=custom_address,
            )
        )
        assert service._merge_custom_devices(controller_name, scanned) == scanned

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
