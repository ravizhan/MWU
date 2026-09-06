"""Tests for LinuxDeviceAddress validation and display-target exclusivity."""

import pytest
from pydantic import ValidationError

from models.device_address import (
    LinuxDeviceAddress,
    canonicalize_custom_device_address,
    canonicalize_runtime_device_address,
)
from models.interface import Controller


class TestLinuxDeviceAddressWlr:
    def test_valid_wlr(self):
        addr = LinuxDeviceAddress(
            kind="wlr", wlr_socket_path="/run/user/1000/wayland-1"
        )
        assert addr.wlr_socket_path == "/run/user/1000/wayland-1"

    def test_missing_socket_rejected(self):
        with pytest.raises(ValidationError, match="wlr_socket_path"):
            LinuxDeviceAddress(kind="wlr")

    def test_blank_socket_rejected(self):
        with pytest.raises(ValidationError, match="wlr_socket_path"):
            LinuxDeviceAddress(kind="wlr", wlr_socket_path="   ")

    def test_uinput_default_path_applied(self):
        addr = LinuxDeviceAddress(
            kind="wlr",
            wlr_socket_path="/run/user/1000/wayland-1",
            uinput_screen_width=1920,
            uinput_screen_height=1080,
        )
        assert addr.uinput_path == "/dev/uinput"


class TestLinuxDeviceAddressGamescope:
    def test_valid_zero_display(self):
        addr = LinuxDeviceAddress(kind="gamescope", display_no=0)
        assert addr.display_no == 0

    def test_negative_display_rejected(self):
        with pytest.raises(ValidationError, match="display_no"):
            LinuxDeviceAddress(kind="gamescope", display_no=-1)

    def test_missing_display_rejected(self):
        with pytest.raises(ValidationError, match="display_no"):
            LinuxDeviceAddress(kind="gamescope")


class TestLinuxDeviceAddressPortal:
    def test_kind_only_allowed(self):
        addr = LinuxDeviceAddress(kind="portal")
        assert addr.kind == "portal"

    def test_portal_with_eis_path_allowed(self):
        addr = LinuxDeviceAddress(
            kind="portal", eis_socket_path="/run/user/1000/gamescope-0-ei"
        )
        assert addr.eis_socket_path == "/run/user/1000/gamescope-0-ei"


class TestLinuxDeviceAddressStrictness:
    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs"):
            LinuxDeviceAddress.model_validate(
                {
                    "kind": "wlr",
                    "wlr_socket_path": "/run/user/1000/wayland-1",
                    "pw_node_id": 5,
                }
            )

    def test_compact_json_serialization_key_sorted(self):
        addr = LinuxDeviceAddress(
            kind="gamescope",
            display_no=2,
            uinput_screen_width=2560,
            uinput_screen_height=1440,
        )
        text = addr.to_compact_json()
        assert text == (
            '{"display_no": 2, "kind": "gamescope", "uinput_path": "/dev/uinput",'
            ' "uinput_screen_height": 1440, "uinput_screen_width": 2560}'
        )
        # round-trip
        assert LinuxDeviceAddress.from_compact_json(text).to_compact_json() == text

    def test_uinput_width_zero_rejected(self):
        with pytest.raises(ValidationError, match="UInput"):
            LinuxDeviceAddress(
                kind="wlr",
                wlr_socket_path="/run/user/1000/wayland-1",
                uinput_screen_width=0,
                uinput_screen_height=1080,
            )


class TestCanonicalizeLinux:
    def test_custom_canonical_key_order(self):
        text = canonicalize_custom_device_address(
            "Linux",
            '{"kind": "wlr", "wlr_socket_path": "/run/user/1000/wayland-1"}',
        )
        assert text == '{"kind": "wlr", "wlr_socket_path": "/run/user/1000/wayland-1"}'

    def test_runtime_canonical_key_order(self):
        text = canonicalize_runtime_device_address(
            "Linux",
            '{"kind": "gamescope", "display_no": 0}',
        )
        assert text == '{"display_no": 0, "kind": "gamescope"}'

    def test_non_object_json_rejected(self):
        for bad in ('"x"', "42", "[]", "null"):
            with pytest.raises(ValueError):
                canonicalize_runtime_device_address("Linux", bad)

    def test_invalid_json_rejected(self):
        with pytest.raises(ValueError):
            canonicalize_runtime_device_address("Linux", "{broken")


class TestDisplayTargetMutualExclusionByExplicitness:
    def test_explicit_short_720_with_long_conflict(self):
        with pytest.raises(ValidationError, match="互斥"):
            Controller(
                name="c",
                type="Adb",
                display_short_side=720,
                display_long_side=1920,
            )

    def test_explicit_short_720_alone_is_allowed(self):
        ctrl = Controller(name="c", type="Adb", display_short_side=720)
        assert ctrl.display_short_side == 720

    def test_explicit_short_720_with_raw_conflict(self):
        with pytest.raises(ValidationError, match="互斥"):
            Controller(
                name="c",
                type="Adb",
                display_short_side=720,
                display_raw=True,
            )
