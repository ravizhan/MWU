"""Tests for models/task_config.py — config normalization and snapshot building."""

from typing import cast

import pytest

from models.interface import (
    Controller,
    HotkeyCase,
    InputCase,
    InterfaceModel,
    Option,
    OptionCase,
    Preset,
    PresetTask,
    Resource,
    Task,
)
from models.scheduler import PreTaskCommand
from models.task_config import (
    CUSTOM_PRESET_NAME,
    TaskConfigModel,
    TaskPresetSnapshotModel,
    _build_option_defaults,
    _build_task_option_maps,
    _clone_option_value,
    _normalize_option_value_for_storage,
    _normalize_options_for_task,
    _normalize_preset_name,
    _normalize_raw_pre_tasks,
    _normalize_raw_snapshot,
    _normalize_raw_task_options,
    build_interface_preset_snapshot,
    normalize_snapshot,
    normalize_task_config,
    normalize_task_execution_payload,
    normalize_task_options_by_task,
)

# ---------------------------------------------------------------------------
# Helpers for constructing test interfaces
# ---------------------------------------------------------------------------


def _make_interface(
    tasks=None, options=None, presets=None, resources=None, controllers=None
):
    return InterfaceModel(
        interface_version=2,
        name="Test",
        label="Test",
        controller=controllers or [Controller(name="adb", type="Adb")],
        resource=resources or [Resource(name="main", path=["resource"])],
        task=tasks or [],
        option=options or None,
        preset=presets or None,
    )


def _make_option(
    opt_type="select",
    cases=None,
    inputs=None,
    hotkeys=None,
    default_case=None,
    scan_dir=None,
    scan_filter=None,
    pipeline_override=None,
):
    return Option(
        type=opt_type,
        cases=[OptionCase(name=c) if isinstance(c, str) else c for c in (cases or [])],
        inputs=inputs,
        hotkeys=hotkeys,
        default_case=default_case,
        scan_dir=scan_dir,
        scan_filter=scan_filter,
        pipeline_override=pipeline_override,
    )


# ---------------------------------------------------------------------------
# _normalize_preset_name
# ---------------------------------------------------------------------------


class TestNormalizePresetName:
    def test_strips_whitespace(self):
        assert _normalize_preset_name("  QuickRun  ") == "QuickRun"

    def test_empty_string_falls_back(self):
        assert _normalize_preset_name("") == CUSTOM_PRESET_NAME

    def test_none_falls_back(self):
        assert _normalize_preset_name(None) == CUSTOM_PRESET_NAME

    def test_non_string_falls_back(self):
        assert _normalize_preset_name(42) == CUSTOM_PRESET_NAME


# ---------------------------------------------------------------------------
# _normalize_option_value_for_storage
# ---------------------------------------------------------------------------


class TestNormalizeOptionValueForStorage:
    def test_string(self):
        assert _normalize_option_value_for_storage("hello") == "hello"

    def test_string_list_filters_non_strings(self):
        assert _normalize_option_value_for_storage(["a", 1, "b"]) == ["a", "b"]

    def test_dict_filters_non_strings(self):
        assert _normalize_option_value_for_storage({"k": "v", 1: 2}) == {"k": "v"}

    def test_hotkey_value_storage_filters_non_strings(self):
        assert _normalize_option_value_for_storage(
            {"attack": "Alt+A", "invalid": 1}
        ) == {"attack": "Alt+A"}

    def test_invalid_type_returns_none(self):
        assert _normalize_option_value_for_storage(42) is None

    def test_none_returns_none(self):
        assert _normalize_option_value_for_storage(None) is None

    def test_empty_list(self):
        assert _normalize_option_value_for_storage([]) == []

    def test_empty_dict(self):
        assert _normalize_option_value_for_storage({}) == {}


# ---------------------------------------------------------------------------
# _normalize_raw_snapshot
# ---------------------------------------------------------------------------


