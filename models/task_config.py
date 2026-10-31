from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from models.interface import InterfaceModel, Option, Preset, PresetOptionValue
from models.scheduler import (
    PreTaskCommand,
    TaskOptionsByTask,
    TaskOptionValue,
    _generate_pre_task_id,
)

CUSTOM_PRESET_NAME = "__mwu_reserved_custom_preset__"


class TaskPresetSnapshotModel(BaseModel):
    tasks: list[str] = Field(
        default_factory=list,
        description="队列任务名列表（有序，允许重复，表示执行顺序）",
    )
    taskOptions: TaskOptionsByTask = Field(
        default_factory=dict,
        description="任务选项配置，key为任务名，value为该任务的选项映射",
    )
    preTasks: list[PreTaskCommand] = Field(
        default_factory=list, description="前置 shell 命令列表"
    )


class TaskConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    selectedPreset: str = Field(default="", description="当前选中的预设名称")
    presets: dict[str, TaskPresetSnapshotModel] = Field(
        default_factory=dict, description="所有预设对应的任务快照"
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_raw_config(cls, value: Any):
        if not isinstance(value, dict):
            return value

        selected_preset = _normalize_preset_name(value.get("selectedPreset"))
        raw_presets = value.get("presets")
        normalized_presets: dict[str, dict[str, Any]] = {}
        if isinstance(raw_presets, dict):
            for preset_name, snapshot in raw_presets.items():
                if not isinstance(preset_name, str):
                    continue
                normalized_presets[preset_name] = _normalize_raw_snapshot(snapshot)

        return {
            "selectedPreset": selected_preset,
            "presets": normalized_presets,
        }


def normalize_task_config(
    config: TaskConfigModel, interface_model: InterfaceModel
) -> TaskConfigModel:
    preset_snapshots: dict[str, TaskPresetSnapshotModel] = {}

    custom_snapshot = config.presets.get(CUSTOM_PRESET_NAME)
    preset_snapshots[CUSTOM_PRESET_NAME] = normalize_snapshot(
        custom_snapshot, interface_model
    )

    for preset in interface_model.preset or []:
        persisted_snapshot = config.presets.get(preset.name)
        snapshot = persisted_snapshot or build_interface_preset_snapshot(
            interface_model, preset
        )
        preset_snapshots[preset.name] = normalize_snapshot(snapshot, interface_model)

    selected_preset = _normalize_preset_name(config.selectedPreset)
    if selected_preset not in preset_snapshots:
        interface_presets = interface_model.preset or []
        selected_preset = (
            interface_presets[0].name if interface_presets else CUSTOM_PRESET_NAME
        )

    # 快照已是归一化后的模型，无需再走一遍 raw 校验
    return TaskConfigModel.model_construct(
        selectedPreset=selected_preset,
        presets=preset_snapshots,
    )


def normalize_snapshot(
    snapshot: TaskPresetSnapshotModel | dict[str, Any] | None,
    interface_model: InterfaceModel,
) -> TaskPresetSnapshotModel:
    valid_task_names = {task.name for task in (interface_model.task or [])}

    if isinstance(snapshot, TaskPresetSnapshotModel):
        raw_tasks = snapshot.tasks
        raw_task_options = snapshot.taskOptions
        raw_pre_tasks = snapshot.preTasks
    else:
        raw_snapshot = _normalize_raw_snapshot(snapshot)
        raw_tasks = raw_snapshot["tasks"]
        raw_task_options = raw_snapshot["taskOptions"]
        raw_pre_tasks = raw_snapshot["preTasks"]

    normalized_tasks = [
        task_name for task_name in raw_tasks if task_name in valid_task_names
    ]

    normalized_options = normalize_task_options_by_task(
        raw_task_options,
        list(dict.fromkeys(normalized_tasks)),
        interface_model,
    )

    return TaskPresetSnapshotModel(
        tasks=normalized_tasks,
        taskOptions=normalized_options,
        preTasks=_coerce_pre_tasks(raw_pre_tasks, drop_disabled=False),
    )


def normalize_task_options_by_task(
    raw_task_options: dict[str, Any] | None,
    task_names: list[str],
    interface_model: InterfaceModel,
) -> TaskOptionsByTask:
    task_option_maps = _build_task_option_maps(interface_model)
    normalized: TaskOptionsByTask = {}

    for task_name in task_names:
        option_map = task_option_maps.get(task_name, {})
        defaults, value_types = _build_option_defaults(option_map)
        case_name_sets = _build_option_case_name_sets(option_map)

        raw_options_for_task = None
        if isinstance(raw_task_options, dict):
            raw_options_for_task = raw_task_options.get(task_name)

        normalized[task_name] = _normalize_options_for_task(
            raw_options_for_task,
            option_map,
            defaults,
            value_types,
            case_name_sets,
        )

    return normalized


def normalize_global_option_values(
    raw_global_options: dict[str, Any] | None,
    interface_model: InterfaceModel,
) -> dict[str, TaskOptionValue]:
    """global_option 与 pretask.option（含嵌套子选项）共用 globalOptionValues。"""
    pretasks = interface_model.pretask or []
    if not isinstance(pretasks, list):
        pretasks = [pretasks]
    names = (interface_model.global_option or []) + [
        name for pretask in pretasks for name in (pretask.option or [])
    ]
    option_map: dict[str, Option] = {}
    _collect_task_options(names, interface_model.option or {}, option_map)
    defaults, value_types = _build_option_defaults(option_map)
    case_name_sets = _build_option_case_name_sets(option_map)
    return _normalize_options_for_task(
        raw_global_options,
        option_map,
        defaults,
        value_types,
        case_name_sets,
    )


def normalize_task_execution_payload(
    raw_task_list: Any,
    raw_task_options: Any,
    interface_model: InterfaceModel,
    raw_pre_tasks: Any = None,
) -> tuple[list[str], TaskOptionsByTask, list[PreTaskCommand]]:
    valid_task_names = {task.name for task in (interface_model.task or [])}
    normalized_task_list: list[str] = []

    if isinstance(raw_task_list, list):
        for task_name in raw_task_list:
            if not isinstance(task_name, str):
                continue
            if task_name not in valid_task_names:
                continue
            normalized_task_list.append(task_name)

    normalized_task_options = normalize_task_options_by_task(
        raw_task_options if isinstance(raw_task_options, dict) else None,
        normalized_task_list,
        interface_model,
    )

    return (
        normalized_task_list,
        normalized_task_options,
        _coerce_pre_tasks(raw_pre_tasks, drop_disabled=True),
    )


def build_interface_preset_snapshot(
    interface_model: InterfaceModel, preset: Preset
) -> TaskPresetSnapshotModel:
    task_names = {task.name for task in (interface_model.task or [])}
    task_option_maps = _build_task_option_maps(interface_model)

    task_options_by_task: TaskOptionsByTask = {}
    tasks: list[str] = []

    for preset_task in preset.task or []:
        if preset_task.name not in task_names or preset_task.enabled is False:
            continue

        tasks.append(preset_task.name)

        option_map = task_option_maps.get(preset_task.name, {})
        defaults, _ = _build_option_defaults(option_map)
        target_options = task_options_by_task.setdefault(preset_task.name, defaults)
        for option_name, option_value in (preset_task.option or {}).items():
            if option_name not in option_map:
                continue
            _apply_preset_option_value(
                option_name,
                option_value,
                option_map,
                target_options,
            )

    return TaskPresetSnapshotModel(
        tasks=tasks,
        taskOptions=task_options_by_task,
    )


def _normalize_raw_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {
            "tasks": [],
            "taskOptions": {},
            "preTasks": [],
        }

    tasks = snapshot.get("tasks")
    raw_tasks = (
        [item for item in tasks if isinstance(item, str)]
        if isinstance(tasks, list)
        else []
    )

    return {
        "tasks": raw_tasks,
        "taskOptions": _normalize_raw_task_options(snapshot.get("taskOptions")),
        "preTasks": _coerce_pre_tasks(snapshot.get("preTasks"), drop_disabled=False),
    }


def _normalize_raw_task_options(value: Any) -> dict[str, dict[str, TaskOptionValue]]:
    normalized: dict[str, dict[str, TaskOptionValue]] = {}
    if not isinstance(value, dict):
        return normalized

    for task_name, option_map in value.items():
        if not isinstance(task_name, str) or not isinstance(option_map, dict):
            continue

        normalized_options: dict[str, TaskOptionValue] = {}
        for option_name, option_value in option_map.items():
            if not isinstance(option_name, str):
                continue

            normalized_option_value = _normalize_option_value_for_storage(option_value)
            if normalized_option_value is None:
                continue
            normalized_options[option_name] = normalized_option_value

        normalized[task_name] = normalized_options

    return normalized


def _coerce_pre_tasks(
    raw_pre_tasks: Any, *, drop_disabled: bool
) -> list[PreTaskCommand]:
    """把持久化数据或已校验请求中的前置命令统一为 PreTaskCommand。

    ``drop_disabled`` 为真时（执行载荷）只保留启用且有命令的项；
    为假时（快照持久化）保留禁用项，由执行阶段过滤。
    请求路径的非法项已由 API 模型拒绝；这里只会遇到持久化文件中的损坏项，
    逐项丢弃，避免单个坏项让整个配置或定时任务无法加载。
    """
    if not isinstance(raw_pre_tasks, list):
        return []

    result: list[PreTaskCommand] = []
    for item in raw_pre_tasks:
        if isinstance(item, PreTaskCommand):
            task = item
        elif isinstance(item, dict) and isinstance(item.get("command"), str):
            task_id = item.get("id")
            timeout = item.get("timeout")
            try:
                task = PreTaskCommand(
                    id=task_id if isinstance(task_id, str) else _generate_pre_task_id(),
                    command=item["command"],
                    enabled=bool(item.get("enabled", True)),
                    timeout=int(timeout) if isinstance(timeout, (int, float)) else 30,
                )
            except (ValidationError, ValueError, OverflowError):
                continue
        else:
            continue
        if drop_disabled and (not task.enabled or not task.command.strip()):
            continue
        result.append(task)
    return result


def _normalize_option_value_for_storage(value: Any) -> TaskOptionValue | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, dict):
        return {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str)
        }
    return None


