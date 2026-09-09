import copy
import re
from pathlib import Path
from typing import Any

import json_utils as json
from models.interface import InterfaceModel, Option, OptionCase

IMPORTABLE_KEYS = {
    "task",
    "option",
    "preset",
    "group",
    "pretask",
    "import",
    "global_option",
    "setting",
}

# pathlib.Path is OS-aware: on POSIX it does not recognize Windows drive
# letters (e.g. "C:/windows" parses as a relative path). Detect them
# explicitly so absolute-path rejection is consistent across platforms.
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class InterfaceLoadError(ValueError):
    pass


class _MergeState:
    def __init__(self):
        self.task_names: dict[str, Path] = {}
        self.preset_names: dict[str, Path] = {}


def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError as exc:
        raise InterfaceLoadError(f"找不到配置文件: {path}") from exc
    except json.JSONDecodeError as exc:
        message = getattr(exc, "message", str(exc))
        raise InterfaceLoadError(f"解析配置文件失败: {path}: {message}") from exc

    if not isinstance(data, dict):
        raise InterfaceLoadError(f"配置文件必须是 JSON 对象: {path}")
    return data


def _normalize_import_list(raw_value: Any, source_path: Path) -> list[str]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list) or not all(
        isinstance(item, str) and item for item in raw_value
    ):
        raise InterfaceLoadError(f"import 字段必须是非空字符串数组: {source_path}")
    return raw_value


def _validate_importable_fragment(data: dict[str, Any], source_path: Path) -> None:
    invalid_keys = sorted(set(data) - IMPORTABLE_KEYS)
    if invalid_keys:
        raise InterfaceLoadError(
            "导入文件只允许包含 task、option、preset、pretask、import、"
            f"global_option、setting 字段: {source_path}，"
            f"发现非法字段 {', '.join(invalid_keys)}"
        )


def _raise_conflict(
    kind: str, key: str, source_path: Path, existing_path: Path
) -> None:
    raise InterfaceLoadError(
        f"{kind} 冲突: {key} 已在 {existing_path} 定义，无法再次从 {source_path} 导入"
    )


def _register_tasks(tasks: Any, source_path: Path, state: _MergeState) -> None:
    if tasks is None:
        return
    if not isinstance(tasks, list):
        raise InterfaceLoadError(f"task 字段必须是数组: {source_path}")

    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise InterfaceLoadError(f"task[{index}] 必须是对象: {source_path}")
        task_name = task.get("name")
        task_entry = task.get("entry")
        if not isinstance(task_name, str) or not task_name:
            raise InterfaceLoadError(
                f"task[{index}].name 必须是非空字符串: {source_path}"
            )
        if not isinstance(task_entry, str) or not task_entry:
            raise InterfaceLoadError(
                f"task[{index}].entry 必须是非空字符串: {source_path}"
            )

        existing_name = state.task_names.get(task_name)
        if existing_name is not None:
            _raise_conflict("task.name", task_name, source_path, existing_name)

        state.task_names[task_name] = source_path


def _validate_options(options: Any, source_path: Path) -> None:
    if options is None:
        return
    if not isinstance(options, dict):
        raise InterfaceLoadError(f"option 字段必须是对象: {source_path}")

    for option_key in options:
        if not isinstance(option_key, str) or not option_key:
            raise InterfaceLoadError(f"option 键必须是非空字符串: {source_path}")


def _validate_groups(groups: Any, source_path: Path) -> None:
    if groups is None:
        return
    if not isinstance(groups, list):
        raise InterfaceLoadError(f"group 字段必须是数组: {source_path}")
    for index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise InterfaceLoadError(f"group[{index}] 必须是对象: {source_path}")
        group_name = group.get("name")
        if not isinstance(group_name, str) or not group_name:
            raise InterfaceLoadError(
                f"group[{index}].name 必须是非空字符串: {source_path}"
            )