class TestNormalizeRawSnapshot:
    def test_none(self):
        assert _normalize_raw_snapshot(None) == {
            "taskOrder": [],
            "taskChecked": {},
            "taskOptions": {},
            "preTasks": [],
        }

    def test_task_order_filters_non_strings(self):
        result = _normalize_raw_snapshot({"taskOrder": ["a", 1, "b"]})
        assert result["taskOrder"] == ["a", "b"]

    def test_model_instance(self):
        model = TaskPresetSnapshotModel(
            taskOrder=["a", "b"],
            taskChecked={"a": True},
            taskOptions={},
            preTasks=[],
        )
        result = _normalize_raw_snapshot(model)
        assert result["taskOrder"] == ["a", "b"]
        assert result["taskChecked"]["a"] is True

    def test_legacy_pre_tasks_key_is_ignored(self):
        result = _normalize_raw_snapshot({"pre_tasks": [{"command": "echo hi"}]})
        assert result["preTasks"] == []


# ---------------------------------------------------------------------------
# _normalize_raw_task_options
# ---------------------------------------------------------------------------


class TestNormalizeRawTaskOptions:
    def test_none_or_not_dict_returns_empty(self):
        assert _normalize_raw_task_options(None) == {}
        assert _normalize_raw_task_options("bad") == {}

    def test_valid(self):
        assert _normalize_raw_task_options({"task1": {"opt": "val"}}) == {
            "task1": {"opt": "val"}
        }

    def test_filters_non_string_option_name(self):
        assert _normalize_raw_task_options({"task1": {1: "val"}}) == {"task1": {}}

    def test_filters_invalid_values(self):
        assert _normalize_raw_task_options({"task1": {"opt": 42}}) == {"task1": {}}


# ---------------------------------------------------------------------------
# _normalize_raw_pre_tasks
# ---------------------------------------------------------------------------


class TestNormalizeRawPreTasks:
    def test_none_or_not_list_returns_empty(self):
        assert _normalize_raw_pre_tasks(None) == []
        assert _normalize_raw_pre_tasks("bad") == []

    def test_dict_items(self):
        result = _normalize_raw_pre_tasks([{"command": "echo hi"}])
        assert len(result) == 1
        assert result[0]["command"] == "echo hi"
        assert result[0]["enabled"] is True
        assert result[0]["timeout"] == 30

    def test_non_dict_skipped(self):
        """Non-dict, non-PreTaskCommand items in the list are silently skipped."""
        result = _normalize_raw_pre_tasks(["not_a_dict"])
        assert len(result) == 0

    def test_pre_task_command_model(self):
        pt = PreTaskCommand(command="echo hi", enabled=True, timeout=30)
        result = _normalize_raw_pre_tasks([pt])
        assert result[0]["command"] == "echo hi"
        assert result[0]["enabled"] is True

    def test_empty_command_included(self):
        """A dict with command='' passes isinstance(str) check and is included."""
        result = _normalize_raw_pre_tasks([{"command": ""}])
        assert len(result) == 1
        assert result[0]["command"] == ""


# ---------------------------------------------------------------------------
# _clone_option_value — proving copies are independent
# ---------------------------------------------------------------------------


class TestCloneOptionValue:
    def test_string_passthrough(self):
        assert _clone_option_value("hello") == "hello"

    def test_list_cloned_independently(self):
        original = ["a", "b"]
        cloned = _clone_option_value(original)
        assert isinstance(cloned, list)
        cloned.append("c")
        assert original == ["a", "b"]  # original unchanged
        assert cloned == ["a", "b", "c"]

    def test_list_filters_non_strings(self):
        assert _clone_option_value(cast(list[str], ["a", 1])) == ["a"]

    def test_dict_cloned_independently(self):
        original = {"k": "v"}
        cloned = _clone_option_value(original)
        assert isinstance(cloned, dict)
        cloned["new"] = "x"
        assert original == {"k": "v"}  # original unchanged
        assert cloned == {"k": "v", "new": "x"}

    def test_dict_filters_non_strings(self):
        assert _clone_option_value(cast(dict[str, str], {"k": 1})) == {}


# ---------------------------------------------------------------------------
# _build_option_defaults
# ---------------------------------------------------------------------------


