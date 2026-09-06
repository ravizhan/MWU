"""Tests for models/interface_loader.py — interface loading, merging, scanning."""

import json as stdlib_json
from pathlib import Path

import pytest

from models.interface import InterfaceModel
from models.interface_loader import (
    InterfaceLoadError,
    _expand_scan_select_options,
    _MergeState,
    _normalize_import_list,
    _normalize_root_relative_path,
    _read_json_dict,
    _validate_options,
    _register_presets,
    _register_tasks,
    _resolve_import_path,
    _scan_scan_select_cases,
    _validate_importable_fragment,
    load_interface_model,
    rescan_scan_select_option,
    resolve_interface_relative_path,
)

# ---------------------------------------------------------------------------
# _normalize_root_relative_path — path safety
# ---------------------------------------------------------------------------


class TestNormalizeRootRelativePath:
    def test_normal_path(self):
        assert (
            _normalize_root_relative_path("resource/sub", field_name="p")
            == "resource/sub"
        )

    def test_backslash_normalized(self):
        assert (
            _normalize_root_relative_path(r"resource\sub", field_name="p")
            == "resource/sub"
        )

    def test_stripped(self):
        assert (
            _normalize_root_relative_path("  resource  ", field_name="p") == "resource"
        )

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            _normalize_root_relative_path("", field_name="p")
        # whitespace-only also collapses to empty
        with pytest.raises(ValueError, match="不能为空"):
            _normalize_root_relative_path("   ", field_name="p")

    def test_absolute_unix_raises(self):
        with pytest.raises(ValueError, match="不允许使用绝对路径"):
            _normalize_root_relative_path("/etc/passwd", field_name="p")

    def test_absolute_windows_raises(self):
        with pytest.raises(ValueError, match="不允许使用绝对路径"):
            _normalize_root_relative_path("C:\\windows", field_name="p")

    def test_dot_raises(self):
        with pytest.raises(ValueError, match="不允许包含"):
            _normalize_root_relative_path(".", field_name="p")

    def test_dotdot_raises(self):
        with pytest.raises(ValueError, match="不允许包含"):
            _normalize_root_relative_path("..", field_name="p")

    def test_dotdot_in_middle_raises(self):
        with pytest.raises(ValueError, match="不允许包含"):
            _normalize_root_relative_path("a/../b", field_name="p")

    def test_empty_segment_raises(self):
        with pytest.raises(ValueError, match="不允许包含"):
            _normalize_root_relative_path("a//b", field_name="p")


# ---------------------------------------------------------------------------
# _resolve_import_path
# ---------------------------------------------------------------------------


class TestResolveImportPath:
    def test_valid(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "tasks.json5").write_text("{}")
        result = _resolve_import_path("sub/tasks.json5", tmp_path)
        assert result == (tmp_path / "sub" / "tasks.json5").resolve()

    def test_traversal_raises(self, tmp_path):
        with pytest.raises(ValueError, match="不允许包含"):
            _resolve_import_path("../other.json5", tmp_path)


# ---------------------------------------------------------------------------
# resolve_interface_relative_path
# ---------------------------------------------------------------------------


class TestResolveInterfaceRelativePath:
    def test_valid_file(self, tmp_path):
        (tmp_path / "config.json5").write_text("{}")
        result = resolve_interface_relative_path(tmp_path, "config.json5")
        assert result == (tmp_path / "config.json5").resolve()

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="不存在"):
            resolve_interface_relative_path(tmp_path, "missing.json5")

    def test_traversal_raises(self, tmp_path):
        with pytest.raises(ValueError, match="不允许包含"):
            resolve_interface_relative_path(tmp_path, "../outside.txt")

    def test_file_not_dir(self, tmp_path):
        (tmp_path / "afile.txt").write_text("x")
        with pytest.raises(ValueError, match="不是目录"):
            resolve_interface_relative_path(
                tmp_path, "afile.txt", allow_directories=True
            )

    def test_dir_ok(self, tmp_path):
        (tmp_path / "somedir").mkdir()
        result = resolve_interface_relative_path(
            tmp_path, "somedir", allow_directories=True
        )
        assert result == (tmp_path / "somedir").resolve()


# ---------------------------------------------------------------------------
# _read_json_dict
# ---------------------------------------------------------------------------