def _register_presets(presets: Any, source_path: Path, state: _MergeState) -> None:
    if presets is None:
        return
    if not isinstance(presets, list):
        raise InterfaceLoadError(f"preset 字段必须是数组: {source_path}")

    for index, preset in enumerate(presets):
        if not isinstance(preset, dict):
            raise InterfaceLoadError(f"preset[{index}] 必须是对象: {source_path}")
        preset_name = preset.get("name")
        if not isinstance(preset_name, str) or not preset_name:
            raise InterfaceLoadError(
                f"preset[{index}].name 必须是非空字符串: {source_path}"
            )

        existing_path = state.preset_names.get(preset_name)
        if existing_path is not None:
            _raise_conflict("preset", preset_name, source_path, existing_path)
        state.preset_names[preset_name] = source_path


def _seed_root_sections(
    root_data: dict[str, Any], source_path: Path, state: _MergeState
) -> None:
    _register_tasks(root_data.get("task"), source_path, state)
    _validate_options(root_data.get("option"), source_path)
    _validate_groups(root_data.get("group"), source_path)
    _register_presets(root_data.get("preset"), source_path, state)
    pretasks = root_data.get("pretask")
    if pretasks is not None and not isinstance(pretasks, list):
        root_data["pretask"] = [pretasks]


def _merge_pretasks(target: dict[str, Any], fragment: dict[str, Any]) -> None:
    pretasks = fragment.get("pretask")
    if pretasks is None:
        return
    if not isinstance(pretasks, list):
        pretasks = [pretasks]
    target.setdefault("pretask", [])
    target["pretask"].extend(copy.deepcopy(pretasks))


def _merge_fragment_sections(
    target: dict[str, Any],
    fragment: dict[str, Any],
    source_path: Path,
    state: _MergeState,
) -> None:
    tasks = fragment.get("task")
    options = fragment.get("option")
    presets = fragment.get("preset")
    groups = fragment.get("group")

    _register_tasks(tasks, source_path, state)
    _validate_options(options, source_path)
    _validate_groups(groups, source_path)
    _register_presets(presets, source_path, state)

    if tasks:
        target.setdefault("task", [])
        target["task"].extend(copy.deepcopy(tasks))
    if options:
        # 同名 option 键整体替换为后导入定义（不做字段级深合并）
        target.setdefault("option", {})
        target["option"].update(copy.deepcopy(options))
    if presets:
        target.setdefault("preset", [])
        target["preset"].extend(copy.deepcopy(presets))
    if groups:
        # group 按名称保留第一次出现的完整定义
        target_group_names = {
            group.get("name")
            for group in target.get("group") or []
            if isinstance(group, dict)
        }
        target.setdefault("group", [])
        for group in groups:
            group_name = group.get("name") if isinstance(group, dict) else None
            if group_name not in target_group_names:
                target["group"].append(copy.deepcopy(group))
                target_group_names.add(group_name)

    global_options = fragment.get("global_option")
    if global_options:
        target_global_options = target.setdefault("global_option", [])
        for option_name in global_options:
            if option_name not in target_global_options:
                target_global_options.append(copy.deepcopy(option_name))

    settings = fragment.get("setting")
    if settings:
        target.setdefault("setting", [])
        target["setting"].extend(copy.deepcopy(settings))

    _merge_pretasks(target, fragment)


def _normalize_root_relative_path(raw_path: str, *, field_name: str) -> str:
    normalized_path = raw_path.strip().replace("\\", "/")
    if not normalized_path:
        raise ValueError(f"{field_name} 不能为空")

    candidate = Path(normalized_path)
    if (
        candidate.is_absolute()
        or candidate.drive
        or candidate.root
        or _WIN_DRIVE_RE.match(normalized_path)
    ):
        raise ValueError(f"{field_name} 不允许使用绝对路径: {raw_path}")

    if normalized_path in {".", ".."}:
        raise ValueError(f"{field_name} 不允许包含 . 或 .. 路径段: {raw_path}")

    parts = normalized_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field_name} 不允许包含 . 或 .. 路径段: {raw_path}")

    return "/".join(parts)


