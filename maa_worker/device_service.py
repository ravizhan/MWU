import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from maa.controller import (
    AdbController,
    GamepadController,
    LinuxController,
    PlayCoverController,
    Win32Controller,
)
from maa.controller import (
    MacOSController as SdkMacOSController,
)
from maa.define import MaaMacOSPermissionEnum
from maa.toolkit import Toolkit

from models.api import CustomDeviceCreate, DeviceModel
from models.device_address import (
    LinuxDeviceAddress,
    canonicalize_custom_device_address,
    try_canonicalize_runtime_device_address,
)
from models.interface_loader import resolve_interface_relative_path
from models.scheduler import PreTaskCommand, TaskOptionValue
from settings_io import SETTINGS_LOCK, atomic_write_settings, read_settings_raw
from services.privilege_service import check_permission

if TYPE_CHECKING:
    from maa_utils import MaaWorker


def is_controller_supported(controller) -> tuple[bool, str]:
    match controller.type:
        case "Adb":
            return True, ""
        case "Win32":
            if sys.platform != "win32":
                return False, "platform_not_supported"
            if not controller.win32:
                return False, "controller_config_missing"
            return True, ""
        case "MacOS":
            if sys.platform != "darwin":
                return False, "platform_not_supported"
            if not controller.macos:
                return False, "controller_config_missing"
            return True, ""
        case "PlayCover":
            if sys.platform != "darwin":
                return False, "platform_not_supported"
            return True, ""
        case "Linux":
            if not sys.platform.startswith("linux"):
                return False, "platform_not_supported"
            return True, ""
        case "Gamepad":
            if sys.platform != "win32":
                return False, "platform_not_supported"
            if not controller.gamepad:
                return False, "controller_config_missing"
            return True, ""
        case _:
            return False, "controller_not_supported"


def _record_identity(
    controller_name: str, device_type: str, address: str
) -> tuple[str, str, str]:
    return (controller_name, device_type, address)


def _applicable_pi_pretasks(
    interface, controller_name: str, resource_name: str
) -> list:
    """返回对当前 controller/resource 适用的 PI pretask 列表。"""
    raw = interface.pretask
    if raw is None:
        return []
    pretasks = raw if isinstance(raw, list) else [raw]
    return [
        p
        for p in pretasks
        if (not p.controller or controller_name in p.controller)
        and (not p.resource or resource_name in p.resource)
    ]


def _scan_device_address(device: dict[str, Any]) -> str | None:
    device_type = device.get("type")
    if device_type in ("Adb", "PlayCover", "MacOS", "Linux"):
        return try_canonicalize_runtime_device_address(
            device_type, str(device.get("address", ""))
        )
    if device_type == "Win32":
        return try_canonicalize_runtime_device_address(
            device_type, str(device.get("hWnd", ""))
        )
    if device_type == "Gamepad":
        return try_canonicalize_runtime_device_address(
            device_type,
            f"{device.get('hWnd', 0)}|{device.get('gamepad_type', 0)}",
        )
    return None