class TestReadJsonDict:
    def test_valid_json5(self, tmp_path):
        p = tmp_path / "test.json5"
        p.write_text("{a: 1,}")
        assert _read_json_dict(p) == {"a": 1}

    def test_missing_file(self, tmp_path):
        with pytest.raises(InterfaceLoadError, match="找不到配置文件"):
            _read_json_dict(tmp_path / "nope.json")

    def test_malformed_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{invalid}")
        with pytest.raises(InterfaceLoadError, match="解析配置文件失败"):
            _read_json_dict(p)

    def test_non_dict_root(self, tmp_path):
        p = tmp_path / "arr.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(InterfaceLoadError, match="必须是 JSON 对象"):
            _read_json_dict(p)


# ---------------------------------------------------------------------------
# _normalize_import_list
# ---------------------------------------------------------------------------


class TestNormalizeImportList:
    def test_none(self):
        assert _normalize_import_list(None, Path()) == []

    def test_valid(self):
        assert _normalize_import_list(["a.json5", "b.json5"], Path()) == [
            "a.json5",
            "b.json5",
        ]

    def test_not_list_raises(self):
        with pytest.raises(InterfaceLoadError, match="非空字符串数组"):
            _normalize_import_list("bad", Path())

    def test_empty_string_raises(self):
        with pytest.raises(InterfaceLoadError, match="非空字符串数组"):
            _normalize_import_list([""], Path())

    def test_non_string_raises(self):
        with pytest.raises(InterfaceLoadError, match="非空字符串数组"):
            _normalize_import_list([42], Path())


# ---------------------------------------------------------------------------
# _validate_importable_fragment
# ---------------------------------------------------------------------------


class TestValidateImportableFragment:
    def test_one_invalid_key(self):
        with pytest.raises(InterfaceLoadError, match="非法字段.*extra"):
            _validate_importable_fragment({"task": [], "extra": 1}, Path())

    def test_multiple_invalid_keys_sorted(self):
        """Invalid keys are reported in sorted order."""
        with pytest.raises(InterfaceLoadError, match=r"非法字段.*(?:a.*z|z.*a)"):
            _validate_importable_fragment({"z": 1, "a": 2, "task": []}, Path())


# ---------------------------------------------------------------------------
# _register_tasks — conflict detection
# ---------------------------------------------------------------------------


class TestRegisterTasks:
    def test_not_list_raises(self):
        with pytest.raises(InterfaceLoadError, match="必须是数组"):
            _register_tasks("bad", Path(), _MergeState())

    def test_name_not_string_raises(self):
        with pytest.raises(InterfaceLoadError, match="必须是非空字符串"):
            _register_tasks([{"name": 1, "entry": "E"}], Path(), _MergeState())

    def test_entry_empty_raises(self):
        with pytest.raises(InterfaceLoadError, match="必须是非空字符串"):
            _register_tasks([{"name": "A", "entry": ""}], Path(), _MergeState())

    def test_name_conflict(self):
        state = _MergeState()
        _register_tasks([{"name": "A", "entry": "E1"}], Path("/a.json"), state)
        with pytest.raises(InterfaceLoadError, match="冲突"):
            _register_tasks([{"name": "A", "entry": "E2"}], Path("/b.json"), state)


# ---------------------------------------------------------------------------
# _validate_options — 结构校验
# ---------------------------------------------------------------------------


class TestValidateOptions:
    def test_not_dict_raises(self):
        with pytest.raises(InterfaceLoadError, match="必须是对象"):
            _validate_options([], Path())

    def test_empty_key_raises(self):
        with pytest.raises(InterfaceLoadError, match="必须是非空字符串"):
            _validate_options({"": {"type": "select"}}, Path())


# ---------------------------------------------------------------------------
# _register_presets — conflict detection
# ---------------------------------------------------------------------------


class TestRegisterPresets:
    def test_not_list_raises(self):
        with pytest.raises(InterfaceLoadError, match="必须是数组"):
            _register_presets("bad", Path(), _MergeState())

    def test_conflict(self):
        state = _MergeState()
        _register_presets([{"name": "P"}], Path("/a.json"), state)
        with pytest.raises(InterfaceLoadError, match="冲突"):
            _register_presets([{"name": "P"}], Path("/b.json"), state)


# ---------------------------------------------------------------------------
# _scan_scan_select_cases
# ---------------------------------------------------------------------------