class TestBuildOptionDefaults:
    def test_select_first_case_default(self):
        opt = _make_option("select", cases=["easy", "hard"])
        defaults, types = _build_option_defaults({"diff": opt})
        assert defaults["diff"] == "easy"
        assert types["diff"] == "string"

    def test_select_respects_default_case(self):
        opt = _make_option("select", cases=["easy", "hard"], default_case="hard")
        defaults, _ = _build_option_defaults({"diff": opt})
        assert defaults["diff"] == "hard"

    def test_switch_exact_default(self):
        """Switch defaults to the first case when no default_case given."""
        opt = _make_option("switch", cases=["on", "off"])
        defaults, _ = _build_option_defaults({"sw": opt})
        assert defaults["sw"] == "on"

    def test_checkbox_defaults(self):
        opt = _make_option("checkbox", cases=["a", "b", "c"], default_case=["a", "c"])
        defaults, types = _build_option_defaults({"multi": opt})
        assert set(defaults["multi"]) == {"a", "c"}
        assert types["multi"] == "string_list"

    def test_checkbox_no_default(self):
        opt = _make_option("checkbox", cases=["a", "b"])
        defaults, _ = _build_option_defaults({"multi": opt})
        assert defaults["multi"] == []

    def test_input_defaults(self):
        opt = _make_option("input", inputs=[InputCase(name="threshold", default="50")])
        defaults, types = _build_option_defaults({"inp": opt})
        assert defaults["inp"] == {"threshold": "50"}
        assert types["inp"] == "object"

    def test_input_no_defaults(self):
        opt = _make_option("input", inputs=[InputCase(name="threshold")])
        defaults, _ = _build_option_defaults({"inp": opt})
        assert defaults["inp"] == {"threshold": ""}

    def test_hotkey_defaults(self):
        opt = _make_option(
            "hotkey",
            hotkeys=[
                HotkeyCase(name="attack", default="Alt+A"),
                HotkeyCase(name="defend"),
            ],
        )
        defaults, types = _build_option_defaults({"combo": opt})
        assert defaults["combo"] == {"attack": "Alt+A", "defend": ""}
        assert types["combo"] == "object"

    def test_scan_select_treated_like_string(self):
        opt = _make_option(
            "scan_select",
            cases=["a", "b"],
            scan_dir="d",
            scan_filter="*",
            pipeline_override={"attach": {"ss": ""}},
        )
        defaults, types = _build_option_defaults({"ss": opt})
        assert defaults["ss"] == "a"
        assert types["ss"] == "string"


# ---------------------------------------------------------------------------
# _build_task_option_maps — recursive collection from OptionCase.option
# ---------------------------------------------------------------------------


class TestBuildTaskOptionMaps:
    def test_recursive_option_collection(self):
        """Options reachable through OptionCase.option are included."""
        sub_opt = _make_option("select", cases=["x", "y"])
        parent_opt = Option(
            type="select",
            cases=[OptionCase(name="sub", option=["sub_opt"])],
        )
        iface = _make_interface(
            tasks=[Task(name="T", entry="T", option=["parent_opt"])],
            options={"parent_opt": parent_opt, "sub_opt": sub_opt},
        )
        maps = _build_task_option_maps(iface)
        assert "parent_opt" in maps["T"]
        assert "sub_opt" in maps["T"]


# ---------------------------------------------------------------------------
# _normalize_options_for_task
# ---------------------------------------------------------------------------