def _resolve_import_path(import_path: str, base_dir: Path) -> Path:
    normalized_import_path = _normalize_root_relative_path(
        import_path,
        field_name="import",
    )
    resolved_path = (base_dir / normalized_import_path).resolve()
    try:
        resolved_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError(
            f"import 越界，禁止访问软件根目录之外的路径: {import_path}"
        ) from exc
    return resolved_path


def _validate_scan_dir(scan_dir: str, option_name: str) -> str:
    return _normalize_root_relative_path(
        scan_dir,
        field_name=f"scan_select 选项 {option_name} 的 scan_dir",
    )


def _validate_scan_filter(scan_filter: str, option_name: str) -> str:
    return _normalize_root_relative_path(
        scan_filter,
        field_name=f"scan_select 选项 {option_name} 的 scan_filter",
    )


def _is_within_base_dir(path: Path, base_dir: Path) -> bool:
    try:
        path.relative_to(base_dir)
        return True
    except ValueError:
        return False


def resolve_interface_relative_path(
    base_dir: Path,
    raw_path: str,
    *,
    field_name: str = "path",
    allow_directories: bool = False,
    allow_files_and_directories: bool = False,
) -> Path:
    normalized_path = _normalize_root_relative_path(raw_path, field_name=field_name)

    resolved_path = (base_dir / normalized_path).resolve()
    if not _is_within_base_dir(resolved_path, base_dir):
        raise ValueError(f"{field_name} 越界，禁止访问软件根目录之外的路径: {raw_path}")
    if not resolved_path.exists():
        raise ValueError(f"{field_name} 不存在: {raw_path}")
    if allow_files_and_directories:
        if not (resolved_path.is_file() or resolved_path.is_dir()):
            raise ValueError(f"{field_name} 不是文件或目录: {raw_path}")
        return resolved_path
    if allow_directories:
        if not resolved_path.is_dir():
            raise ValueError(f"{field_name} 不是目录: {raw_path}")
    elif not resolved_path.is_file():
        raise ValueError(f"{field_name} 不是文件: {raw_path}")
    return resolved_path


def _scan_scan_select_cases(
    option_name: str,
    option_data: dict[str, Any],
    base_dir: Path,
) -> list[dict[str, str]]:
    raw_cases = option_data.get("cases")
    if raw_cases is not None:
        if not isinstance(raw_cases, list):
            raise InterfaceLoadError(
                f"scan_select 选项 {option_name} 的 cases 必须为空数组或省略"
            )
        if len(raw_cases) > 0:
            raise InterfaceLoadError(
                f"scan_select 选项 {option_name} 不允许预置 cases，请改为留空后由扫描结果生成"
            )

    scan_dir = option_data.get("scan_dir")
    if not isinstance(scan_dir, str) or not scan_dir.strip():
        raise InterfaceLoadError(
            f"scan_select 选项 {option_name} 的 scan_dir 必须为非空字符串"
        )

    scan_filter = option_data.get("scan_filter")
    if not isinstance(scan_filter, str) or not scan_filter.strip():
        raise InterfaceLoadError(
            f"scan_select 选项 {option_name} 的 scan_filter 必须为非空字符串"
        )

    normalized_scan_dir = _validate_scan_dir(scan_dir, option_name)
    normalized_scan_filter = _validate_scan_filter(scan_filter, option_name)

    resolved_scan_dir = (base_dir / normalized_scan_dir).resolve()
    if not _is_within_base_dir(resolved_scan_dir, base_dir):
        raise InterfaceLoadError(
            f"scan_select 选项 {option_name} 的 scan_dir 越界，禁止访问软件根目录之外的路径"
        )
    if not resolved_scan_dir.exists() or not resolved_scan_dir.is_dir():
        raise InterfaceLoadError(
            f"scan_select 选项 {option_name} 的 scan_dir 不存在或不是目录: {scan_dir}"
        )

    try:
        matched_paths = sorted(
            {
                file_path.relative_to(resolved_scan_dir).as_posix()
                for file_path in resolved_scan_dir.glob(normalized_scan_filter)
                if file_path.is_file()
            }
        )
    except Exception as exc:
        raise InterfaceLoadError(
            f"scan_select 选项 {option_name} 扫描失败，scan_filter={normalized_scan_filter}"
        ) from exc

    return [
        {"name": relative_path, "label": relative_path}
        for relative_path in matched_paths
    ]