class TestScanScanSelectCases:
    def test_raises_if_cases_prefilled(self):
        with pytest.raises(InterfaceLoadError, match="不允许预置 cases"):
            _scan_scan_select_cases(
                "opt",
                {"cases": [{"name": "a"}], "scan_dir": ".", "scan_filter": "*"},
                Path(),
            )

    def test_missing_scan_dir(self):
        with pytest.raises(InterfaceLoadError, match="scan_dir 必须为非空字符串"):
            _scan_scan_select_cases("opt", {"scan_dir": "", "scan_filter": "*"}, Path())

    def test_missing_scan_filter(self):
        with pytest.raises(InterfaceLoadError, match="scan_filter 必须为非空字符串"):
            _scan_scan_select_cases("opt", {"scan_dir": ".", "scan_filter": ""}, Path())

    def test_scan_dir_not_exist(self, tmp_path):
        with pytest.raises(InterfaceLoadError, match="不存在或不是目录"):
            _scan_scan_select_cases(
                "opt", {"scan_dir": "nonexistent", "scan_filter": "*"}, tmp_path
            )

    def test_returns_matched_files(self, tmp_path):
        imgs = tmp_path / "images"
        imgs.mkdir()
        (imgs / "icon1.png").write_text("x")
        (imgs / "icon2.png").write_text("x")
        (imgs / "readme.txt").write_text("x")

        result = _scan_scan_select_cases(
            "opt", {"scan_dir": "images", "scan_filter": "*.png"}, tmp_path
        )
        assert len(result) == 2
        names = {c["name"] for c in result}
        assert names == {"icon1.png", "icon2.png"}


# ---------------------------------------------------------------------------
# _expand_scan_select_options
# ---------------------------------------------------------------------------


class TestExpandScanSelectOptions:
    def test_non_scan_select_untouched(self, tmp_path):
        data = {"option": {"diff": {"type": "select", "cases": [{"name": "a"}]}}}
        _expand_scan_select_options(data, tmp_path)
        assert data["option"]["diff"]["cases"] == [{"name": "a"}]


# ---------------------------------------------------------------------------
# rescan_scan_select_option
# ---------------------------------------------------------------------------


class TestRescanScanSelectOption:
    def test_nonexistent_option_raises(self, tmp_path):
        iface = InterfaceModel.model_validate(
            {
                "interface_version": 2,
                "name": "T",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "r", "path": ["resource"]}],
            }
        )
        with pytest.raises(InterfaceLoadError, match="不存在"):
            rescan_scan_select_option(iface, "no_such_option", tmp_path)

    def test_wrong_type_raises(self, tmp_path):
        iface = InterfaceModel.model_validate(
            {
                "interface_version": 2,
                "name": "T",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "r", "path": ["resource"]}],
                "option": {"diff": {"type": "select", "cases": [{"name": "a"}]}},
            }
        )
        with pytest.raises(InterfaceLoadError, match="不是 scan_select"):
            rescan_scan_select_option(iface, "diff", tmp_path)

    def test_rescan_populates_cases(self, tmp_path):
        imgs = tmp_path / "images"
        imgs.mkdir()
        (imgs / "skin_1.png").write_text("x")
        (imgs / "skin_2.png").write_text("x")

        iface_data = {
            "interface_version": 2,
            "name": "T",
            "controller": [{"name": "adb", "type": "Adb"}],
            "resource": [{"name": "r", "path": ["resource"]}],
            "option": {
                "skin": {
                    "type": "scan_select",
                    "scan_dir": "images",
                    "scan_filter": "*.png",
                    "pipeline_override": {"attach": {"skin": ""}},
                }
            },
        }
        iface = InterfaceModel.model_validate(iface_data)
        scanned = rescan_scan_select_option(iface, "skin", tmp_path)
        assert len(scanned) == 2
        assert {c["name"] for c in scanned} == {"skin_1.png", "skin_2.png"}
        assert iface.option is not None
        assert iface.option["skin"].cases is not None
        assert len(iface.option["skin"].cases) == 2


# ---------------------------------------------------------------------------
# load_interface_model — integration tests
# ---------------------------------------------------------------------------


def _write_interface(base_dir: Path, data: dict):
    (base_dir / "interface.json").write_text(stdlib_json.dumps(data))