class TestNormalizeOptionsForTask:
    def test_defaults_when_raw_is_none(self):
        opt = _make_option("select", cases=["a", "b"])
        defaults, types = _build_option_defaults({"opt": opt})
        case_sets = {o: {c.name for c in (op.cases or [])} for o, op in [("opt", opt)]}
        result = _normalize_options_for_task(
            None, {"opt": opt}, defaults, types, case_sets
        )
        assert result == {"opt": "a"}

    def test_invalid_type_ignored(self):
        opt = _make_option("select", cases=["a", "b"])
        defaults, types = _build_option_defaults({"opt": opt})
        case_sets = {o: {c.name for c in (op.cases or [])} for o, op in [("opt", opt)]}
        result = _normalize_options_for_task(
            {"opt": 42}, {"opt": opt}, defaults, types, case_sets
        )
        assert result == {"opt": "a"}

    def test_invalid_case_name_ignored(self):
        opt = _make_option("select", cases=["a", "b"])
        defaults, types = _build_option_defaults({"opt": opt})
        case_sets = {o: {c.name for c in (op.cases or [])} for o, op in [("opt", opt)]}
        result = _normalize_options_for_task(
            {"opt": "nonexistent"}, {"opt": opt}, defaults, types, case_sets
        )
        assert result == {"opt": "a"}

    def test_checkbox_valid(self):
        opt = _make_option("checkbox", cases=["a", "b", "c"])
        defaults, types = _build_option_defaults({"opt": opt})
        case_sets = {o: {c.name for c in (op.cases or [])} for o, op in [("opt", opt)]}
        result = _normalize_options_for_task(
            {"opt": ["a", "c"]}, {"opt": opt}, defaults, types, case_sets
        )
        assert result["opt"] == ["a", "c"]

    def test_checkbox_invalid_items_filtered(self):
        opt = _make_option("checkbox", cases=["a", "b"])
        defaults, types = _build_option_defaults({"opt": opt})
        case_sets = {o: {c.name for c in (op.cases or [])} for o, op in [("opt", opt)]}
        result = _normalize_options_for_task(
            {"opt": ["a", "x", "y"]}, {"opt": opt}, defaults, types, case_sets
        )
        assert result["opt"] == ["a"]

    def test_input_partial_update(self):
        opt = _make_option(
            "input", inputs=[InputCase(name="host"), InputCase(name="port")]
        )
        defaults, types = _build_option_defaults({"opt": opt})
        case_sets = {}
        result = _normalize_options_for_task(
            {"opt": {"host": "localhost"}}, {"opt": opt}, defaults, types, case_sets
        )
        opt_value = result["opt"]
        assert isinstance(opt_value, dict)
        assert opt_value["host"] == "localhost"
        assert opt_value["port"] == ""

    def test_hotkey_partial_update(self):
        opt = _make_option(
            "hotkey",
            hotkeys=[HotkeyCase(name="attack"), HotkeyCase(name="defend")],
        )
        defaults, types = _build_option_defaults({"combo": opt})
        result = _normalize_options_for_task(
            {"combo": {"attack": "Ctrl+A", "unknown": "ignored"}},
            {"combo": opt},
            defaults,
            types,
            {},
        )
        assert result["combo"] == {"attack": "Ctrl+A", "defend": ""}

    def test_unknown_option_key_ignored(self):
        opt = _make_option("select", cases=["a"])
        defaults, types = _build_option_defaults({"opt": opt})
        case_sets = {o: {c.name for c in (op.cases or [])} for o, op in [("opt", opt)]}
        result = _normalize_options_for_task(
            {"unknown": "val"}, {"opt": opt}, defaults, types, case_sets
        )
        assert "unknown" not in result
        assert result["opt"] == "a"


# ---------------------------------------------------------------------------
# normalize_task_options_by_task
# ---------------------------------------------------------------------------


class TestNormalizeTaskOptionsByTask:
    def test_basic(self):
        iface = _make_interface(
            tasks=[Task(name="T1", entry="T1", option=["diff"])],
            options={"diff": _make_option("select", cases=["a", "b"])},
        )
        result = normalize_task_options_by_task({"T1": {"diff": "b"}}, ["T1"], iface)
        assert result["T1"]["diff"] == "b"


# ---------------------------------------------------------------------------
# normalize_task_execution_payload
# ---------------------------------------------------------------------------