def _expand_scan_select_options(data: dict[str, Any], base_dir: Path) -> None:
    options = data.get("option")
    if options is None or not isinstance(options, dict):
        return

    for option_name, option_data in options.items():
        if not isinstance(option_data, dict):
            continue
        if option_data.get("type") != "scan_select":
            continue
        option_data["cases"] = _scan_scan_select_cases(
            option_name, option_data, base_dir
        )


def rescan_scan_select_option(
    interface_model: InterfaceModel,
    option_name: str,
    base_dir: Path,
) -> list[dict[str, str]]:
    option_map = interface_model.option or {}
    option = option_map.get(option_name)
    if option is None:
        raise InterfaceLoadError(f"scan_select 选项 {option_name} 不存在")
    if option.type != "scan_select":
        raise InterfaceLoadError(f"选项 {option_name} 不是 scan_select 类型")

    option_data = Option.model_validate(option).model_dump(exclude_none=False)
    option_data["cases"] = []
    scanned_cases = _scan_scan_select_cases(option_name, option_data, base_dir)
    option.cases = [OptionCase.model_validate(item) for item in scanned_cases]
    return scanned_cases


def _collect_reachable_option_names(
    option_names: list[str],
    option_map: dict[str, Option],
    collected: set[str],
) -> None:
    for option_name in option_names:
        option = option_map.get(option_name)
        if option is None:
            raise InterfaceLoadError(f"任务引用了不存在的选项: {option_name}")
        if option_name in collected:
            continue
        collected.add(option_name)
        for case_item in option.cases or []:
            if case_item.option:
                _collect_reachable_option_names(case_item.option, option_map, collected)


def _validate_preset_option_value(
    preset_name: str,
    task_name: str,
    option_name: str,
    option: Option,
    value: Any,
) -> None:
    location = f"preset[{preset_name}].task[{task_name}].option[{option_name}]"
    case_names = {case.name for case in option.cases or []}

    if option.type in {"select", "switch", "scan_select"}:
        if not isinstance(value, str):
            raise InterfaceLoadError(f"{location} 必须是字符串")
        if value not in case_names:
            raise InterfaceLoadError(f"{location} 引用了不存在的 case: {value}")
        return

    if option.type == "checkbox":
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise InterfaceLoadError(f"{location} 必须是字符串数组")
        invalid_cases = [item for item in value if item not in case_names]
        if invalid_cases:
            raise InterfaceLoadError(
                f"{location} 引用了不存在的 case: {', '.join(invalid_cases)}"
            )
        return

    if option.type == "input":
        if not isinstance(value, dict):
            raise InterfaceLoadError(f"{location} 必须是对象")
        input_names = {input_item.name for input_item in option.inputs or []}
        for input_name, input_value in value.items():
            if input_name not in input_names:
                raise InterfaceLoadError(
                    f"{location} 引用了不存在的输入项: {input_name}"
                )
            if not isinstance(input_value, str):
                raise InterfaceLoadError(f"{location}.{input_name} 必须是字符串")

    if option.type == "hotkey":
        if not isinstance(value, dict):
            raise InterfaceLoadError(f"{location} 必须是对象")
        hotkey_names = {item.name for item in option.hotkeys or []}
        for hotkey_name, hotkey_value in value.items():
            if hotkey_name not in hotkey_names:
                raise InterfaceLoadError(
                    f"{location} 引用了不存在的快捷键项: {hotkey_name}"
                )
            if not isinstance(hotkey_value, str):
                raise InterfaceLoadError(f"{location}.{hotkey_name} 必须是字符串")