class TestLoadInterfaceModel:
    def test_no_interface_json(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        with pytest.raises(InterfaceLoadError, match="找不到配置文件"):
            load_interface_model(empty_dir)

    def test_minimal_interface(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
            },
        )
        model = load_interface_model(tmp_path)
        assert model.name == "Test"

    def test_invalid_interface_version(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 1,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="校验 interface 配置失败"):
            load_interface_model(tmp_path)

    def test_nonexistent_imports_raises(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "import": ["missing.json5"],
            },
        )
        with pytest.raises(InterfaceLoadError, match="找不到配置文件"):
            load_interface_model(tmp_path)

    def test_import_file_loaded(self, tmp_path):
        (tmp_path / "tasks.json5").write_text(
            '{task: [{name: "Extra", entry: "Extra"}]}'
        )
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "import": ["tasks.json5"],
            },
        )
        model = load_interface_model(tmp_path)
        assert model.task is not None
        assert {t.name for t in model.task} == {"Extra"}

    def test_import_global_options_are_deduped_and_settings_appended(self, tmp_path):
        (tmp_path / "first.json5").write_text(
            stdlib_json.dumps(
                {
                    "global_option": ["shared_option", "first_option"],
                    "setting": [{"name": "first", "option": ["first_option"]}],
                }
            )
        )
        (tmp_path / "second.json5").write_text(
            stdlib_json.dumps(
                {
                    "global_option": ["first_option", "second_option"],
                    "setting": [{"name": "second", "option": ["second_option"]}],
                }
            )
        )
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "option": {
                    option_name: {
                        "type": "select",
                        "cases": [{"name": "enabled"}],
                    }
                    for option_name in (
                        "root_option",
                        "shared_option",
                        "first_option",
                        "second_option",
                    )
                },
                "global_option": ["root_option", "shared_option"],
                "setting": [{"name": "root", "option": ["root_option"]}],
                "import": ["first.json5", "second.json5"],
            },
        )

        model = load_interface_model(tmp_path)

        assert model.global_option == [
            "root_option",
            "shared_option",
            "first_option",
            "second_option",
        ]
        assert model.setting is not None
        assert [section.name for section in model.setting] == [
            "root",
            "first",
            "second",
        ]

    def test_duplicate_setting_name_is_rejected(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "setting": [{"name": "general"}, {"name": "general"}],
            },
        )

        with pytest.raises(
            InterfaceLoadError,
            match=r"setting 中存在重复分区: general",
        ):
            load_interface_model(tmp_path)

    def test_setting_unknown_option_is_rejected(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "setting": [{"name": "general", "option": ["missing"]}],
            },
        )

        with pytest.raises(
            InterfaceLoadError,
            match=r"setting\[general\] 引用了不存在的选项: missing",
        ):
            load_interface_model(tmp_path)

    def test_pretask_single_object_is_normalized_to_list(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "pretask": {"name": "Root pretask", "exec": "prepare-root"},
            },
        )

        model = load_interface_model(tmp_path)

        assert isinstance(model.pretask, list)
        assert [(pretask.name, pretask.exec) for pretask in model.pretask] == [
            ("Root pretask", "prepare-root")
        ]

    def test_imported_pretasks_merge_preorder(self, tmp_path):
        (tmp_path / "inner.json5").write_text(
            stdlib_json.dumps({"pretask": {"name": "Inner", "exec": "prepare-inner"}})
        )
        (tmp_path / "outer.json5").write_text(
            stdlib_json.dumps(
                {
                    "import": ["inner.json5"],
                    "pretask": [{"name": "Outer", "exec": "prepare-outer"}],
                }
            )
        )
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "pretask": {"name": "Root", "exec": "prepare-root"},
                "import": ["outer.json5"],
            },
        )

        model = load_interface_model(tmp_path)

        assert isinstance(model.pretask, list)
        assert [pretask.name for pretask in model.pretask] == [
            "Root",
            "Outer",
            "Inner",
        ]

    def test_imported_fragment_pretask_loads_with_valid_context_and_option(
        self, tmp_path
    ):
        (tmp_path / "pretasks.json5").write_text(
            stdlib_json.dumps(
                {
                    "pretask": [
                        {
                            "name": "Fragment pretask",
                            "exec": "prepare-fragment",
                            "args": ["--flag"],
                            "resource": ["main"],
                            "controller": ["adb"],
                            "option": ["mode"],
                        }
                    ]
                }
            )
        )
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [
                    {
                        "name": "Main task",
                        "entry": "main",
                        "resource": ["main"],
                        "option": ["mode"],
                    }
                ],
                "option": {
                    "mode": {
                        "type": "select",
                        "cases": [{"name": "safe"}],
                    }
                },
                "import": ["pretasks.json5"],
            },
        )

        model = load_interface_model(tmp_path)

        assert isinstance(model.pretask, list)
        assert len(model.pretask) == 1
        pretask = model.pretask[0]
        assert pretask.name == "Fragment pretask"
        assert pretask.exec == "prepare-fragment"
        assert pretask.args == ["--flag"]
        assert pretask.resource == ["main"]
        assert pretask.controller == ["adb"]
        assert pretask.option == ["mode"]

    def test_cyclic_import_raises(self, tmp_path):
        (tmp_path / "a.json5").write_text('{import: ["b.json5"]}')
        (tmp_path / "b.json5").write_text('{import: ["a.json5"]}')
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "import": ["a.json5"],
            },
        )
        with pytest.raises(InterfaceLoadError, match="循环导入"):
            load_interface_model(tmp_path)

    def test_nonexistent_resource(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "T", "entry": "T", "resource": ["bad_resource"]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的 resource"):
            load_interface_model(tmp_path)

    def test_nonexistent_controller(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "T", "entry": "T", "controller": ["bad_ctrl"]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的 controller"):
            load_interface_model(tmp_path)

    def test_pretask_whitespace_exec_is_rejected(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "pretask": [{"exec": "   \t  "}],
            },
        )

        with pytest.raises(
            InterfaceLoadError,
            match=r"pretask\[0\]\.exec 必须是非空字符串",
        ):
            load_interface_model(tmp_path)

    def test_pretask_nonexistent_resource(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "pretask": [{"exec": "prepare", "resource": ["missing"]}],
            },
        )

        with pytest.raises(
            InterfaceLoadError,
            match=r"pretask\[0\] 引用了不存在的 resource: missing",
        ):
            load_interface_model(tmp_path)

    def test_pretask_nonexistent_controller(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "pretask": [{"exec": "prepare", "controller": ["missing"]}],
            },
        )

        with pytest.raises(
            InterfaceLoadError,
            match=r"pretask\[0\] 引用了不存在的 controller: missing",
        ):
            load_interface_model(tmp_path)

    def test_pretask_nonexistent_option(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "pretask": [{"exec": "prepare", "option": ["missing"]}],
            },
        )

        with pytest.raises(
            InterfaceLoadError,
            match=r"pretask\[0\]\.option 引用了不存在的选项: missing",
        ):
            load_interface_model(tmp_path)

    def test_pretask_option_not_reachable_from_task_is_allowed(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [
                    {
                        "name": "Main task",
                        "entry": "main",
                        "resource": ["main"],
                        "option": ["reachable"],
                    }
                ],
                "option": {
                    "reachable": {
                        "type": "select",
                        "cases": [{"name": "yes"}],
                    },
                    "unreachable": {
                        "type": "select",
                        "cases": [{"name": "no"}],
                    },
                },
                "pretask": [
                    {
                        "exec": "prepare",
                        "resource": ["main"],
                        "option": ["unreachable"],
                    }
                ],
            },
        )

        # pretask.option 的合法来源不再要求能从任务到达，只要求 option 键存在
        model = load_interface_model(tmp_path)
        assert model.pretask is not None
        assert [p.option for p in model.pretask] == [["unreachable"]]

    def test_scan_select_expansion(self, tmp_path):
        imgs = tmp_path / "images"
        imgs.mkdir()
        (imgs / "a.png").write_text("x")
        (imgs / "b.png").write_text("x")
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "option": {
                    "skin": {
                        "type": "scan_select",
                        "scan_dir": "images",
                        "scan_filter": "*.png",
                        "pipeline_override": {"Action": {"attach": {"skin": ""}}},
                    }
                },
            },
        )
        model = load_interface_model(tmp_path)
        assert model.option is not None
        assert model.option["skin"].cases is not None
        assert len(model.option["skin"].cases) == 2

    def test_import_shared_entry_is_allowed(self, tmp_path):
        """不同 task name 共用 entry 不再是冲突。"""
        (tmp_path / "extra.json5").write_text(
            '{task: [{name: "X", entry: "RootTask"}]}'
        )
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "RootTask", "entry": "RootTask"}],
                "import": ["extra.json5"],
            },
        )
        model = load_interface_model(tmp_path)
        assert model.task is not None
        assert {t.name: t.entry for t in model.task} == {
            "RootTask": "RootTask",
            "X": "RootTask",
        }

    def test_import_fragment_with_illegal_key(self, tmp_path):
        """Import file with key outside the allowed sections is rejected."""
        (tmp_path / "bad.json5").write_text("{controller: []}")
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "import": ["bad.json5"],
            },
        )
        with pytest.raises(InterfaceLoadError, match="非法字段"):
            load_interface_model(tmp_path)

    # ------------------------------------------------------------------
    # Preset validation through load_interface_model
    # ------------------------------------------------------------------

    def test_preset_duplicate_task(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A"}],
                "preset": [{"name": "P", "task": [{"name": "A"}, {"name": "A"}]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="重复任务"):
            load_interface_model(tmp_path)

    def test_preset_nonexistent_task(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A"}],
                "preset": [{"name": "P", "task": [{"name": "NoSuchTask"}]}],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的任务"):
            load_interface_model(tmp_path)

    def test_preset_option_not_in_task(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A"}],
                "option": {"diff": {"type": "select", "cases": [{"name": "easy"}]}},
                "preset": [
                    {"name": "P", "task": [{"name": "A", "option": {"diff": "easy"}}]}
                ],
            },
        )
        # Task A does not declare option=["diff"], so diff is not reachable
        with pytest.raises(InterfaceLoadError, match="不属于该任务的选项"):
            load_interface_model(tmp_path)

    def test_preset_select_invalid_case(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["diff"]}],
                "option": {"diff": {"type": "select", "cases": [{"name": "easy"}]}},
                "preset": [
                    {"name": "P", "task": [{"name": "A", "option": {"diff": "hard"}}]}
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的 case"):
            load_interface_model(tmp_path)

    def test_preset_checkbox_invalid_value(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["mods"]}],
                "option": {
                    "mods": {
                        "type": "checkbox",
                        "cases": [{"name": "fast"}, {"name": "slow"}],
                    }
                },
                "preset": [
                    {
                        "name": "P",
                        "task": [{"name": "A", "option": {"mods": "not_a_list"}}],
                    }
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="必须是字符串数组"):
            load_interface_model(tmp_path)

    def test_preset_input_invalid_type(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["cfg"]}],
                "option": {"cfg": {"type": "input", "inputs": [{"name": "host"}]}},
                "preset": [
                    {
                        "name": "P",
                        "task": [
                            {"name": "A", "option": {"cfg": "string_instead_of_dict"}}
                        ],
                    }
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="必须是对象"):
            load_interface_model(tmp_path)

    def test_preset_input_nonexistent_key(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["cfg"]}],
                "option": {"cfg": {"type": "input", "inputs": [{"name": "host"}]}},
                "preset": [
                    {
                        "name": "P",
                        "task": [{"name": "A", "option": {"cfg": {"bad_key": "val"}}}],
                    }
                ],
            },
        )
        with pytest.raises(InterfaceLoadError, match="引用了不存在的输入项"):
            load_interface_model(tmp_path)

    def test_preset_hotkey_invalid_type(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["hotkeys"]}],
                "option": {
                    "hotkeys": {
                        "type": "hotkey",
                        "hotkeys": [{"name": "toggle"}],
                    }
                },
                "preset": [
                    {
                        "name": "P",
                        "task": [{"name": "A", "option": {"hotkeys": "Alt+A"}}],
                    }
                ],
            },
        )

        with pytest.raises(
            InterfaceLoadError,
            match=(r"preset\[P\]\.task\[A\]\.option\[hotkeys\] 必须是对象"),
        ):
            load_interface_model(tmp_path)

    def test_preset_hotkey_unknown_field_is_rejected(self, tmp_path):
        _write_interface(
            tmp_path,
            {
                "interface_version": 2,
                "name": "Test",
                "controller": [{"name": "adb", "type": "Adb"}],
                "resource": [{"name": "main", "path": ["resource"]}],
                "task": [{"name": "A", "entry": "A", "option": ["hotkeys"]}],
                "option": {
                    "hotkeys": {
                        "type": "hotkey",
                        "hotkeys": [{"name": "toggle"}],
                    }
                },
                "preset": [
                    {
                        "name": "P",
                        "task": [
                            {
                                "name": "A",
                                "option": {"hotkeys": {"unknown": "Alt+A"}},
                            }
                        ],
                    }
                ],
            },
        )

        with pytest.raises(
            InterfaceLoadError,
            match=(
                r"preset\[P\]\.task\[A\]\.option\[hotkeys\] "
                r"引用了不存在的快捷键项: unknown"
            ),
        ):
            load_interface_model(tmp_path)


