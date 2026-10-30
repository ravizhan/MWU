"""Tests for models/task_config.py — config normalization and snapshot building."""

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
from models.task_config import (
    CUSTOM_PRESET_NAME,
    TaskConfigModel,
    _build_option_defaults,
    _build_task_option_maps,
    _clone_option_value,
    _normalize_option_value_for_storage,
    _normalize_options_for_task,
    _normalize_preset_name,
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
        assert _normalize_preset_name("") == ""

    def test_none_falls_back(self):
        assert _normalize_preset_name(None) == ""

    def test_non_string_falls_back(self):
        assert _normalize_preset_name(42) == ""


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
            "tasks": [],
            "taskOptions": {},
            "preTasks": [],
        }

    def test_tasks_filters_non_strings(self):
        result = _normalize_raw_snapshot({"tasks": ["a", 1, "b"]})
        assert result["tasks"] == ["a", "b"]


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
# _clone_option_value — proving copies are independent
# ---------------------------------------------------------------------------


class TestCloneOptionValue:
    def test_list_cloned_independently(self):
        original = ["a", "b"]
        cloned = _clone_option_value(original)
        assert isinstance(cloned, list)
        cloned.append("c")
        assert original == ["a", "b"]  # original unchanged
        assert cloned == ["a", "b", "c"]

    def test_dict_cloned_independently(self):
        original = {"k": "v"}
        cloned = _clone_option_value(original)
        assert isinstance(cloned, dict)
        cloned["new"] = "x"
        assert original == {"k": "v"}  # original unchanged
        assert cloned == {"k": "v", "new": "x"}


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

    def test_select_unknown_default_case_falls_back_to_first_case(self):
        opt = _make_option("select", cases=["easy", "hard"], default_case="missing")
        defaults, _ = _build_option_defaults({"diff": opt})
        assert defaults["diff"] == "easy"

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
            tasks=[Task(name="T", entry="EntryT", option=["parent_opt"])],
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

    def test_checkbox_out_of_count_range_falls_back_to_default(self):
        opt = Option(
            type="checkbox",
            cases=[OptionCase(name="a"), OptionCase(name="b")],
            default_case=["a"],
            max_count=1,
        )
        defaults, types = _build_option_defaults({"opt": opt})
        case_sets = {"opt": {"a", "b"}}
        result = _normalize_options_for_task(
            {"opt": ["a", "b"]}, {"opt": opt}, defaults, types, case_sets
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
            tasks=[Task(name="T1", entry="EntryT1", option=["diff"])],
            options={"diff": _make_option("select", cases=["a", "b"])},
        )
        result = normalize_task_options_by_task({"T1": {"diff": "b"}}, ["T1"], iface)
        assert result["T1"]["diff"] == "b"


# ---------------------------------------------------------------------------
# normalize_task_execution_payload
# ---------------------------------------------------------------------------


class TestNormalizeTaskExecutionPayload:
    def test_preserves_duplicates_and_filters(self):
        iface = _make_interface(
            tasks=[Task(name="A", entry="TaskA"), Task(name="B", entry="TaskB")],
        )
        task_list, _, _ = normalize_task_execution_payload(
            ["A", "B", "A", "InvalidTask"],
            {},
            iface,
        )
        assert task_list == ["A", "B", "A"]

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
            tasks=[Task(name="A", entry="EntryA", option=["diff"])],
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


@pytest.mark.parametrize(
    "raw_pre_tasks",
    [
        pytest.param(None, id="missing"),
        pytest.param("echo", id="not-a-list"),
        pytest.param(
            [{"command": "bad", "timeout": 0}, {"command": "ok", "timeout": 10}],
            id="invalid-item",
        ),
    ],
)
def test_persisted_config_with_bad_pre_tasks_still_loads(raw_pre_tasks):
    snapshot: dict = {"tasks": []}
    if raw_pre_tasks is not None:
        snapshot["preTasks"] = raw_pre_tasks

    config = TaskConfigModel.model_validate(
        {"selectedPreset": "", "presets": {"p": snapshot}}
    )

    expected = ["ok"] if isinstance(raw_pre_tasks, list) else []
    assert [p.command for p in config.presets["p"].preTasks] == expected


# ---------------------------------------------------------------------------
# normalize_snapshot
# ---------------------------------------------------------------------------