def _validate_presets(interface_model: InterfaceModel) -> None:
    presets = interface_model.preset or []
    tasks = interface_model.task or []
    option_map = interface_model.option or {}
    task_name_map = {task.name: task for task in tasks}
    reachable_options_by_task: dict[str, set[str]] = {}

    for task in tasks:
        collected: set[str] = set()
        _collect_reachable_option_names(task.option or [], option_map, collected)
        reachable_options_by_task[task.name] = collected

    for preset in presets:
        seen_task_names: set[str] = set()
        for preset_task in preset.task or []:
            if preset_task.name in seen_task_names:
                raise InterfaceLoadError(
                    f"preset[{preset.name}] 中存在重复任务: {preset_task.name}"
                )
            seen_task_names.add(preset_task.name)

            task = task_name_map.get(preset_task.name)
            if task is None:
                raise InterfaceLoadError(
                    f"preset[{preset.name}] 引用了不存在的任务: {preset_task.name}"
                )

            reachable_options = reachable_options_by_task.get(task.name, set())
            for option_name, option_value in (preset_task.option or {}).items():
                if option_name not in reachable_options:
                    raise InterfaceLoadError(
                        f"preset[{preset.name}] 的任务 {task.name} 引用了不属于该任务的选项: {option_name}"
                    )
                option = option_map.get(option_name)
                if option is None:
                    raise InterfaceLoadError(
                        f"preset[{preset.name}] 引用了不存在的选项: {option_name}"
                    )
                _validate_preset_option_value(
                    preset.name,
                    task.name,
                    option_name,
                    option,
                    option_value,
                )


def _validate_setting_sections(interface_model: InterfaceModel) -> None:
    option_map = interface_model.option or {}
    seen_names: set[str] = set()

    for section in interface_model.setting or []:
        if section.name in seen_names:
            raise InterfaceLoadError(f"setting 中存在重复分区: {section.name}")
        seen_names.add(section.name)

        for option_name in section.option or []:
            if option_name not in option_map:
                raise InterfaceLoadError(
                    f"setting[{section.name}] 引用了不存在的选项: {option_name}"
                )


def _validate_task_context_constraints(
    interface_model: InterfaceModel, state: _MergeState
) -> None:
    tasks = interface_model.task or []
    resource_names = {resource.name for resource in interface_model.resource}
    controller_names = {controller.name for controller in interface_model.controller}
    group_names = {group.name for group in interface_model.group or []}

    for task in tasks:
        task_ref = f"{task.name}({task.entry})"
        source = state.task_names.get(task.name)
        if source is not None:
            task_ref = f"{task_ref} 定义于 {source}"

        if task.resource:
            invalid_resources = sorted(
                {
                    resource_name
                    for resource_name in task.resource
                    if resource_name not in resource_names
                }
            )
            if invalid_resources:
                raise InterfaceLoadError(
                    f"任务 {task_ref} 引用了不存在的 resource: {', '.join(invalid_resources)}"
                )

        if task.controller:
            invalid_controllers = sorted(
                {
                    controller_name
                    for controller_name in task.controller
                    if controller_name not in controller_names
                }
            )
            if invalid_controllers:
                raise InterfaceLoadError(
                    f"任务 {task_ref} 引用了不存在的 controller: {', '.join(invalid_controllers)}"
                )

        if task.group:
            invalid_groups = sorted(
                {
                    group_name
                    for group_name in task.group
                    if group_name not in group_names
                }
            )
            if invalid_groups:
                raise InterfaceLoadError(
                    f"任务 {task_ref} 的 group 字段引用了不存在的分组: {', '.join(invalid_groups)}"
                )