def _normalize_preset_name(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _build_task_option_maps(
    interface_model: InterfaceModel,
) -> dict[str, dict[str, Option]]:
    option_map = interface_model.option or {}
    task_option_maps: dict[str, dict[str, Option]] = {}

    for task in interface_model.task or []:
        collected: dict[str, Option] = {}
        _collect_task_options(task.option or [], option_map, collected)
        task_option_maps[task.name] = collected

    return task_option_maps


def _collect_task_options(
    option_names: list[str],
    option_map: dict[str, Option],
    target: dict[str, Option],
) -> None:
    for option_name in option_names:
        if option_name in target:
            continue
        option = option_map.get(option_name)
        if option is None:
            continue

        target[option_name] = option
        for case in option.cases or []:
            if case.option:
                _collect_task_options(case.option, option_map, target)


def _build_option_defaults(
    option_map: dict[str, Option],
) -> tuple[dict[str, TaskOptionValue], dict[str, str]]:
    defaults: dict[str, TaskOptionValue] = {}
    value_types: dict[str, str] = {}

    for option_name, option in option_map.items():
        if option.type in {"select", "scan_select", "switch"}:
            case_names = [case.name for case in option.cases or []]
            default_value = option.default_case
            if not isinstance(default_value, str) or default_value not in case_names:
                default_value = case_names[0] if case_names else ""
            defaults[option_name] = default_value
            value_types[option_name] = "string"
            continue

        if option.type == "checkbox":
            selected_values = (
                set(option.default_case)
                if isinstance(option.default_case, list)
                else set()
            )
            defaults[option_name] = [
                case.name
                for case in (option.cases or [])
                if case.name in selected_values
            ]
            value_types[option_name] = "string_list"
            continue

        if option.type == "input":
            input_defaults: dict[str, str] = {}
            for input_case in option.inputs or []:
                input_defaults[input_case.name] = input_case.default or ""
            defaults[option_name] = input_defaults
            value_types[option_name] = "object"
            continue

        if option.type == "hotkey":
            defaults[option_name] = {
                hotkey_case.name: hotkey_case.default or ""
                for hotkey_case in option.hotkeys or []
            }
            value_types[option_name] = "object"

    return defaults, value_types


def _build_option_case_name_sets(option_map: dict[str, Option]) -> dict[str, set[str]]:
    case_name_sets: dict[str, set[str]] = {}

    for option_name, option in option_map.items():
        if option.type in {"select", "scan_select", "switch", "checkbox"}:
            case_name_sets[option_name] = {case.name for case in (option.cases or [])}

    return case_name_sets


def _normalize_options_for_task(
    raw_options_for_task: Any,
    option_map: dict[str, Option],
    defaults: dict[str, TaskOptionValue],
    value_types: dict[str, str],
    case_name_sets: dict[str, set[str]],
) -> dict[str, TaskOptionValue]:
    normalized_options = {
        key: _clone_option_value(value) for key, value in defaults.items()
    }

    if not isinstance(raw_options_for_task, dict):
        return normalized_options

    for option_key, option_value in raw_options_for_task.items():
        if not isinstance(option_key, str) or option_key not in option_map:
            continue

        expected_type = value_types.get(option_key)
        if expected_type == "string" and isinstance(option_value, str):
            allowed_cases = case_name_sets.get(option_key)
            if allowed_cases is not None and option_value not in allowed_cases:
                continue
            normalized_options[option_key] = option_value
            continue

        if expected_type == "string_list" and isinstance(option_value, list):
            # 去重后计数，重复的 case 只算一次选择
            normalized_items = list(
                dict.fromkeys(item for item in option_value if isinstance(item, str))
            )
            allowed_cases = case_name_sets.get(option_key)
            if allowed_cases is not None:
                normalized_items = [
                    item for item in normalized_items if item in allowed_cases
                ]
            option = option_map[option_key]
            if len(normalized_items) < (option.min_count or 0) or (
                option.max_count is not None
                and len(normalized_items) > option.max_count
            ):
                continue
            normalized_options[option_key] = normalized_items
            continue

        if expected_type == "object" and isinstance(option_value, dict):
            option = option_map.get(option_key)
            if option is None or option.type not in {"input", "hotkey"}:
                continue

            existing_value = normalized_options.get(option_key)
            normalized_input = (
                {
                    key: item
                    for key, item in existing_value.items()
                    if isinstance(key, str) and isinstance(item, str)
                }
                if isinstance(existing_value, dict)
                else {}
            )

            fields = option.inputs if option.type == "input" else option.hotkeys
            for field in fields or []:
                field_value = option_value.get(field.name)
                if isinstance(field_value, str):
                    if option.type == "hotkey" and not _hotkey_value_supported(
                        field_value
                    ):
                        continue
                    normalized_input[field.name] = field_value

            normalized_options[option_key] = normalized_input

    return normalized_options


def _clone_option_value(value: TaskOptionValue) -> TaskOptionValue:
    """归一化并返回独立副本，避免共享的默认值列表/字典被就地修改。"""
    cloned = _normalize_option_value_for_storage(value)
    assert cloned is not None  # TaskOptionValue 的三种形态都有对应分支
    return cloned


def _apply_preset_option_value(
    option_name: str,
    value: PresetOptionValue,
    option_map: dict[str, Option],
    target_options: dict[str, TaskOptionValue],
) -> None:
    option = option_map.get(option_name)
    if option is None:
        return

    if option.type in {"input", "hotkey"}:
        if not isinstance(value, dict):
            return

        existing_value = target_options.get(option_name)
        normalized_input: dict[str, str] = (
            {
                key: item
                for key, item in existing_value.items()
                if isinstance(key, str) and isinstance(item, str)
            }
            if isinstance(existing_value, dict)
            else {}
        )

        fields = option.inputs if option.type == "input" else option.hotkeys
        for field in fields or []:
            field_value = value.get(field.name)
            if isinstance(field_value, str):
                if option.type == "hotkey" and not _hotkey_value_supported(field_value):
                    continue
                normalized_input[field.name] = field_value

        target_options[option_name] = normalized_input
        return

    if option.type == "checkbox":
        if isinstance(value, list):
            target_options[option_name] = [
                item for item in value if isinstance(item, str)
            ]
        return

    if isinstance(value, str):
        target_options[option_name] = value


def _hotkey_value_supported(value: str) -> bool:
    """只按占位符表达能力过滤；键名合法性由 maa_worker.hotkey 转换时判定。"""
    parts = [part.strip() for part in value.split("+") if part.strip()]
    return len(parts) <= 3