class TestNormalizeSnapshot:
    def test_empty_snapshot(self):
        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        result = normalize_snapshot(None, iface)
        assert result.tasks == []

    def test_removes_unknown_task_names(self):
        iface = _make_interface(tasks=[Task(name="A", entry="TaskA")])
        result = normalize_snapshot(
            {
                "tasks": ["A", "InvalidTask"],
                "taskOptions": {},
            },
            iface,
        )
        assert result.tasks == ["A"]

    def test_preserves_duplicate_names(self):
        """Duplicate task names in input remain separate queue instances."""
        iface = _make_interface(tasks=[Task(name="A", entry="EntryA")])
        result = normalize_snapshot(
            {"tasks": ["A", "A"], "taskOptions": {}},
            iface,
        )
        assert result.tasks == ["A", "A"]

    def test_preserves_normalized_pre_tasks(self):
        iface = _make_interface(tasks=[])
        result = normalize_snapshot(
            {
                "tasks": [],
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
    @pytest.mark.parametrize(
        ("option", "option_value", "expected"),
        [
            (
                _make_option("select", cases=["easy", "hard"]),
                "hard",
                "hard",
            ),
            (
                _make_option("checkbox", cases=["a", "b", "c"]),
                ["a", "c"],
                ["a", "c"],
            ),
            (
                _make_option(
                    "input", inputs=[InputCase(name="host"), InputCase(name="port")]
                ),
                {"host": "localhost"},
                {"host": "localhost", "port": ""},
            ),
            (
                _make_option(
                    "hotkey",
                    hotkeys=[HotkeyCase(name="attack"), HotkeyCase(name="defend")],
                ),
                {"attack": "Alt+A"},
                {"attack": "Alt+A", "defend": ""},
            ),
        ],
    )
    def test_option_value_applied(self, option, option_value, expected):
        iface = _make_interface(
            tasks=[Task(name="T", entry="EntryT", option=["opt"])],
            options={"opt": option},
            presets=[
                Preset(
                    name="P",
                    task=[PresetTask(name="T", option={"opt": option_value})],
                )
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.taskOptions["T"]["opt"] == expected

    def test_enabled_false_is_omitted(self):
        """Preset task with enabled=False is omitted from the queue."""
        iface = _make_interface(
            tasks=[Task(name="T", entry="EntryT")],
            presets=[Preset(name="P", task=[PresetTask(name="T", enabled=False)])],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.tasks == []

    def test_duplicate_preset_tasks_preserved(self):
        """Duplicate task names in a preset remain ordered queue instances."""
        iface = _make_interface(
            tasks=[Task(name="A", entry="EntryA")],
            presets=[
                Preset(name="P", task=[PresetTask(name="A"), PresetTask(name="A")])
            ],
        )
        snapshot = build_interface_preset_snapshot(iface, iface.preset[0])
        assert snapshot.tasks == ["A", "A"]


# ---------------------------------------------------------------------------
# normalize_task_config — full flow
# ---------------------------------------------------------------------------


class TestNormalizeTaskConfig:
    @pytest.mark.parametrize(
        ("selected", "has_presets", "expected"),
        [
            pytest.param("", False, CUSTOM_PRESET_NAME, id="no-interface-presets"),
            pytest.param("", True, "QuickRun", id="empty-selects-first"),
            pytest.param("Missing", True, "QuickRun", id="missing-selects-first"),
            pytest.param("QuickRun", True, "QuickRun", id="keeps-valid-selection"),
        ],
    )
    def test_selected_preset_selection(self, selected, has_presets, expected):
        iface = _make_interface(
            tasks=[Task(name="A", entry="EntryA")],
            presets=(
                [Preset(name="QuickRun"), Preset(name="Other")] if has_presets else None
            ),
        )
        result = normalize_task_config(TaskConfigModel(selectedPreset=selected), iface)
        assert result.selectedPreset == expected

    def test_includes_interface_preset_when_absent_from_config(self):
        """Interface presets missing from saved config are built from scratch."""
        iface = _make_interface(
            tasks=[Task(name="A", entry="EntryA")],
            presets=[Preset(name="QuickRun", task=[PresetTask(name="A")])],
        )
        config = TaskConfigModel(selectedPreset="QuickRun")
        result = normalize_task_config(config, iface)
        assert "QuickRun" in result.presets
        assert result.presets["QuickRun"].tasks == ["A"]


# ---------------------------------------------------------------------------
# TaskConfigModel model validation
# ---------------------------------------------------------------------------


class TestTaskConfigModel:
    def test_normalize_raw_config_strips_blank_selected_preset(self):
        model = TaskConfigModel.model_validate({"selectedPreset": "  "})
        assert model.selectedPreset == ""

    def test_normalize_raw_config_ignores_non_string_preset_names(self):
        model = TaskConfigModel.model_validate({"presets": {1: {"tasks": []}}})
        assert model.presets == {}