def _validate_pretasks(interface_model: InterfaceModel) -> None:
    raw_pretasks = interface_model.pretask
    if raw_pretasks is None:
        pretasks = []
    elif isinstance(raw_pretasks, list):
        pretasks = raw_pretasks
    else:
        pretasks = [raw_pretasks]

    resource_names = {resource.name for resource in interface_model.resource}
    controller_names = {controller.name for controller in interface_model.controller}
    option_map = interface_model.option or {}

    for index, pretask in enumerate(pretasks):
        pretask_ref = f"pretask[{index}]"
        if not pretask.exec.strip():
            raise InterfaceLoadError(f"{pretask_ref}.exec 必须是非空字符串")

        invalid_resources = sorted(
            {
                resource_name
                for resource_name in pretask.resource or []
                if resource_name not in resource_names
            }
        )
        if invalid_resources:
            raise InterfaceLoadError(
                f"{pretask_ref} 引用了不存在的 resource: {', '.join(invalid_resources)}"
            )

        invalid_controllers = sorted(
            {
                controller_name
                for controller_name in pretask.controller or []
                if controller_name not in controller_names
            }
        )
        if invalid_controllers:
            raise InterfaceLoadError(
                f"{pretask_ref} 引用了不存在的 controller: {', '.join(invalid_controllers)}"
            )

        for option_name in pretask.option or []:
            if option_name not in option_map:
                raise InterfaceLoadError(
                    f"{pretask_ref}.option 引用了不存在的选项: {option_name}"
                )

    interface_model.pretask = pretasks


def _merge_imports_into_target(
    target: dict[str, Any],
    import_paths: list[str],
    base_dir: Path,
    state: _MergeState,
    stack: list[Path],
) -> None:
    for import_path in import_paths:
        resolved_path = _resolve_import_path(import_path, base_dir)
        if resolved_path in stack:
            chain = " -> ".join(str(item) for item in [*stack, resolved_path])
            raise InterfaceLoadError(f"检测到循环导入: {chain}")

        fragment = _read_json_dict(resolved_path)
        _validate_importable_fragment(fragment, resolved_path)

        child_imports = _normalize_import_list(fragment.get("import"), resolved_path)
        # 前序遍历：先合并该文件自身内容，再递归其 imports。
        # 顺序为主文件 → 第一个 import 自身 → 该文件的递归 imports → 下一个 import。
        _merge_fragment_sections(target, fragment, resolved_path, state)
        _merge_imports_into_target(
            target,
            child_imports,
            base_dir,
            state,
            [*stack, resolved_path],
        )


def load_interface_model(base_dir: str | Path) -> InterfaceModel:
    resolved_base_dir = Path(base_dir).resolve()
    root_path = (resolved_base_dir / "interface.json").resolve()
    if not _is_within_base_dir(root_path, resolved_base_dir):
        raise InterfaceLoadError("interface.json 不在软件根目录内")

    root_data = _read_json_dict(root_path)
    merged_data = copy.deepcopy(root_data)
    merge_state = _MergeState()

    _seed_root_sections(merged_data, root_path, merge_state)
    root_imports = _normalize_import_list(merged_data.get("import"), root_path)
    _merge_imports_into_target(
        merged_data,
        root_imports,
        resolved_base_dir,
        merge_state,
        [root_path],
    )
    _expand_scan_select_options(merged_data, resolved_base_dir)

    try:
        interface_model = InterfaceModel.model_validate(merged_data)
        _validate_task_context_constraints(interface_model, merge_state)
        _validate_pretasks(interface_model)
        _validate_presets(interface_model)
        _validate_setting_sections(interface_model)
        return interface_model
    except Exception as exc:
        raise InterfaceLoadError(f"校验 interface 配置失败: {exc}") from exc
