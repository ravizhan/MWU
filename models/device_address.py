"""Device address canonicalization authority.

Single source of truth for device address validation and normalization.
Custom (user-entered) addresses are strict; runtime (scanned) addresses
are lenient for Adb (USB serials) but strict for PlayCover/Win32/Gamepad/Linux.
"""

import re
from ipaddress import IPv4Address
from typing import Literal

DeviceType = Literal["Adb", "Win32", "Gamepad", "PlayCover", "Linux"]

_IPV4_PORT_PATTERN = re.compile(r"^([^:]+):(\d+)$")


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
    Linux: non-empty Wayland socket path or gamescope identifier.
    Win32: positive integer hWnd.
    Gamepad: hWnd|type where type is 0 or 1.
    """
    text = str(address).strip()
    if device_type in ("Adb", "PlayCover"):
        return canonicalize_ipv4_port(text)
    if device_type == "Linux":
        if not text:
            raise ValueError("Linux device address must not be empty")
        return text
    if device_type == "Win32":
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("Win32 address must be a positive integer hWnd")
        return str(int(text))
    if device_type == "Gamepad":
        parts = text.split("|")
        if len(parts) != 2:
            raise ValueError("Gamepad address must be hWnd|type")
        hwnd_raw, type_raw = parts[0].strip(), parts[1].strip()
        if not hwnd_raw.isdigit() or int(hwnd_raw) <= 0:
            raise ValueError("Gamepad hWnd must be a positive integer")
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
    PlayCover: must be IPv4:port.
    Win32: positive integer hWnd.
    Gamepad: hWnd|type where type is 0 or 1.
    Linux: non-empty Wayland socket path or gamescope identifier.
    """
    text = str(address).strip()
    if device_type == "Adb":
        if not text:
            raise ValueError("Adb address must not be empty")
        return text
    if device_type == "PlayCover":
        return canonicalize_ipv4_port(text)
    if device_type == "Linux":
        if not text:
            raise ValueError("Linux device address must not be empty")
        return text
    if device_type == "Win32":
        if not text.isdigit() or int(text) <= 0:
            raise ValueError("Win32 address must be a positive integer hWnd")
        return str(int(text))
    if device_type == "Gamepad":
        parts = text.split("|")
        if len(parts) != 2:
            raise ValueError("Gamepad address must be hWnd|type")
        hwnd_raw, type_raw = parts[0].strip(), parts[1].strip()
        if not hwnd_raw.isdigit() or int(hwnd_raw) <= 0:
            raise ValueError("Gamepad hWnd must be a positive integer")
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
