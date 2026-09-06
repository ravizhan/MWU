"""Tests for hotkey conversion and pipeline override placeholders."""

from types import SimpleNamespace

import pytest

from maa_worker.hotkey import hotkey_value_to_codes, split_hotkey_combo
from maa_worker.pipeline_override import PipelineOverrideService
from models.interface import (
    Controller,
    HotkeyCase,
    LinuxControllerConfig,
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
            (" ALT + Shift + A ", ("A", ["ALT", "SHIFT"])),
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
        ],
    )
    def test_alt_a_uses_controller_key_map(self, controller_type, expected):
        assert hotkey_value_to_codes("ALT+A", controller_type) == expected

    def test_unknown_controller_type_rejected(self):
        with pytest.raises(ValueError, match="受支持的控制器类型"):
            hotkey_value_to_codes("ALT+A", "WlRoots")
        with pytest.raises(ValueError, match="受支持的控制器类型"):
            hotkey_value_to_codes("ALT+A", None)
        with pytest.raises(ValueError, match="受支持的控制器类型"):
            hotkey_value_to_codes("ALT+A", "UnknownController")

    def test_linux_use_win32_vk_code_uses_win32_table(self):
        assert hotkey_value_to_codes("ALT+A", "Linux", use_win32_vk_code=True) == (
            0x41,
            0x12,
            0,
        )

    def test_macos_uses_cgkeycode_table(self):
        # MacOS A=0 是有效 CGKeyCode，不能复用 Win32 值
        assert hotkey_value_to_codes("A", "MacOS") == (0, 0, 0)
        assert hotkey_value_to_codes("Ctrl+A", "MacOS") == (0, 59, 0)
        assert hotkey_value_to_codes("ENTER", "MacOS") == (36, 0, 0)
        assert hotkey_value_to_codes("F1", "MacOS") == (122, 0, 0)

    def test_macos_allows_command_modifier(self):
        assert hotkey_value_to_codes("Cmd+A", "MacOS") == (0, 55, 0)

    def test_unknown_key_raises_config_error(self):
        with pytest.raises(ValueError, match="不在 Win32 键码表中"):
            hotkey_value_to_codes("ALT+Unknown", "Win32")
        with pytest.raises(ValueError, match="不在 Win32 键码表中"):
            hotkey_value_to_codes("Unknown", "Win32")

    def test_empty_primary_raises(self):
        with pytest.raises(ValueError, match="主键为空"):
            hotkey_value_to_codes("", "Win32")

    def test_rejects_more_than_two_modifiers(self):
        with pytest.raises(ValueError, match="最多支持两个修饰键"):
            hotkey_value_to_codes("Ctrl+Alt+Shift+A", "Win32")

    @pytest.mark.parametrize("value", ["Meta+A", "Command+A", "Win+A", "Super+A"])
    def test_rejects_meta_aliases_non_macos(self, value):
        with pytest.raises(ValueError, match="不支持 Meta/Command/Win"):
            hotkey_value_to_codes(value, "Win32")
        with pytest.raises(ValueError, match="不支持 Meta/Command/Win"):
            hotkey_value_to_codes(value, "Linux")


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

    def test_bare_placeholder_is_primary(self):
        option = Option(
            type="hotkey",
            hotkeys=[HotkeyCase(name="FightCombo")],
            pipeline_override={"key": "{FightCombo}"},
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

        override = PipelineOverrideService(worker)._build_option_override(
            "K",
            {"K": {"FightCombo": "A"}},
            set(),
        )

        assert override == {"key": 0x41}

    def test_linux_use_win32_vk_code_emits_win32_codes(self):
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
                        name="linux",
                        type="Linux",
                        linux=LinuxControllerConfig(use_win32_vk_code=True),
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

    def test_macos_hotkey_primary_zero_is_valid(self):
        option = Option(
            type="hotkey",
            hotkeys=[HotkeyCase(name="Combo")],
            pipeline_override={"key": "{Combo.primary}"},
        )
        worker = SimpleNamespace(
            interface=SimpleNamespace(option={"K": option}),
            device=SimpleNamespace(
                get_active_controller_definitions=lambda: [
                    Controller(name="mac", type="MacOS")
                ]
            ),
            device_state=SimpleNamespace(current_resource_name=None),
        )

        override = PipelineOverrideService(worker)._build_option_override(
            "K",
            {"K": {"Combo": "A"}},
            set(),
        )

        assert override == {"key": 0}

    def test_invalid_hotkey_value_raises_with_option_and_field(self):
        option = Option(
            type="hotkey",
            hotkeys=[HotkeyCase(name="Combo")],
            pipeline_override={"key": "{Combo.primary}"},
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

        with pytest.raises(ValueError, match=r"选项 K 的快捷键字段 Combo"):
            PipelineOverrideService(worker)._build_option_override(
                "K",
                {"K": {"Combo": "NoSuchKey"}},
                set(),
            )


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
                    entry="Task",
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
