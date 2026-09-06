"""Tests for models/interface.py — Pydantic models for interface.json schema."""

import re

import pytest
from pydantic import ValidationError

from models.interface import (
    Controller,
    GamepadController,
    HotkeyCase,
    InterfaceModel,
    LinuxControllerConfig,
    MacOSController,
    Option,
    OptionCase,
    Resource,
    SettingSection,
    Win32Controller,
    _pipeline_override_contains_attach_option,
    validate_regex,
)


class _FakeFieldInfo:
    """A minimal stand-in for ValidationInfo (which is a Protocol and cannot be
    instantiated directly)."""

    def __init__(self, field_name: str = "test"):
        self.field_name = field_name
        self.config = None
        self.data = None
        self.context = None
        self.mode = "python"


# ---------------------------------------------------------------------------
# validate_regex helper
# ---------------------------------------------------------------------------


class TestValidateRegex:
    def test_none_passed_through(self):
        assert validate_regex(None, _FakeFieldInfo()) is None

    def test_valid_string_compiled(self):
        result = validate_regex(r"\d+", _FakeFieldInfo())
        assert isinstance(result, re.Pattern)
        assert result.match("123")

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError, match="无法编译为正则表达式"):
            validate_regex(r"[invalid", _FakeFieldInfo())


# ---------------------------------------------------------------------------
# _pipeline_override_contains_attach_option helper
# ---------------------------------------------------------------------------


class TestPipelineOverrideContainsAttachOption:
    def test_direct_attach(self):
        override = {"attach": {"my_option": "value"}}
        assert _pipeline_override_contains_attach_option(override, "my_option")

    def test_nested_attach(self):
        override = {"sub": {"attach": {"my_option": "value"}}}
        assert _pipeline_override_contains_attach_option(override, "my_option")

    def test_attach_not_present(self):
        assert not _pipeline_override_contains_attach_option(
            {"other": "value"}, "my_option"
        )

    def test_attach_wrong_key(self):
        assert not _pipeline_override_contains_attach_option(
            {"attach": {"other": "value"}}, "my_option"
        )

    def test_in_list(self):
        override = [{"attach": {"my_option": "value"}}]
        assert _pipeline_override_contains_attach_option(override, "my_option")

    def test_deeply_nested(self):
        override = {"a": {"b": {"c": [{"attach": {"my_option": 1}}]}}}
        assert _pipeline_override_contains_attach_option(override, "my_option")


# ---------------------------------------------------------------------------
# Win32Controller — regex compilation & method→int coercion
# ---------------------------------------------------------------------------


class TestWin32Controller:
    def test_regex_fields_compiled(self):
        ctrl = Win32Controller.model_validate(
            {"class_regex": r"^Qt.*", "window_regex": r".*MyApp.*"}
        )
        assert isinstance(ctrl.class_regex, re.Pattern)
        assert isinstance(ctrl.window_regex, re.Pattern)

    def test_string_method_converted_to_int(self):
        ctrl = Win32Controller(mouse="Seize", keyboard="SendMessage", screencap="GDI")
        assert ctrl.mouse == 1
        assert ctrl.keyboard == 2
        assert ctrl.screencap == 1

    def test_invalid_method_raises(self):
        with pytest.raises(ValidationError):
            Win32Controller.model_validate({"mouse": "InvalidMethod"})


# ---------------------------------------------------------------------------
# MacOSController
# ---------------------------------------------------------------------------


class TestMacOSController:
    def test_regex_field_compiled(self):
        ctrl = MacOSController.model_validate({"title_regex": r"^MyApp"})
        assert isinstance(ctrl.title_regex, re.Pattern)

    def test_invalid_input_raises(self):
        with pytest.raises(ValidationError):
            MacOSController.model_validate({"input": "Invalid"})


class TestLinuxControllerConfig:
    def test_invalid_screencap_rejected(self):
        with pytest.raises(ValidationError):
            LinuxControllerConfig(screencap="ExtImage")


# ---------------------------------------------------------------------------
# GamepadController — method→int coercion & defaults
# ---------------------------------------------------------------------------


class TestGamepadController:
    def test_regex_fields(self):
        ctrl = GamepadController.model_validate(
            {"class_regex": r".*", "window_regex": r".*"}
        )
        assert isinstance(ctrl.class_regex, re.Pattern)

    def test_gamepad_type_default_converted(self):
        """Default 'Xbox360' is converted to int 0 by method_to_int."""
        ctrl = GamepadController()
        assert ctrl.gamepad_type == 0

    def test_dualshock4_converted(self):
        ctrl = GamepadController(gamepad_type="DualShock4")
        assert ctrl.gamepad_type == 1

    def test_ds4_converted(self):
        ctrl = GamepadController(gamepad_type="DS4")
        assert ctrl.gamepad_type == 1

    def test_invalid_gamepad_type_raises(self):
        """Pydantic Literal validation rejects invalid type before method_to_int."""
        with pytest.raises(ValidationError, match="Xbox360.*DualShock4.*DS4"):
            GamepadController.model_validate({"gamepad_type": "InvalidType"})

    def test_screencap_converted_to_int(self):
        ctrl = GamepadController(screencap="GDI")
        assert ctrl.screencap == 1