def custom_record_to_device(record: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a ConnectableDevice-like dict from a persisted custom record."""
    device_type = record.get("type")
    address = str(record.get("address", ""))

    if device_type == "Adb":
        return {
            "name": "",
            "type": "Adb",
            "adb_path": "",
            "address": address,
            "screencap_methods": 0,
            "input_methods": 0,
            "config": {},
        }
    if device_type == "Win32":
        return {
            "type": "Win32",
            "hWnd": int(address),
            "class_name": "",
            "window_name": "",
            "screencap_methods": 0,
            "input_methods": 0,
        }
    if device_type == "Gamepad":
        hwnd_s, type_s = address.split("|", 1)
        return {
            "type": "Gamepad",
            "hWnd": int(hwnd_s),
            "class_name": "",
            "window_name": "",
            "screencap_methods": 0,
            "gamepad_type": int(type_s),
        }
    if device_type == "MacOS":
        return {
            "type": "MacOS",
            "name": address,
            "address": address,
            "screencap_methods": 1,
            "input_methods": 1,
        }
    if device_type == "PlayCover":
        return {"type": "PlayCover", "address": address}
    return {"type": device_type, "address": address}


class DeviceService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _settings_path(self) -> Path:
        return self.worker.context.interface_base_dir / "config" / "settings.json"

    def _load_custom_devices(self) -> list[dict[str, Any]]:
        with SETTINGS_LOCK:
            path = self._settings_path()
            raw = read_settings_raw(path)
            panel = raw.get("panel") if isinstance(raw, dict) else None
            custom_list = (
                panel.get("customDevices") if isinstance(panel, dict) else None
            )
            if not isinstance(custom_list, list):
                return []

            records: list[dict[str, Any]] = []
            for item in custom_list:
                if not isinstance(item, dict):
                    continue
                controller_name = str(item.get("controller_name", "")).strip()
                device_type = item.get("type")
                if not controller_name or device_type not in (
                    "Adb",
                    "Win32",
                    "MacOS",
                    "Gamepad",
                    "PlayCover",
                    "Linux",
                ):
                    continue
                address = try_canonicalize_runtime_device_address(
                    device_type, str(item.get("address", ""))
                )
                if address is None:
                    continue
                records.append(
                    {
                        "controller_name": controller_name,
                        "type": device_type,
                        "address": address,
                    }
                )
            return records

    def _save_custom_devices(self, records: list[dict[str, Any]]) -> None:
        with SETTINGS_LOCK:
            path = self._settings_path()
            # Load existing settings to preserve all fields
            raw = read_settings_raw(path)
            if not isinstance(raw, dict):
                raw = {}
            panel = raw.get("panel")
            if not isinstance(panel, dict):
                panel = {}
            panel["customDevices"] = records
            raw["panel"] = panel
            atomic_write_settings(path, raw)

    def add_custom_device(self, payload: CustomDeviceCreate) -> dict[str, Any]:
        controller = self.get_controller_definition(payload.controller_name)
        if controller is None:
            raise ValueError("未找到匹配的控制器配置")
        if controller.type != payload.type:
            raise ValueError("控制器类型不匹配")

        address = canonicalize_custom_device_address(payload.type, payload.address)
        record = {
            "controller_name": payload.controller_name,
            "type": payload.type,
            "address": address,
        }
        identity = _record_identity(
            record["controller_name"], record["type"], record["address"]
        )

        with SETTINGS_LOCK:
            records = self._load_custom_devices()
            for existing in records:
                if (
                    _record_identity(
                        existing["controller_name"],
                        existing["type"],
                        existing["address"],
                    )
                    == identity
                ):
                    return custom_record_to_device(existing)
            records.append(record)
            self._save_custom_devices(records)

        return custom_record_to_device(record)

    def _merge_custom_devices(
        self, controller_name: str, devices: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        seen: set[tuple[str, str, str]] = set()
        for device in devices:
            address = _scan_device_address(device)
            device_type = device.get("type")
            if address is None or not device_type:
                continue
            seen.add(_record_identity(controller_name, device_type, address))

        merged = list(devices)
        with SETTINGS_LOCK:
            custom_records = self._load_custom_devices()
        for record in custom_records:
            if record["controller_name"] != controller_name:
                continue
            identity = _record_identity(
                record["controller_name"], record["type"], record["address"]
            )
            if identity in seen:
                continue  # scan wins on duplicate identity
            merged.append(custom_record_to_device(record))
            seen.add(identity)
        return merged

    def _resource_path(self, path: str) -> Path:
        """解析资源路径：{PROJECT_DIR} 替换为 interface 根目录并做 containment 校验。"""
        base_dir = Path(self.worker.context.interface_base_dir).resolve()
        # resource bundle 既可能是目录（resource/）也可能是单文件，两种都合法。
        if "{PROJECT_DIR}" in path:
            prefix, remainder = path.split("{PROJECT_DIR}", 1)
            if prefix.strip().replace("\\", "/").strip("/"):
                raise ValueError(f"path 中的 {{PROJECT_DIR}} 只能出现在开头: {path}")
            relative = remainder.strip().replace("\\", "/").lstrip("/")
            if not relative:
                raise ValueError("path 不能为空")
            return resolve_interface_relative_path(
                base_dir, relative, allow_files_and_directories=True
            )
        return resolve_interface_relative_path(
            base_dir, path, allow_files_and_directories=True
        )

    def _load_resource_bundle(self, path: str) -> str:
        resolved_path = self._resource_path(path)
        self.worker.resource.post_bundle(resolved_path).wait()
        return str(resolved_path)

    def _append_controller_resource_paths(self, controller) -> list[str]:
        loaded_paths: list[str] = []
        if controller is None or not controller.attach_resource_path:
            return loaded_paths

        for path in controller.attach_resource_path:
            loaded_paths.append(self._load_resource_bundle(path))
        return loaded_paths

    def _build_controller_display_labels(self) -> dict[str, str]:
        label_counts: dict[str, int] = {}
        base_labels: dict[str, str] = {}

        for controller in self.worker.interface.controller:
            base_label = controller.label or controller.name or controller.type
            base_labels[controller.name] = base_label
            label_counts[base_label] = label_counts.get(base_label, 0) + 1

        display_labels: dict[str, str] = {}
        for controller in self.worker.interface.controller:
            base_label = base_labels[controller.name]
            if label_counts[base_label] > 1:
                display_labels[controller.name] = f"{base_label}({controller.name})"
            else:
                display_labels[controller.name] = base_label
        return display_labels

    def get_controller_definition(self, controller_name: str | None):
        if not controller_name:
            return None
        return next(
            (
                controller
                for controller in self.worker.interface.controller
                if controller.name == controller_name
            ),
            None,
        )

    def get_current_resource_definition(self):
        resource_name = self.worker.device_state.current_resource_name
        if resource_name is None:
            return None
        return next(
            (
                item
                for item in self.worker.interface.resource
                if item.name == resource_name
            ),
            None,
        )

    def get_active_controller_definitions(self) -> list[Any]:
        controller = self.get_controller_definition(
            self.worker.device_state.controller_name
        )
        return [controller] if controller is not None else []

    def get_active_controller_names(self) -> set[str]:
        return {
            controller.name for controller in self.get_active_controller_definitions()
        }

    def build_device_capabilities(self) -> list[dict[str, Any]]:
        capabilities: list[dict[str, Any]] = []
        display_labels = self._build_controller_display_labels()
        for controller in self.worker.interface.controller:
            supported, reason = is_controller_supported(controller)
            capabilities.append(
                {
                    "name": controller.name,
                    "type": controller.type,
                    "label": controller.label or controller.name or controller.type,
                    "display_label": display_labels[controller.name],
                    "enabled": supported,
                    "reason": "" if supported else reason,
                    "search_mode": "input"
                    if controller.type == "PlayCover"
                    else "select",
                    "default_address": "127.0.0.1:1717"
                    if controller.type == "PlayCover"
                    else "",
                }
            )

        controller_order = [
            "Adb",
            "Win32",
            "Gamepad",
            "PlayCover",
            "MacOS",
            "Linux",
        ]
        return sorted(
            capabilities,
            key=lambda item: (
                controller_order.index(item["type"])
                if item["type"] in controller_order
                else len(controller_order),
                item["display_label"],
            ),
        )

    def _scan_wlr_devices(self) -> list[dict[str, Any]]:
        """Wlr 模式：从既有桌面窗口 socket 发现结果枚举候选。"""
        devices: list[dict[str, Any]] = []
        socket_seen: set[str] = set()
        for device in Toolkit.find_desktop_windows():
            socket_path = device.class_name.strip()
            if not socket_path or socket_path in socket_seen:
                continue
            socket_seen.add(socket_path)
            address = LinuxDeviceAddress(
                kind="wlr", wlr_socket_path=socket_path
            ).to_compact_json()
            devices.append(
                {
                    "type": "Linux",
                    "name": device.window_name,
                    "address": address,
                }
            )
        return devices

    def _find_devices_for_controller(self, controller) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        win32_seen: set[int] = set()

        supported, _ = is_controller_supported(controller)
        if not supported:
            return devices

        match controller.type:
            case "Adb":
                for device in Toolkit.find_adb_devices():
                    data = {
                        "name": device.name,
                        "type": "Adb",
                        "adb_path": str(device.adb_path),
                        "address": device.address,
                        "screencap_methods": str(device.screencap_methods),
                        "input_methods": str(device.input_methods),
                        "config": device.config,
                    }
                    if data not in devices:
                        devices.append(data)
            case "Win32":
                assert controller.win32 is not None
                for device in Toolkit.find_desktop_windows():
                    class_name = device.class_name
                    window_name = device.window_name
                    class_match = not controller.win32.class_regex or re.search(
                        controller.win32.class_regex, class_name
                    )
                    window_match = not controller.win32.window_regex or re.search(
                        controller.win32.window_regex, window_name
                    )
                    if not (class_match and window_match):
                        continue

                    hwnd = int(device.hwnd)
                    if hwnd in win32_seen:
                        continue
                    win32_seen.add(hwnd)

                    devices.append(
                        {
                            "type": "Win32",
                            "hWnd": hwnd,
                            "class_name": class_name,
                            "window_name": window_name,
                            "screencap_methods": controller.win32.screencap or 1,
                            "input_methods": controller.win32.mouse
                            or controller.win32.keyboard
                            or 1,
                        }
                    )
            case "MacOS":
                assert controller.macos is not None
                window_id_seen: set[str] = set()
                for device in Toolkit.find_desktop_windows():
                    window_name = device.window_name
                    if controller.macos.title_regex and not re.search(
                        controller.macos.title_regex, window_name
                    ):
                        continue
                    window_id = str(int(device.hwnd))
                    if window_id in window_id_seen:
                        continue
                    window_id_seen.add(window_id)
                    devices.append(
                        {
                            "type": "MacOS",
                            "name": window_name,
                            "address": window_id,
                            "screencap_methods": 1,
                            "input_methods": 1,
                        }
                    )
            case "Linux":
                devices = self._find_linux_devices(controller)
            case "PlayCover":
                return devices
            case "Gamepad":
                devices = self._find_gamepad_devices(controller)
        return devices

    def _find_linux_devices(self, controller) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        cfg = controller.linux
        if cfg is None:
            return devices

        screencap = cfg.screencap or "Wlr"

        if screencap == "Wlr":
            devices.extend(self._scan_wlr_devices())
        elif screencap == "PipeWire":
            if cfg.pipewire_source == "Gamescope" or cfg.pipewire_source is None:
                for instance in Toolkit.find_gamescope_instances():
                    address = LinuxDeviceAddress(
                        kind="gamescope", display_no=instance.display_no
                    ).to_compact_json()
                    devices.append(
                        {
                            "type": "Linux",
                            "name": f"gamescope-{instance.display_no}",
                            "address": address,
                        }
                    )
            else:
                address = LinuxDeviceAddress(kind="portal").to_compact_json()
                devices.append(
                    {
                        "type": "Linux",
                        "name": "通过系统选择屏幕",
                        "address": address,
                    }
                )
        return devices

    def _find_gamepad_devices(self, controller) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        assert controller.gamepad is not None
        has_window_filter = bool(
            controller.gamepad.class_regex or controller.gamepad.window_regex
        )
        if not has_window_filter:
            # 无窗口过滤：允许创建无窗口手柄控制器（hWnd=None）
            devices.append(
                {
                    "type": "Gamepad",
                    "hWnd": 0,
                    "class_name": "",
                    "window_name": "",
                    "screencap_methods": controller.gamepad.screencap or 2,
                    "gamepad_type": controller.gamepad.gamepad_type or 0,
                }
            )
            return devices

        gamepad_seen: set[int] = set()
        for device in Toolkit.find_desktop_windows():
            class_name = device.class_name
            window_name = device.window_name
            class_match = not controller.gamepad.class_regex or re.search(
                controller.gamepad.class_regex, class_name
            )
            window_match = not controller.gamepad.window_regex or re.search(
                controller.gamepad.window_regex, window_name
            )
            if not (class_match and window_match):
                continue

            hwnd = int(device.hwnd)
            if hwnd in gamepad_seen:
                continue
            gamepad_seen.add(hwnd)

            devices.append(
                {
                    "type": "Gamepad",
                    "hWnd": hwnd,
                    "class_name": class_name,
                    "window_name": window_name,
                    "screencap_methods": controller.gamepad.screencap or 2,
                    "gamepad_type": controller.gamepad.gamepad_type or 0,
                }
            )
        return devices

    def get_device(self, controller_name: str | None = None) -> dict[str, Any]:
        capabilities = self.build_device_capabilities()
        all_names = [item["name"] for item in capabilities]
        enabled_names = [item["name"] for item in capabilities if item["enabled"]]

        selected_name = controller_name if controller_name in all_names else None
        if not selected_name:
            if enabled_names:
                selected_name = enabled_names[0]
            elif all_names:
                selected_name = all_names[0]

        selected_capability = next(
            (item for item in capabilities if item["name"] == selected_name), None
        )
        devices: list[dict[str, Any]] = []
        if (
            selected_name
            and selected_capability
            and selected_capability["enabled"]
            and selected_capability["search_mode"] == "select"
        ):
            controller = self.get_controller_definition(selected_name)
            if controller is not None:
                devices = self._find_devices_for_controller(controller)

        if selected_name:
            devices = self._merge_custom_devices(selected_name, devices)

        return {
            "controllers": capabilities,
            "selected_controller": selected_name,
            "devices": devices,
        }

    def is_connection_alive(self) -> bool:
        controller = self.worker.device_state.controller
        if not self.worker.device_state.connected or controller is None:
            return False
        return bool(getattr(controller, "connected", False))

    def reset_connection_state(self, reason: str | None = None):
        state = self.worker.device_state
        state_changed = (
            state.connected
            or state.configuration_locked
            or state.controller is not None
            or state.controller_name is not None
            or state.controller_type is not None
        )

        # 先释放 controller sink，再释放 controller，最后清 portal helper，
        # 保证 PortalHelper 的生命周期不越过控制器（沿用 SDK 析构释放）。
        if state.controller is not None and hasattr(self.worker, "sinks"):
            self.worker.sinks.unregister_controller_sink(state.controller)
        state.controller = None
        if state.portal_helper is not None:
            state.portal_helper = None

        state.connected = False
        state.configuration_locked = False
        state.controller_name = None
        state.controller_type = None
        state.current_resource_name = None

        if reason:
            state.last_device_error = reason
            if state_changed:
                self.worker.events.send_log(reason)

    @staticmethod
    def build_device_model_from_config(
        controller_name: str, device_type: str, device_address: str
    ) -> DeviceModel:
        """从简化设备配置构造 DeviceModel。

        由调度器使用，在执行定时任务前根据存储的设备配置构造 DeviceModel，
        然后传递给 connect() 进行实际连接。

        Args:
            controller_name: 控制器名称（来自 interface.json 的 controller name）
            device_type: 设备类型 ("Adb", "Win32", "MacOS", "Gamepad", "PlayCover",
                "Linux")
            device_address: 设备地址（格式因类型而异）
                - Adb: IP:PORT 地址，如 "127.0.0.1:5555"
                - Win32: hWnd 的字符串形式，如 "123456"
                - MacOS: CGWindowID 的十进制字符串形式
                - Gamepad: "hWnd|gamepad_type" 格式，如 "123456|1"；hWnd 为 0 表示无窗口
                - PlayCover: IP:PORT 地址，如 "127.0.0.1:1717"
                - Linux: LinuxDeviceAddress 的键排序紧凑 JSON

        Returns:
            构造好的 DeviceModel 实例

        Raises:
            ValueError: 不支持的设备类型
        """
        if device_type == "Adb":
            return DeviceModel(
                type="Adb",
                controller_name=controller_name,
                name=device_address,
                address=device_address,
                adb_path="",
                screencap_methods=0,
                input_methods=0,
                config={},
            )
        elif device_type == "Win32":
            try:
                hwnd = int(device_address)
            except (ValueError, TypeError):
                hwnd = 0
            return DeviceModel(
                type="Win32",
                controller_name=controller_name,
                name=device_address,
                hWnd=hwnd,
                screencap_methods=0,
                input_methods=0,
            )
        elif device_type == "MacOS":
            try:
                window_id = int(device_address)
            except (ValueError, TypeError):
                window_id = 0
            return DeviceModel(
                type="MacOS",
                controller_name=controller_name,
                name=device_address,
                address=str(window_id),
                screencap_methods=1,
                input_methods=1,
            )
        elif device_type == "Gamepad":
            parts = device_address.split("|", 1)
            try:
                hwnd = int(parts[0]) if parts else 0
            except (ValueError, TypeError):
                hwnd = 0
            gamepad_type = 0
            if len(parts) > 1:
                try:
                    gamepad_type = int(parts[1])
                except (ValueError, TypeError):
                    gamepad_type = 0
            return DeviceModel(
                type="Gamepad",
                controller_name=controller_name,
                name=device_address,
                hWnd=hwnd,
                gamepad_type=gamepad_type,
                screencap_methods=0,
            )
        elif device_type == "PlayCover":
            return DeviceModel(
                type="PlayCover",
                controller_name=controller_name,
                name=device_address,
                address=device_address,
                uuid="",
            )
        elif device_type == "Linux":
            address = LinuxDeviceAddress.from_compact_json(
                device_address
            ).to_compact_json()
            return DeviceModel(
                type="Linux",
                controller_name=controller_name,
                name=address,
                address=address,
            )
        else:
            raise ValueError(f"不支持的设备类型: {device_type}")

    # -- Linux 连接辅助 -----------------------------------------------------

    def _ensure_macos_permissions(self) -> tuple[bool, str]:
        """检查 macOS TCC 权限；缺失时请求，拒绝时打开权限设置并失败。"""
        for permission in (
            MaaMacOSPermissionEnum.ScreenCapture,
            MaaMacOSPermissionEnum.Accessibility,
        ):
            if Toolkit.macos_check_permission(permission):
                continue
            Toolkit.macos_request_permission(permission)
            if not Toolkit.macos_check_permission(permission):
                Toolkit.macos_reveal_permission_settings(permission)
                return False, "macos_permission_required"
        return True, ""

    def _build_linux_config(
        self,
        address: LinuxDeviceAddress,
        screencap: str,
        input_method: str,
        use_win32_vk_code: bool,
    ) -> dict[str, Any] | None:
        """构建 LinuxController JSON 配置；不可用返回 None 并记录错误。"""
        state = self.worker.device_state
        screencap_int = 1 if screencap == "Wlr" else 4
        input_int = {"Wlr": 1, "UInput": 2, "Libei": 4}[input_method]

        if address.kind == "wlr":
            config: dict[str, Any] = {
                "screencap_method": screencap_int,
                "input_method": input_int,
                "wlr_socket_path": address.wlr_socket_path,
                "use_win32_vk_code": use_win32_vk_code,
            }
            if address.uinput_path:
                config["uinput_path"] = address.uinput_path
            if address.uinput_screen_width is not None:
                config["uinput_screen_width"] = address.uinput_screen_width
            if address.uinput_screen_height is not None:
                config["uinput_screen_height"] = address.uinput_screen_height
            return config

        if address.kind == "gamescope":
            instances = [
                item
                for item in Toolkit.find_gamescope_instances()
                if item.display_no == address.display_no
            ]
            if not instances:
                state.last_device_error = "linux_device_unavailable"
                return None
            instance = instances[0]
            if instance.pipewire_node_id == 0:
                state.last_device_error = "linux_device_unavailable"
                return None
            config = {
                "screencap_method": 4,
                "input_method": input_int,
                "pw_node_id": instance.pipewire_node_id,
                "use_win32_vk_code": use_win32_vk_code,
            }
            if input_method == "Libei":
                eis_socket_path = address.eis_socket_path or instance.eis_socket_path
                config["eis_socket_path"] = eis_socket_path
            return config

        # portal
        helper = state.portal_helper
        if helper is None:
            try:
                helper = Toolkit.portal_helper_create()
            except Exception:
                state.last_device_error = "linux_device_unavailable"
                return None
            if not helper.open_stream():
                state.portal_helper = None
                state.last_device_error = "linux_portal_cancelled"
                return None
            state.portal_helper = helper
        config = {
            "screencap_method": 4,
            "input_method": input_int,
            "pw_socket_fd": helper.get_pipewire_fd(),
            "pw_node_id": helper.get_pipewire_node_id(),
            "use_win32_vk_code": use_win32_vk_code,
        }
        if input_method == "Libei":
            config["eis_socket_path"] = address.eis_socket_path
        return config

    def connect(self, device_config: DeviceModel) -> bool:
        state = self.worker.device_state
        if state.configuration_locked:
            if not self.is_connection_alive():
                self.reset_connection_state(
                    "检测到设备连接已断开，已解除设备与资源锁定"
                )
            else:
                state.last_device_error = (
                    "设备与资源已锁定，当前生命周期内不允许重新连接"
                )
                self.worker.events.send_log(state.last_device_error)
                return False

        state.last_device_error = None
        device_type = device_config.type
        selected_controller = self.get_controller_definition(
            device_config.controller_name
        )
        if selected_controller is None or selected_controller.type != device_type:
            state.last_device_error = "未找到匹配的控制器配置"
            self.worker.events.send_log(state.last_device_error)
            return False

        status = False
        controller = None
        conn_fail_msg = "设备连接失败，请检查终端日志"
        try:
            if device_type == "Adb":
                controller = AdbController(
                    adb_path=device_config.adb_path,
                    address=device_config.address,
                    screencap_methods=int(device_config.screencap_methods or 0),
                    input_methods=int(device_config.input_methods or 0),
                    config=device_config.config or {},
                )
                status = controller.post_connection().wait().succeeded
            elif device_type == "Win32":
                win32_cfg = selected_controller.win32
                mouse_method = 1
                keyboard_method = 1
                screencap_method = 18
                if win32_cfg is not None:
                    if win32_cfg.screencap is not None:
                        screencap_method = int(win32_cfg.screencap)
                    if win32_cfg.mouse is not None:
                        mouse_method = int(win32_cfg.mouse)
                    if win32_cfg.keyboard is not None:
                        keyboard_method = int(win32_cfg.keyboard)
                controller = Win32Controller(
                    hWnd=device_config.hWnd,
                    screencap_method=screencap_method,
                    mouse_method=mouse_method,
                    keyboard_method=keyboard_method,
                )
                status = controller.post_connection().wait().succeeded
            elif device_type == "MacOS":
                macos_cfg = selected_controller.macos
                if macos_cfg is None:
                    state.last_device_error = "未找到匹配的控制器配置"
                    self.worker.events.send_log(state.last_device_error)
                    return False
                permission_ok, permission_error = self._ensure_macos_permissions()
                if not permission_ok:
                    state.last_device_error = permission_error
                    self.worker.events.send_log(state.last_device_error)
                    return False
                input_method_int = 2 if macos_cfg.input == "PostToPid" else 1
                controller = SdkMacOSController(
                    window_id=int(device_config.address),
                    screencap_method=1,
                    input_method=input_method_int,
                )
                status = controller.post_connection().wait().succeeded
            elif device_type == "Linux":
                linux_cfg = selected_controller.linux
                if linux_cfg is None:
                    state.last_device_error = "未找到匹配的控制器配置"
                    self.worker.events.send_log(state.last_device_error)
                    return False
                address = LinuxDeviceAddress.from_compact_json(device_config.address)
                linux_config = self._build_linux_config(
                    address,
                    screencap=linux_cfg.screencap or "Wlr",
                    input_method=linux_cfg.input or "Wlr",
                    use_win32_vk_code=bool(linux_cfg.use_win32_vk_code),
                )
                if linux_config is None:
                    self.worker.events.send_log(
                        state.last_device_error or "设备连接失败，请检查终端日志"
                    )
                    return False
                controller = LinuxController(config=linux_config)
                status = controller.post_connection().wait().succeeded
            elif device_type == "Gamepad":
                hwnd = device_config.hWnd or None
                gamepad_cfg = selected_controller.gamepad
                screencap_method = 2
                if gamepad_cfg is not None and gamepad_cfg.screencap is not None:
                    screencap_method = int(gamepad_cfg.screencap)
                controller = GamepadController(
                    hWnd=hwnd,
                    gamepad_type=int(device_config.gamepad_type or 0),
                    screencap_method=screencap_method,
                )
                status = controller.post_connection().wait().succeeded
            elif device_type == "PlayCover":
                controller = PlayCoverController(
                    address=device_config.address or "127.0.0.1:1717",
                    uuid=device_config.uuid or "maa.playcover",
                )
                status = controller.post_connection().wait().succeeded
            else:
                state.last_device_error = "未找到匹配的控制器配置"
                self.worker.events.send_log(state.last_device_error)
                return False
        except Exception as exc:
            state.last_device_error = f"设备连接失败: {exc}"
            self.worker.events.send_log(state.last_device_error)
            return False

        if not status:
            self.worker.events.show_system_notification(
                self.worker.interface.title or self.worker.interface.label or "MWU",
                conn_fail_msg,
            )
            state.last_device_error = conn_fail_msg
            self.worker.events.send_log(state.last_device_error)
            return False

        if not self._apply_display_targets(selected_controller, controller):
            return False

        time.sleep(1)
        if self.worker.tasker.bind(self.worker.resource, controller):
            state.connected = True
            state.controller = controller
            state.controller_type = device_type
            state.controller_name = selected_controller.name
            state.last_device_error = None

            # 注册 controller sink
            if hasattr(self.worker, "sinks"):
                self.worker.sinks.register_controller_sink(controller)

            self.worker.events.send_log("设备连接成功")
            return True

        self.worker.events.show_system_notification(
            self.worker.interface.title or self.worker.interface.label or "MWU",
            conn_fail_msg,
        )
        state.last_device_error = conn_fail_msg
        self.worker.events.send_log(state.last_device_error)
        return False

    def _apply_display_targets(self, controller_def, controller) -> bool:
        """在 bind 前按 PI 控制器模型设置截图目标。

        互斥判定按显式输入字段进行：显式给出的 short_side=720 也视为提供；
        仅当三个字段都未显式给出时使用短边 720 默认。
        """
        state = self.worker.device_state
        explicitly_set = controller_def.model_fields_set
        configured = [
            name
            for name in ("display_short_side", "display_long_side", "display_raw")
            if name in explicitly_set
        ]

        try:
            if not configured:
                if not controller.set_screenshot_target_short_side(720):
                    raise RuntimeError("设置截图目标（short_side=720）失败")
            elif configured == ["display_short_side"]:
                if controller_def.display_short_side is None:
                    if not controller.set_screenshot_target_short_side(720):
                        raise RuntimeError("设置截图目标（short_side=720）失败")
                elif not controller.set_screenshot_target_short_side(
                    int(controller_def.display_short_side)
                ):
                    raise RuntimeError("设置截图目标（short_side）失败")
            elif configured == ["display_long_side"]:
                long_value = controller_def.display_long_side
                if long_value is None:
                    # 显式 null 等价于未配置截图目标 → 回退短边 720
                    if not controller.set_screenshot_target_short_side(720):
                        raise RuntimeError("设置截图目标（short_side=720）失败")
                elif not controller.set_screenshot_target_long_side(int(long_value)):
                    raise RuntimeError("设置截图目标（long_side）失败")
            elif configured == ["display_raw"]:
                raw_value = bool(controller_def.display_raw)
                if not controller.set_screenshot_use_raw_size(raw_value):
                    raise RuntimeError("设置截图目标（raw）失败")
            else:
                state.last_device_error = (
                    "display_short_side, display_long_side 和 display_raw 必须互斥"
                )
                self.worker.events.send_log(state.last_device_error)
                return False
        except Exception as exc:
            state.last_device_error = f"设备连接失败: {exc}"
            self.worker.events.send_log(state.last_device_error)
            return False
        return True

    def set_resource(self, resource_name: str) -> bool:
        state = self.worker.device_state
        if state.configuration_locked:
            if not self.is_connection_alive():
                self.reset_connection_state(
                    "检测到设备连接已断开，已解除设备与资源锁定"
                )
            else:
                state.last_resource_error = (
                    "设备与资源已锁定，当前生命周期内不允许修改资源"
                )
                self.worker.events.send_log(state.last_resource_error)
                return False

        state.last_resource_error = None
        for resource_config in self.worker.interface.resource:
            if resource_config.name != resource_name:
                continue

            # 切换资源：先清理上一套已加载路径的内容，再加载本次 path。
            # SDK Resource 是模块级单例，无卸载 API；clear() 可能因正在加载
            # 失败，清空失败不阻断新资源加载（旧内容可能残留）。
            if self.worker.resource.loaded:
                try:
                    self.worker.resource.clear()
                except Exception:
                    pass

            loaded_paths = [
                self._load_resource_bundle(path) for path in resource_config.path
            ]

            # hash 校验严格保留在所有 path 加载成功之后、附加路径之前：
            # 不匹配仅告警并继续。
            if (
                resource_config.hash
                and resource_config.hash != self.worker.resource.hash
            ):
                self.worker.events.send_log(
                    f"资源包校验值不匹配，建议重新下载资源包: {resource_config.name}"
                )

            state.current_resource_name = resource_config.name
            controller = self.get_controller_definition(state.controller_name)
            attached_paths = self._append_controller_resource_paths(controller)
            if loaded_paths:
                self.worker.events.send_log(
                    f"资源主路径已加载: {', '.join(loaded_paths)}"
                )
            if attached_paths:
                controller_label = (
                    (controller.label or controller.name) if controller else ""
                )
                self.worker.events.send_log(
                    f"已为控制器 {controller_label} 加载附加资源: "
                    f"{', '.join(attached_paths)}"
                )
            self.worker.events.send_log(f"资源已设置为: {resource_config.name}")
            if state.connected:
                state.configuration_locked = True
            return True

        state.last_resource_error = f"未找到资源: {resource_name}"
        self.worker.events.send_log(state.last_resource_error)
        return False

    def has_preparation_programs(
        self,
        controller_name: str,
        resource_name: str,
        user_pre_tasks: list[PreTaskCommand] | None,
    ) -> bool:
        """是否存在需要 Controller 创建前执行的准备程序（PI pretask / 用户命令）。"""
        pi_pretasks = _applicable_pi_pretasks(
            self.worker.interface, controller_name, resource_name
        )
        enabled_user = [
            t for t in (user_pre_tasks or []) if getattr(t, "enabled", True)
        ]
        return bool(pi_pretasks or enabled_user)

    def prepare_connection(
        self,
        device_config: DeviceModel,
        resource_name: str,
        global_options: dict[str, TaskOptionValue],
        user_pre_tasks: list[PreTaskCommand],
    ) -> bool:
        """准备临界区内的连接前准备：权限 → 释放旧连接 → 适用 PI pretask →
        用户命令 → 低层 connect。不加载 resource；调用者随后在同一临界区
        调用 set_resource。

        只要本次有适用 PI pretask 或启用用户命令，就重新创建 Controller
        （释放旧连接）；没有准备程序且 controller/resource 匹配时允许复用。
        低层 connect 不自行运行 pretask，避免重试重复启动准备程序。
        """
        state = self.worker.device_state

        # 1. 管理员权限检查（在任何准备程序之前）
        controller_def = self.get_controller_definition(device_config.controller_name)
        if controller_def is not None:
            permission_error = check_permission(controller_def)
            if permission_error is not None:
                state.last_device_error = "控制器需要管理员权限（permission_required）"
                self.worker.events.send_log(state.last_device_error)
                return False

        effective_controller = device_config.controller_name

        # 2. 适用 PI pretask → 用户 shell 命令（run_all 内部按适用性过滤，
        # 无适用项时为空操作；复用既有连接时同样执行）
        self.worker.pretasks.run_all(
            effective_controller,
            resource_name,
            user_pre_tasks,
            global_options=global_options,
        )

        # 3. 复用判定：无准备程序且 controller/resource 匹配 → 复用既有连接
        has_programs = self.has_preparation_programs(
            effective_controller, resource_name, user_pre_tasks
        )
        reusable = (
            not has_programs
            and state.connected
            and state.configuration_locked
            and state.controller_name == effective_controller
            and state.current_resource_name == resource_name
        )
        if reusable:
            state.prepared_resource_name = resource_name
            return True

        # 4. 释放旧连接（准备程序必须在 Controller 创建前运行）
        if state.connected or state.configuration_locked:
            self.reset_connection_state("准备新的连接上下文，已释放旧连接")

        # 5. 低层 connect（不加载 resource）
        if not self.connect(device_config):
            return False
        state.prepared_resource_name = resource_name
        return True
