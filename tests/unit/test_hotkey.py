"""Tests for hotkey conversion and pipeline override placeholders."""

from types import SimpleNamespace

import pytest

from maa_worker.hotkey import hotkey_value_to_codes, split_hotkey_combo
from maa_worker.pipeline_override import PipelineOverrideService
from models.interface import (
    Controller,
    HotkeyCase,
    LinuxController,
    Option,
    OptionCase,
)


class TestSplitHotkeyCombo:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("", ("", [])),
            (" + ", ("", [])),
            ("A", ("A", [])),
            (" ALT + Shift + A ", ("A", ["ALT", "Shift"])),
        ],
    )
    def test_primary_is_last_nonempty_part(self, value, expected):
        assert split_hotkey_combo(value) == expected


class TestHotkeyValueToCodes:
    @pytest.mark.parametrize(
        ("controller_type", "expected"),
        [
            ("Win32", (0x41, 0x12, 0)),
            ("Adb", (29, 57, 0)),
            ("Linux", (30, 56, 0)),
            ("MacOS", (0x00, 0x3A, 0)),
            (None, (0x41, 0x12, 0)),
            ("UnknownController", (0x41, 0x12, 0)),
        ],
    )
    def test_alt_a_uses_controller_key_map(self, controller_type, expected):
        assert hotkey_value_to_codes("ALT+A", controller_type) == expected

    def test_empty_value_uses_zero_codes(self):
        assert hotkey_value_to_codes("", "Win32") == (0, 0, 0)

    @pytest.mark.parametrize("value", ["ALT+Unknown", ";", "F13"])
    def test_unsupported_key_is_rejected(self, value):
        with pytest.raises(ValueError, match="未知快捷键"):
            hotkey_value_to_codes(value, "Win32")

    def test_rejects_more_than_two_modifiers(self):
        with pytest.raises(ValueError, match="最多支持两个修饰键"):
            hotkey_value_to_codes("Ctrl+Alt+Shift+A", "Win32")

    @pytest.mark.parametrize("value", ["Meta+A", "Command+A", "Win+A", "Super+A"])
    def test_meta_aliases_use_controller_meta_code(self, value):
        assert hotkey_value_to_codes(value, "Win32") == (0x41, 0x5B, 0)
        assert hotkey_value_to_codes(value, "Adb") == (29, 117, 0)
        assert hotkey_value_to_codes(value, "Linux") == (30, 125, 0)
        assert hotkey_value_to_codes(value, "MacOS") == (0x00, 0x37, 0)

    @pytest.mark.parametrize(
        ("controller_type", "expected"),
        [
            ("Win32", (0xBA, 0, 0)),
            ("Adb", (74, 0, 0)),
            ("Linux", (39, 0, 0)),
            ("MacOS", (0x29, 0, 0)),
        ],
    )
    def test_symbol_keys_use_controller_key_map(self, controller_type, expected):
        assert hotkey_value_to_codes("SEMICOLON", controller_type) == expected

    @pytest.mark.parametrize(
        ("controller_type", "expected"),
        [
            ("Win32", (0x65, 0, 0)),
            ("Adb", (149, 0, 0)),
            ("Linux", (76, 0, 0)),
            ("MacOS", (0x57, 0, 0)),
        ],
    )
    def test_numpad_keys_use_controller_key_map(self, controller_type, expected):
        assert hotkey_value_to_codes("NUMPAD5", controller_type) == expected

    def test_playcover_rejects_key_operations(self):
        with pytest.raises(ValueError, match="PlayCover 控制器不支持按键操作"):
            hotkey_value_to_codes("A", "PlayCover")

    def test_gamepad_uses_button_codes(self):
        assert hotkey_value_to_codes("A", "Gamepad") == (0x1000, 0, 0)
        assert hotkey_value_to_codes("UP", "Gamepad") == (0x0001, 0, 0)

    def test_gamepad_rejects_modifiers(self):
        with pytest.raises(ValueError, match="Gamepad 控制器不支持组合键"):
            hotkey_value_to_codes("Ctrl+A", "Gamepad")


class TestPipelineOverrideHotkey:
    def test_replaces_modifier_and_primary_placeholders_with_integers(self):
        option = Option(
            type="hotkey",
            hotkeys=[HotkeyCase(name="FightCombo")],
            pipeline_override={
                "key": [
                    "{FightCombo.modifier1}",
                    "{FightCombo.primary}",
                ]
            },
        )
        worker = SimpleNamespace(
            interface=SimpleNamespace(option={"K": option}),
            device=SimpleNamespace(
                get_active_controller_definitions=lambda: [
                    Controller(name="win", type="Win32")
                ]
            ),
            device_state=SimpleNamespace(current_resource_name=None),
        )
        service = PipelineOverrideService(worker)

        override = service._build_option_override(
            "K",
            {"K": {"FightCombo": "ALT+A"}},
            set(),
        )

        assert override == {"key": [0x12, 0x41]}

    def test_linux_can_emit_win32_virtual_key_codes(self):
        option = Option(
            type="hotkey",
            hotkeys=[HotkeyCase(name="FightCombo")],
            pipeline_override={"key": "{FightCombo.primary}"},
        )
        worker = SimpleNamespace(
            interface=SimpleNamespace(option={"K": option}),
            device=SimpleNamespace(
                get_active_controller_definitions=lambda: [
                    Controller(
                        name="wlr",
                        type="Linux",
                        linux=LinuxController(use_win32_vk_code=True),
                    )
                ]
            ),
            device_state=SimpleNamespace(current_resource_name=None),
        )

        override = PipelineOverrideService(worker)._build_option_override(
            "K",
            {"K": {"FightCombo": "A"}},
            set(),
        )

        assert override == {"key": 0x41}


def test_saved_global_value_is_not_shadowed_by_task_default():
    global_option = Option(
        type="select",
        cases=[
            OptionCase(name="default", pipeline_override={"Node": {"mode": "default"}}),
            OptionCase(name="saved", pipeline_override={"Node": {"mode": "saved"}}),
        ],
        default_case="default",
    )
    worker = SimpleNamespace(
        interface=SimpleNamespace(
            option={"GlobalMode": global_option},
            global_option=["GlobalMode"],
            task=[
                SimpleNamespace(
                    name="Task",
                    entry="EntryTask",
                    pipeline_override={},
                    option=[],
                )
            ],
        ),
        device=SimpleNamespace(
            get_active_controller_names=lambda: set(),
            get_active_controller_definitions=lambda: [],
            get_current_resource_definition=lambda: None,
        ),
        device_state=SimpleNamespace(current_resource_name=None),
    )

    override = PipelineOverrideService(worker).build_task_pipeline_override(
        "Task",
        {"GlobalMode": "default"},
        {"GlobalMode": "saved"},
    )

    assert override == {"Node": {"mode": "saved"}}
