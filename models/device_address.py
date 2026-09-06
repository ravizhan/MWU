"""Device address canonicalization authority.

Single source of truth for device address validation and normalization.
Custom (user-entered) addresses are strict; runtime (scanned) addresses
are lenient for Adb (USB serials) but strict for other device types.
"""

import json
import re
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

DeviceType = Literal["Adb", "Win32", "MacOS", "Gamepad", "PlayCover", "Linux"]

_IPV4_PORT_PATTERN = re.compile(r"^([^:]+):(\d+)$")


class LinuxDeviceAddress(BaseModel):
    """Linux 控制器持久化设备地址（runtime fd/node id 不入库）。

    kind 由所选 PI 截图方法/pipewire_source 决定，由调用方给定：
        - "wlr":       Wlr 截图或输入，需要非空 wlr_socket_path
        - "gamescope": PipeWire + Gamescope，需要非负 display_no
        - "portal":    PipeWire + Portal，需要非空 eis_socket_path
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["wlr", "gamescope", "portal"]
    display_no: int | None = None
    wlr_socket_path: str | None = None
    uinput_path: str | None = None
    uinput_screen_width: int | None = None
    uinput_screen_height: int | None = None
    eis_socket_path: str | None = None

    @model_validator(mode="after")
    def _trim_strings(self):
        if self.wlr_socket_path is not None:
            self.wlr_socket_path = self.wlr_socket_path.strip()
        if self.uinput_path is not None:
            self.uinput_path = self.uinput_path.strip()
            if not self.uinput_path:
                self.uinput_path = None
        if self.eis_socket_path is not None:
            self.eis_socket_path = self.eis_socket_path.strip()
        return self

    @model_validator(mode="after")
    def _default_uinput_path(self):
        # UInput 输入需要屏幕宽高与设备路径；提供任一屏幕尺寸即视为启用 UInput
        # 相关字段，缺省设备路径使用 /dev/uinput。
        if (
            self.uinput_screen_width is not None
            or self.uinput_screen_height is not None
            or self.uinput_path is not None
        ):
            if self.uinput_path is None:
                self.uinput_path = "/dev/uinput"
        if (
            self.uinput_screen_width is not None
            or self.uinput_screen_height is not None
        ):
            if (
                not isinstance(self.uinput_screen_width, int)
                or isinstance(self.uinput_screen_width, bool)
                or self.uinput_screen_width < 1
                or not isinstance(self.uinput_screen_height, int)
                or isinstance(self.uinput_screen_height, bool)
                or self.uinput_screen_height < 1
            ):
                raise ValueError("UInput 屏幕宽高必须为正整数")
        return self

    @model_validator(mode="after")
    def _validate_kind(self):
        kind = self.kind
        if kind == "wlr":
            if not self.wlr_socket_path:
                raise ValueError("wlr 模式必须提供非空 wlr_socket_path")
        elif kind == "gamescope":
            if self.display_no is None or self.display_no < 0:
                raise ValueError("gamescope 模式必须提供非负 display_no")
        # portal：屏幕在连接时才由系统选择，地址只携带 kind；
        # 输入方式（UInput/Libei）所需的补充字段在 connect 时按需校验。
        return self

    def to_compact_json(self) -> str:
        """键排序的紧凑 JSON 字符串，作为 device_address 持久化。"""
        return json.dumps(self.model_dump(exclude_none=True), sort_keys=True)

    @staticmethod
    def from_compact_json(text: str) -> "LinuxDeviceAddress":
        try:
            data = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise ValueError("Linux 地址必须是合法的 JSON 对象字符串") from exc
        if not isinstance(data, dict):
            raise ValueError("Linux 地址必须是 JSON 对象")
        return LinuxDeviceAddress.model_validate(data)


def canonicalize_ipv4_port(address: str) -> str:
    """Validate and canonicalize an IPv4:port address.

    Returns canonical form: compressed IPv4 + canonical port.
    Raises ValueError on invalid input.
    """
    text = address.strip()
    if not text:
        raise ValueError("address must not be empty")
    # Reject scheme, path, IPv6, hostnames
    if "://" in text or "/" in text:
        raise ValueError("address must be IPv4:port, not a URL")
    m = _IPV4_PORT_PATTERN.match(text)
    if not m:
        raise ValueError("address must be in IPv4:port format")
    host_raw, port_raw = m.group(1), m.group(2)
    try:
        ip = IPv4Address(host_raw)
    except Exception:
        raise ValueError(f"invalid IPv4 address: {host_raw}") from None
    if not port_raw.isascii() or not port_raw.isdigit():
        raise ValueError(f"invalid port: {port_raw}")
    port = int(port_raw)
    if not 1 <= port <= 65535:
        raise ValueError(f"port out of range: {port} (must be 1-65535)")
    return f"{ip.compressed}:{port}"


def canonicalize_custom_device_address(device_type: str, address: str) -> str:
    """Validate and canonicalize a custom (user-entered) device address.

    Adb/PlayCover: must be IPv4:port.
    Linux: JSON object string validated via LinuxDeviceAddress (strict).
    MacOS: decimal positive integer (CGWindowID).
    Win32: positive integer hWnd.
    Gamepad: hWnd|type where type is 0 or 1.
    """
    text = str(address).strip()
    if device_type in ("Adb", "PlayCover"):
        return canonicalize_ipv4_port(text)
    if device_type == "Linux":
        return LinuxDeviceAddress.from_compact_json(text).to_compact_json()
    if device_type == "MacOS":
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("MacOS 地址必须是正整数 CGWindowID")
        return str(int(text))
    if device_type == "Win32":
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("Win32 address must be a positive integer hWnd")
        return str(int(text))
    if device_type == "Gamepad":
        parts = text.split("|")
        if len(parts) != 2:
            raise ValueError("Gamepad address must be hWnd|type")
        hwnd_raw, type_raw = parts[0].strip(), parts[1].strip()
        if not hwnd_raw.isdigit():
            raise ValueError("Gamepad hWnd must be a non-negative integer")
        # hWnd=0 表示无窗口手柄（未配置窗口过滤时允许）
        if not type_raw.isdigit():
            raise ValueError("Gamepad type must be 0 or 1")
        gamepad_type = int(type_raw)
        if gamepad_type not in (0, 1):
            raise ValueError("Gamepad type must be 0 or 1")
        return f"{int(hwnd_raw)}|{gamepad_type}"
    raise ValueError(f"unsupported device type: {device_type}")


def canonicalize_runtime_device_address(device_type: str, address: str) -> str:
    """Validate and canonicalize a runtime (scanned) device address.

    Adb: any non-empty string (USB serial allowed).
    Linux: JSON object string validated via LinuxDeviceAddress (strict).
    MacOS: decimal positive integer (CGWindowID).
    PlayCover: must be IPv4:port.
    Win32: positive integer hWnd.
    Gamepad: hWnd|type where type is 0 or 1.
    """
    text = str(address).strip()
    if device_type == "Adb":
        if not text:
            raise ValueError("Adb address must not be empty")
        return text
    if device_type == "Linux":
        return LinuxDeviceAddress.from_compact_json(text).to_compact_json()
    if device_type == "MacOS":
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("MacOS 地址必须是正整数 CGWindowID")
        return str(int(text))
    if device_type == "PlayCover":
        return canonicalize_ipv4_port(text)
    if device_type == "Win32":
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("Win32 address must be a positive integer hWnd")
        return str(int(text))
    if device_type == "Gamepad":
        parts = text.split("|")
        if len(parts) != 2:
            raise ValueError("Gamepad address must be hWnd|type")
        hwnd_raw, type_raw = parts[0].strip(), parts[1].strip()
        if not hwnd_raw.isdigit():
            raise ValueError("Gamepad hWnd must be a non-negative integer")
        # hWnd=0 表示无窗口手柄（未配置窗口过滤时允许）
        if not type_raw.isdigit():
            raise ValueError("Gamepad type must be 0 or 1")
        gamepad_type = int(type_raw)
        if gamepad_type not in (0, 1):
            raise ValueError("Gamepad type must be 0 or 1")
        return f"{int(hwnd_raw)}|{gamepad_type}"
    raise ValueError(f"unsupported device type: {device_type}")


def try_canonicalize_runtime_device_address(
    device_type: str, address: str
) -> str | None:
    try:
        return canonicalize_runtime_device_address(device_type, address)
    except (ValueError, TypeError):
        return None