# ---------------------------------------------------------------------------
# PI v2.9.2 合并语义
# ---------------------------------------------------------------------------


class TestMergeSemanticsV292:
    def _base_interface(self, imports=None, **extra):
        if imports is not None:
            extra["import"] = imports
        data = {
            "interface_version": 2,
            "name": "Test",
            "controller": [{"name": "adb", "type": "Adb"}],
            "resource": [{"name": "main", "path": ["resource"]}],
        }
        data.update(extra)
        return data

    def test_later_imported_option_replaces_whole_definition(self, tmp_path):
        """option 同名键整体替换为后导入定义，不做字段级合并。"""
        (tmp_path / "first.json5").write_text(
            stdlib_json.dumps(
                {
                    "option": {
                        "mode": {
                            "type": "select",
                            "label": "First label",
                            "cases": [{"name": "a"}, {"name": "b"}],
                            "default_case": "a",
                        }
                    }
                }
            )
        )
        (tmp_path / "second.json5").write_text(
            stdlib_json.dumps(
                {
                    "option": {
                        "mode": {
                            "type": "select",
                            "label": "Second label",
                            "cases": [{"name": "x"}],
                            "default_case": "x",
                        }
                    }
                }
            )
        )
        _write_interface(
            tmp_path,
            self._base_interface(imports=["first.json5", "second.json5"]),
        )

        model = load_interface_model(tmp_path)
        assert model.option is not None
        mode = model.option["mode"]
        assert mode.label == "Second label"
        assert [case.name for case in mode.cases or []] == ["x"]
        assert mode.default_case == "x"

    def test_group_first_definition_wins(self, tmp_path):
        """group 按名称保留第一次出现的完整定义。"""
        (tmp_path / "first.json5").write_text(
            stdlib_json.dumps(
                {"group": [{"name": "g1", "label": "First", "default_expand": True}]}
            )
        )
        (tmp_path / "second.json5").write_text(
            stdlib_json.dumps(
                {"group": [{"name": "g1", "label": "Second"}, {"name": "g2"}]}
            )
        )
        _write_interface(
            tmp_path,
            self._base_interface(
                group=[{"name": "g0"}],
                imports=["first.json5", "second.json5"],
            ),
        )

        model = load_interface_model(tmp_path)
        assert model.group is not None
        groups = {g.name: g for g in model.group}
        assert list(groups) == ["g0", "g1", "g2"]
        assert groups["g1"].label == "First"

    def test_task_group_reference_validated(self, tmp_path):
        _write_interface(
            tmp_path,
            self._base_interface(
                group=[{"name": "real"}],
                task=[{"name": "T", "entry": "T", "group": ["missing"]}],
            ),
        )
        with pytest.raises(InterfaceLoadError, match=r"引用了不存在的分组: missing"):
            load_interface_model(tmp_path)

    def test_task_group_reference_valid(self, tmp_path):
        _write_interface(
            tmp_path,
            self._base_interface(
                group=[{"name": "real"}],
                task=[{"name": "T", "entry": "T", "group": ["real"]}],
            ),
        )
        model = load_interface_model(tmp_path)
        assert model.task is not None
        assert model.task[0].group == ["real"]

    def test_imported_task_shares_entry_with_distinct_options(self, tmp_path):
        """两个 name 共用 entry，各自携带不同选项定义。"""
        (tmp_path / "extra.json5").write_text(
            stdlib_json.dumps(
                {
                    "task": [
                        {
                            "name": "Fast",
                            "entry": "Farm",
                            "option": ["speed"],
                        }
                    ],
                    "option": {
                        "speed": {"type": "select", "cases": [{"name": "high"}]}
                    },
                }
            )
        )
        _write_interface(
            tmp_path,
            self._base_interface(
                task=[{"name": "Slow", "entry": "Farm", "option": ["safety"]}],
                option={"safety": {"type": "select", "cases": [{"name": "on"}]}},
                imports=["extra.json5"],
            ),
        )
        model = load_interface_model(tmp_path)
        assert model.task is not None
        by_name = {t.name: t for t in model.task}
        assert by_name["Slow"].option == ["safety"]
        assert by_name["Fast"].option == ["speed"]
        assert by_name["Slow"].entry == by_name["Fast"].entry == "Farm"