class TestNormalizeTaskExecutionPayload:
    def test_dedups_and_filters(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="TaskA"), Task(name="B", entry="TaskB")],
        )
        task_list, _, _ = normalize_task_execution_payload(
            ["A", "B", "A", "InvalidTask"],
            {},
            iface,
        )
        assert task_list == ["A", "B"]

    def test_orders_by_input_order(self):
        iface = _make_interface(
            tasks=[Task(name="B", entry="TaskB"), Task(name="A", entry="TaskA")],
        )
        task_list, _, _ = normalize_task_execution_payload(
            ["B", "A"],
            {},
            iface,
        )
        assert task_list == ["B", "A"]

    def test_normalizes_task_options(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="A", option=["diff"])],
            options={"diff": _make_option("select", cases=["easy", "hard"])},
        )
        _, options, _ = normalize_task_execution_payload(
            ["A"],
            {"A": {"diff": "hard"}},
            iface,
        )
        assert options["A"]["diff"] == "hard"

    def test_pre_tasks_enabled_filter(self):
        iface = _make_interface()
        _, _, pre_tasks = normalize_task_execution_payload(
            [],
            {},
            iface,
            raw_pre_tasks=[
                {"command": "echo ok", "enabled": True},
                {"command": "echo skip", "enabled": False},
                {"command": "", "enabled": True},
            ],
        )
        assert len(pre_tasks) == 1
        assert pre_tasks[0].command == "echo ok"


# ---------------------------------------------------------------------------
# normalize_snapshot
# ---------------------------------------------------------------------------


class TestNormalizeSnapshot:
    def test_empty_snapshot(self):
        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        result = normalize_snapshot(None, iface)
        assert "A" in result.taskOrder
        assert result.taskChecked["A"] is False

    def test_removes_invalid_task_ids(self):
        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        result = normalize_snapshot(
            {
                "taskOrder": ["A", "InvalidTask"],
                "taskChecked": {},
                "taskOptions": {},
            },
            iface,
        )
        assert "InvalidTask" not in result.taskOrder
        assert "A" in result.taskOrder

    def test_merges_default_tasks(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="TaskA"), Task(name="B", entry="TaskB")],
        )
        result = normalize_snapshot(
            {"taskOrder": ["B"], "taskChecked": {"B": True}, "taskOptions": {}},
            iface,
        )
        assert result.taskOrder == ["B", "A"]
        assert result.taskChecked["B"] is True
        assert result.taskChecked["A"] is False

    def test_deduplicates_duplicate_ids(self):
        """Duplicate task IDs in input are silently de-duped."""
        iface = _make_interface(tasks=[Task(name="A", entry="A")])
        result = normalize_snapshot(
            {"taskOrder": ["A", "A"], "taskChecked": {"A": True}, "taskOptions": {}},
            iface,
        )
        assert result.taskOrder == ["A"]
        assert result.taskOrder.count("A") == 1

    def test_preserves_normalized_pre_tasks(self):
        iface = _make_interface(tasks=[])
        result = normalize_snapshot(
            {
                "taskOrder": [],
                "taskChecked": {},
                "taskOptions": {},
                "preTasks": [{"command": "echo hello"}],
            },
            iface,
        )
        assert len(result.preTasks) == 1
        assert result.preTasks[0].command == "echo hello"


# ---------------------------------------------------------------------------
# build_interface_preset_snapshot
# ---------------------------------------------------------------------------


