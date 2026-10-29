"""Tests for models/interface.py — Pydantic models for interface.json schema."""

import re

import pytest
from pydantic import ValidationError

from models.interface import (
    Controller,
    GamepadController,
    HotkeyCase,
    InterfaceModel,
    LinuxController,
    MacOSController,
    Option,
    OptionCase,
    Resource,
    Win32Controller,
    _pipeline_override_contains_attach_option,
    controller_method_ints,
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
    def test_absent(self):
        assert not _pipeline_override_contains_attach_option(
            {"other": "value"}, "my_option"
        )
        assert not _pipeline_override_contains_attach_option(
            {"attach": {"other": "value"}}, "my_option"
        )

    def test_deeply_nested_with_list(self):
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

    def test_methods_stay_strings(self):
        ctrl = Win32Controller(mouse="Seize", keyboard="SendMessage", screencap="GDI")
        assert ctrl.mouse == "Seize"
        assert ctrl.keyboard == "SendMessage"
        assert ctrl.screencap == "GDI"

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


class TestLinuxController:
    def test_full_config_fields(self):
        config = LinuxController(
            input="Wlr",
            screencap="PipeWire",
            pipewire_source="Portal",
            use_win32_vk_code=True,
        )
        controller = Controller(name="linux", type="Linux", linux=config)

        assert controller.linux is not None
        assert controller.linux.input == "Wlr"
        assert controller.linux.screencap == "PipeWire"
        assert controller.linux.pipewire_source == "Portal"
        assert controller.linux.use_win32_vk_code is True

    def test_defaults(self):
        config = LinuxController()

        assert config.input is None
        assert config.screencap is None
        assert config.pipewire_source == "Gamescope"
        assert config.use_win32_vk_code is False

    def test_libei_accepts_gamescope_pipewire(self):
        config = LinuxController(
            input="Libei", screencap="PipeWire", pipewire_source="Gamescope"
        )

        assert config.input == "Libei"

    def test_libei_rejects_wlr_screencap(self):
        with pytest.raises(ValidationError, match="Libei"):
            LinuxController(input="Libei", screencap="Wlr")

    def test_libei_rejects_portal_pipewire_source(self):
        with pytest.raises(ValidationError, match="Libei"):
            LinuxController(
                input="Libei", screencap="PipeWire", pipewire_source="Portal"
            )


# ---------------------------------------------------------------------------
# GamepadController — method→int coercion & defaults
# ---------------------------------------------------------------------------


class TestGamepadController:
    def test_regex_fields(self):
        ctrl = GamepadController.model_validate(
            {"class_regex": r".*", "window_regex": r".*"}
        )
        assert isinstance(ctrl.class_regex, re.Pattern)

    def test_values_stay_strings(self):
        ctrl = GamepadController(gamepad_type="DS4", screencap="GDI")
        assert ctrl.gamepad_type == "DS4"
        assert ctrl.screencap == "GDI"

    def test_default_gamepad_type_is_xbox360(self):
        assert GamepadController().gamepad_type == "Xbox360"

    def test_invalid_gamepad_type_raises(self):
        """Pydantic Literal validation rejects invalid type before method_to_int."""
        with pytest.raises(ValidationError, match="Xbox360.*DualShock4.*DS4"):
            GamepadController.model_validate({"gamepad_type": "InvalidType"})


class TestControllerMethodInts:
    def test_win32(self):
        ctrl = Controller(
            name="w",
            type="Win32",
            win32=Win32Controller(
                mouse="Seize", keyboard="SendMessage", screencap="GDI"
            ),
        )
        assert controller_method_ints(ctrl) == {
            "screencap": 1,
            "mouse": 1,
            "keyboard": 2,
        }

    def test_unset_fields_are_none(self):
        assert controller_method_ints(Win32Controller()) == {
            "screencap": None,
            "mouse": None,
            "keyboard": None,
        }

    def test_gamepad(self):
        ctrl = Controller(
            name="g",
            type="Gamepad",
            gamepad=GamepadController(gamepad_type="DS4", screencap="FramePool"),
        )
        assert controller_method_ints(ctrl) == {"screencap": 2, "gamepad_type": 1}

    def test_other_controller_type(self):
        assert controller_method_ints(Controller(name="a", type="Adb")) == {}


# ---------------------------------------------------------------------------
# Controller — parametrized type tests & display field mutual exclusion
# ---------------------------------------------------------------------------


class TestController:
    @pytest.mark.parametrize(
        "ctrl_type", ["Adb", "Win32", "MacOS", "PlayCover", "Gamepad"]
    )
    def test_valid_types(self, ctrl_type):
        ctrl = Controller(name="c", type=ctrl_type)
        assert ctrl.type == ctrl_type
        assert ctrl.name == "c"

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            Controller.model_validate({"name": "bad", "type": "InvalidType"})

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"display_short_side": 1080, "display_long_side": 1920},
            {"display_short_side": 1080, "display_raw": True},
            {"display_long_side": 1920, "display_raw": True},
        ],
    )
    def test_display_fields_mutual_exclusion(self, kwargs):
        with pytest.raises(ValidationError, match="互斥"):
            Controller(name="c", type="Adb", **kwargs)

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

    def test_checkbox_default_case_respects_counts(self):
        cases = [OptionCase(name="a"), OptionCase(name="b")]
        with pytest.raises(ValidationError, match="min_count / max_count"):
            Option(type="checkbox", cases=cases, default_case=[], min_count=1)

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

    def test_title_set_when_label_and_version_present(self, _base_iface_data):
        data = {**_base_iface_data, "label": "My Game", "version": "1.0.0"}
        model = InterfaceModel.model_validate(data)
        assert model.title == "My Game 1.0.0"

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

    @pytest.mark.parametrize(
        "default", ["Ctrl+Alt+Shift+A", "Meta+A", "Cmd+S", "Win+A"]
    )
    def test_hotkey_default_is_not_restricted_at_load(self, _base_iface_data, default):
        """default 只是用户捕获前的初值，合法性由运行时按键码映射判定。"""
        data = {
            **_base_iface_data,
            "option": {
                "shortcut": {
                    "type": "hotkey",
                    "hotkeys": [
                        {"name": "run", "default": default},
                    ],
                }
            },
        }

        model = InterfaceModel.model_validate(data)

        assert model.option is not None
        assert model.option["shortcut"].hotkeys is not None
        assert model.option["shortcut"].hotkeys[0].default == default