# ---------------------------------------------------------------------------
# Controller — parametrized type tests & display field mutual exclusion
# ---------------------------------------------------------------------------


class TestController:
    @pytest.mark.parametrize(
        "ctrl_type", ["Adb", "Win32", "MacOS", "PlayCover", "Linux", "Gamepad"]
    )
    def test_valid_types(self, ctrl_type):
        ctrl = Controller(name="c", type=ctrl_type)
        assert ctrl.type == ctrl_type
        assert ctrl.name == "c"

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            Controller.model_validate({"name": "bad", "type": "InvalidType"})

    def test_display_short_side_and_long_side_mutual_exclusion(self):
        with pytest.raises(ValidationError, match="互斥"):
            Controller(
                name="c", type="Adb", display_short_side=1080, display_long_side=1920
            )

    def test_display_short_side_and_raw_mutual_exclusion(self):
        with pytest.raises(ValidationError, match="互斥"):
            Controller(name="c", type="Adb", display_short_side=1080, display_raw=True)

    def test_display_long_side_and_raw_mutual_exclusion(self):
        with pytest.raises(ValidationError, match="互斥"):
            Controller(name="c", type="Adb", display_long_side=1920, display_raw=True)

    def test_display_short_side_default_no_conflict(self):
        """Default 720 should not trigger conflict."""
        ctrl = Controller(name="c", type="Adb", display_long_side=1920)
        assert ctrl.display_long_side == 1920


# ---------------------------------------------------------------------------
# Option — type-specific validators
# ---------------------------------------------------------------------------


class TestOption:
    def test_select_requires_cases(self):
        with pytest.raises(ValidationError, match="cases 不能为空"):
            Option(type="select")

    def test_switch_requires_two_cases(self):
        with pytest.raises(ValidationError, match="必须有且仅有 2 个元素"):
            Option(type="switch", cases=[OptionCase(name="a")])

    def test_checkbox_requires_cases(self):
        with pytest.raises(ValidationError, match="cases 不能为空"):
            Option(type="checkbox")

    def test_checkbox_default_case_must_be_list(self):
        with pytest.raises(ValidationError, match="default_case 必须为字符串数组"):
            Option(type="checkbox", cases=[OptionCase(name="a")], default_case="a")

    def test_input_requires_inputs(self):
        with pytest.raises(ValidationError, match="inputs 不能为空"):
            Option(type="input")

    def test_hotkey_requires_hotkeys(self):
        with pytest.raises(
            ValidationError,
            match="当 type 为 hotkey 时，hotkeys 不能为空",
        ):
            Option(type="hotkey")

    def test_hotkey_accepts_hotkey_cases(self):
        option = Option(
            type="hotkey",
            hotkeys=[
                HotkeyCase(
                    name="attack",
                    label="Attack",
                    description="Attack shortcut",
                    default="Alt+A",
                )
            ],
        )
        assert option.hotkeys is not None
        assert option.hotkeys[0].name == "attack"
        assert option.hotkeys[0].default == "Alt+A"

    def test_scan_select_requires_scan_dir(self):
        with pytest.raises(ValidationError, match="scan_dir 不能为空"):
            Option(type="scan_select")

    def test_scan_select_requires_scan_filter(self):
        with pytest.raises(ValidationError, match="scan_filter 不能为空"):
            Option(type="scan_select", scan_dir="images")

    def test_scan_select_requires_pipeline_override(self):
        with pytest.raises(ValidationError, match="pipeline_override 不能为空"):
            Option(type="scan_select", scan_dir="images", scan_filter="*.png")

    def test_select_default_case_must_be_str(self):
        with pytest.raises(ValidationError, match="default_case 必须为字符串"):
            Option(type="select", cases=[OptionCase(name="a")], default_case=["a"])

    def test_switch_default_case_must_be_str(self):
        with pytest.raises(ValidationError, match="default_case 必须为字符串"):
            Option(
                type="switch",
                cases=[OptionCase(name="a"), OptionCase(name="b")],
                default_case=["a"],
            )


class TestHotkeyCase:
    def test_parses_metadata_and_optional_default(self):
        case = HotkeyCase(
            name="toggle",
            label="Toggle",
            description="Toggle feature",
            default="Ctrl+T",
        )
        assert case.name == "toggle"
        assert case.label == "Toggle"
        assert case.description == "Toggle feature"
        assert case.default == "Ctrl+T"


class TestSettingSection:
    def test_parses_metadata_and_options(self):
        section = SettingSection(
            name="general",
            label="General",
            description="General settings",
            icon="settings",
            option=["language", "shortcut"],
            default_expand=False,
        )
        assert section.name == "general"
        assert section.label == "General"
        assert section.description == "General settings"
        assert section.icon == "settings"
        assert section.option == ["language", "shortcut"]
        assert section.default_expand is False

    def test_default_expand_is_true(self):
        assert SettingSection(name="general").default_expand is True


# ---------------------------------------------------------------------------
# InterfaceModel — label/title defaults, import alias, scan_select placeholder
# ---------------------------------------------------------------------------