class TestBuildInterfacePresetSnapshot:
    def test_select_option_applied(self):
        """Preset applies a select option value."""
        iface = _make_interface(
            tasks=[Task(name="T", entry="T", option=["diff"])],
            options={"diff": _make_option("select", cases=["easy", "hard"])},
            presets=[
                Preset(name="P", task=[PresetTask(name="T", option={"diff": "hard"})])
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.taskOptions["T"]["diff"] == "hard"

    def test_checkbox_option_applied(self):
        """Preset applies a checkbox option value."""
        iface = _make_interface(
            tasks=[Task(name="T", entry="T", option=["mods"])],
            options={"mods": _make_option("checkbox", cases=["a", "b", "c"])},
            presets=[
                Preset(
                    name="P", task=[PresetTask(name="T", option={"mods": ["a", "c"]})]
                )
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert set(snapshot.taskOptions["T"]["mods"]) == {"a", "c"}

    def test_input_option_applied(self):
        """Preset applies an input option value."""
        iface = _make_interface(
            tasks=[Task(name="T", entry="T", option=["cfg"])],
            options={
                "cfg": _make_option(
                    "input", inputs=[InputCase(name="host"), InputCase(name="port")]
                )
            },
            presets=[
                Preset(
                    name="P",
                    task=[PresetTask(name="T", option={"cfg": {"host": "localhost"}})],
                )
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        cfg = snapshot.taskOptions["T"]["cfg"]
        assert isinstance(cfg, dict)
        assert cfg["host"] == "localhost"
        assert cfg["port"] == ""  # default preserved

    def test_hotkey_option_applied(self):
        """Preset applies a hotkey option value and preserves other defaults."""
        opt = _make_option(
            "hotkey",
            hotkeys=[HotkeyCase(name="attack"), HotkeyCase(name="defend")],
        )
        iface = _make_interface(
            tasks=[Task(name="T", entry="T", option=["combo"])],
            options={"combo": opt},
            presets=[
                Preset(
                    name="P",
                    task=[
                        PresetTask(
                            name="T",
                            option={"combo": {"attack": "Alt+A"}},
                        )
                    ],
                )
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        combo = snapshot.taskOptions["T"]["combo"]
        assert isinstance(combo, dict)
        assert combo["attack"] == "Alt+A"
        assert combo["defend"] == ""

    def test_enabled_false_stays_unchecked(self):
        """Preset task with enabled=False is unchecked."""
        iface = _make_interface(
            tasks=[Task(name="T", entry="T")],
            presets=[Preset(name="P", task=[PresetTask(name="T", enabled=False)])],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.taskChecked["T"] is False

    def test_duplicate_preset_tasks_deduped(self):
        """Duplicate task names in a preset are silently deduplicated (defensive)."""
        iface = _make_interface(
            tasks=[Task(name="A", entry="A")],
            presets=[
                Preset(name="P", task=[PresetTask(name="A"), PresetTask(name="A")])
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.taskOrder.count("A") == 1


# ---------------------------------------------------------------------------
# normalize_task_config — full flow
# ---------------------------------------------------------------------------


class TestNormalizeTaskConfig:
    def test_empty_config(self):
        iface = _make_interface(tasks=[Task(name="A", entry="A")])
        result = normalize_task_config(TaskConfigModel(), iface)
        assert CUSTOM_PRESET_NAME in result.presets
        assert result.selectedPreset == CUSTOM_PRESET_NAME

    def test_falls_back_to_custom_when_selected_missing(self):
        iface = _make_interface(tasks=[Task(name="A", entry="A")])
        result = normalize_task_config(
            TaskConfigModel(selectedPreset="NonExistent"), iface
        )
        assert result.selectedPreset == CUSTOM_PRESET_NAME

    def test_preserves_valid_selected_preset(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="A")],
            presets=[Preset(name="QuickRun")],
        )
        config = TaskConfigModel(selectedPreset="QuickRun")
        result = normalize_task_config(config, iface)
        assert result.selectedPreset == "QuickRun"

    def test_includes_interface_preset_when_absent_from_config(self):
        """Interface presets missing from saved config are built from scratch."""
        iface = _make_interface(
            tasks=[Task(name="A", entry="A")],
            presets=[Preset(name="QuickRun", task=[PresetTask(name="A")])],
        )
        config = TaskConfigModel(selectedPreset="QuickRun")
        result = normalize_task_config(config, iface)
        assert "QuickRun" in result.presets
        assert "A" in result.presets["QuickRun"].taskOrder


# ---------------------------------------------------------------------------
# TaskConfigModel model validation
# ---------------------------------------------------------------------------


class TestTaskConfigModel:
    def test_normalize_raw_config_strips_blank_selected_preset(self):
        model = TaskConfigModel.model_validate({"selectedPreset": "  "})
        assert model.selectedPreset == CUSTOM_PRESET_NAME

    def test_normalize_raw_config_ignores_non_string_preset_names(self):
        model = TaskConfigModel.model_validate({"presets": {1: {"taskOrder": []}}})
        assert model.presets == {}


# ---------------------------------------------------------------------------
# 任务身份切换（PI v2.9：name 为唯一身份）
# ---------------------------------------------------------------------------


class TestTaskIdentityName:
    def test_two_tasks_sharing_entry_get_separate_options(self):
        """两个 name 共用 entry：选项按 name 分别归一。"""
        iface = _make_interface(
            tasks=[
                Task(name="Slow", entry="Farm", option=["safety"]),
                Task(name="Fast", entry="Farm", option=["speed"]),
            ],
            options={
                "safety": _make_option("select", cases=["on"]),
                "speed": _make_option("select", cases=["high"]),
            },
        )
        result = normalize_task_options_by_task(
            {"Slow": {"safety": "on"}, "Fast": {"speed": "high"}},
            ["Slow", "Fast"],
            iface,
        )
        assert result["Slow"] == {"safety": "on"}
        assert result["Fast"] == {"speed": "high"}

    def test_default_order_uses_names_not_entries(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="TaskA"), Task(name="B", entry="TaskB")]
        )
        result = normalize_snapshot(None, iface)
        assert result.taskOrder == ["A", "B"]

    def test_unknown_names_reported_by_helper(self):
        from models.task_config import find_unknown_task_names

        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        assert find_unknown_task_names(iface, ["A", "B", "B", 42]) == ["B"]
        assert find_unknown_task_names(iface, ["A"]) == []

    def test_wrong_identity_marker_rejected(self):
        from pydantic import ValidationError

        # pydantic 将 model_validator 抛出的 TaskConfigFormatError 包装为 ValidationError
        with pytest.raises(ValidationError, match="taskIdentity"):
            TaskConfigModel.model_validate(
                {"taskIdentity": "entry", "selectedPreset": "x"}
            )

    def test_validate_task_config_identity_rejects_missing_marker(self):
        from models.task_config import (
            TaskConfigFormatError,
            validate_task_config_identity,
        )

        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        with pytest.raises(TaskConfigFormatError):
            validate_task_config_identity({"selectedPreset": "x"}, iface)

    def test_validate_task_config_identity_rejects_unknown_task_keys(self):
        from models.task_config import (
            TaskConfigFormatError,
            validate_task_config_identity,
        )

        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        # "TaskA" 是 entry 身份的旧键：必须拒绝
        with pytest.raises(TaskConfigFormatError):
            validate_task_config_identity(
                {
                    "taskIdentity": "name",
                    "presets": {
                        "__mwu_reserved_custom_preset__": {
                            "taskOrder": ["TaskA"],
                            "taskChecked": {},
                            "taskOptions": {},
                        }
                    },
                },
                iface,
            )

    def test_validate_task_config_identity_accepts_new_format(self):
        from models.task_config import validate_task_config_identity

        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        validate_task_config_identity(
            {
                "taskIdentity": "name",
                "presets": {
                    "__mwu_reserved_custom_preset__": {
                        "taskOrder": ["A"],
                        "taskChecked": {"A": True},
                        "taskOptions": {"A": {}},
                    }
                },
            },
            iface,
        )

    def test_new_task_appended_and_options_seeded_for_new_format(self):
        """严格切换不删除新格式任务：新增任务补缺省、新 option 补默认值。"""
        iface = _make_interface(
            tasks=[Task(name="A", entry="A", option=["diff"])],
            options={"diff": _make_option("select", cases=["x", "y"])},
        )
        config = TaskConfigModel(
            presets={
                CUSTOM_PRESET_NAME: {
                    "taskOrder": ["A"],
                    "taskChecked": {"A": True},
                    "taskOptions": {"A": {}},
                }
            }
        )
        result = normalize_task_config(config, iface)
        custom = result.presets[CUSTOM_PRESET_NAME]
        assert custom.taskOrder == ["A"]
        assert custom.taskOptions["A"] == {"diff": "x"}