@pytest.fixture
def _base_iface_data():
    return {
        "interface_version": 2,
        "name": "Test",
        "controller": [Controller(name="adb", type="Adb")],
        "resource": [Resource(name="main", path=["resource"])],
    }


class TestInterfaceModel:
    def test_label_defaults_from_name(self, _base_iface_data):
        model = InterfaceModel(**_base_iface_data)
        assert model.label == "Test"

    def test_title_set_when_name_and_version_present(self, _base_iface_data):
        data = {**_base_iface_data, "label": "My Game", "version": "1.0.0"}
        model = InterfaceModel.model_validate(data)
        assert model.title == "Test 1.0.0"

    def test_import_alias(self, _base_iface_data):
        model = InterfaceModel(**_base_iface_data, **{"import": ["tasks.json5"]})
        assert model.import_ == ["tasks.json5"]

    def test_invalid_interface_version_raises(self, _base_iface_data):
        data = {k: v for k, v in _base_iface_data.items() if k != "interface_version"}
        with pytest.raises(ValidationError):
            InterfaceModel.model_validate({**data, "interface_version": 1})

    def test_controller_list_required(self, _base_iface_data):
        data = {k: v for k, v in _base_iface_data.items() if k != "controller"}
        with pytest.raises(ValidationError):
            InterfaceModel.model_validate({**data, "controller": "not_a_list"})

    def test_scan_select_pipeline_override_valid(self, _base_iface_data):
        """pipeline_override must contain the option name in any-level attach."""
        data = {
            **_base_iface_data,
            "option": {
                "skin": {
                    "type": "scan_select",
                    "scan_dir": "images",
                    "scan_filter": "*.png",
                    "pipeline_override": {"Action": {"attach": {"skin": "{{}}"}}},
                }
            },
        }
        model = InterfaceModel.model_validate(data)
        assert model.option is not None
        assert model.option["skin"].type == "scan_select"

    def test_scan_select_pipeline_override_missing_attach(self, _base_iface_data):
        data = {
            **_base_iface_data,
            "option": {
                "skin": {
                    "type": "scan_select",
                    "scan_dir": "images",
                    "scan_filter": "*.png",
                    "pipeline_override": {"Action": {}},
                }
            },
        }
        with pytest.raises(ValidationError, match="至少包含一次键"):
            InterfaceModel.model_validate(data)

    def test_scan_select_pipeline_override_wrong_key(self, _base_iface_data):
        data = {
            **_base_iface_data,
            "option": {
                "skin": {
                    "type": "scan_select",
                    "scan_dir": "images",
                    "scan_filter": "*.png",
                    "pipeline_override": {"attach": {"other_key": ""}},
                }
            },
        }
        with pytest.raises(ValidationError, match="至少包含一次键"):
            InterfaceModel.model_validate(data)

    def test_hotkey_default_rejects_more_than_two_modifiers(self, _base_iface_data):
        data = {
            **_base_iface_data,
            "option": {
                "shortcut": {
                    "type": "hotkey",
                    "hotkeys": [
                        {"name": "run", "default": "Ctrl+Alt+Shift+A"},
                    ],
                }
            },
        }

        with pytest.raises(ValidationError, match="最多支持两个修饰键"):
            InterfaceModel.model_validate(data)

    def test_hotkey_default_rejects_meta(self, _base_iface_data):
        data = {
            **_base_iface_data,
            "option": {
                "shortcut": {
                    "type": "hotkey",
                    "hotkeys": [
                        {"name": "run", "default": "Meta+A"},
                    ],
                }
            },
        }

        with pytest.raises(ValidationError, match="不支持 Meta/Command/Win"):
            InterfaceModel.model_validate(data)


# ---------------------------------------------------------------------------
# telemetry 配置（PI v2.9.2）
# ---------------------------------------------------------------------------


class TestTelemetryConfig:
    def _base(self) -> dict:
        return {
            "interface_version": 2,
            "name": "Test",
            "controller": [{"name": "adb", "type": "Adb"}],
            "resource": [{"name": "main", "path": ["resource"]}],
        }

    def test_blank_dsn_rejected(self):
        from models.interface import InterfaceModel

        data = self._base() | {"telemetry": {"sentry": {"dsn": "   "}}}
        with pytest.raises(Exception):
            InterfaceModel.model_validate(data)

    def test_sample_rate_out_of_range_rejected(self):
        from models.interface import InterfaceModel

        for bad in (1.5, -0.1):
            data = self._base() | {
                "telemetry": {
                    "sentry": {
                        "dsn": "https://key@example.com/42",
                        "traces_sample_rate": bad,
                    }
                }
            }
            with pytest.raises(Exception):
                InterfaceModel.model_validate(data)

    def test_sample_rate_nan_infinite_rejected(self):
        from models.interface import InterfaceModel

        for bad in (float("nan"), float("inf")):
            data = self._base() | {
                "telemetry": {
                    "sentry": {
                        "dsn": "https://key@example.com/42",
                        "failure_attachments_sample_rate": bad,
                    }
                }
            }
            with pytest.raises(Exception):
                InterfaceModel.model_validate(data)
