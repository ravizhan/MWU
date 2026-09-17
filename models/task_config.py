from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
        description="队列任务ID列表（有序，允许重复，表示执行顺序）",
    )
    taskOptions: TaskOptionsByTask = Field(
        default_factory=dict,
        description="任务选项配置，key为任务ID，value为该任务的选项映射",
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

    return TaskConfigModel(
        selectedPreset=selected_preset,
        presets=preset_snapshots,
    )


def normalize_snapshot(
    snapshot: TaskPresetSnapshotModel | dict[str, Any] | None,
    interface_model: InterfaceModel,
) -> TaskPresetSnapshotModel:
    valid_task_ids = {task.entry for task in (interface_model.task or [])}

    raw_snapshot = _normalize_raw_snapshot(snapshot)
    normalized_tasks = [
        task_id for task_id in raw_snapshot["tasks"] if task_id in valid_task_ids
    ]
    raw_task_options = raw_snapshot["taskOptions"]
    raw_pre_tasks = raw_snapshot.get("preTasks", [])

    normalized_options = normalize_task_options_by_task(
        raw_task_options,
        list(dict.fromkeys(normalized_tasks)),
        interface_model,
    )

    normalized_pre_tasks = _normalize_raw_pre_tasks(raw_pre_tasks)
    parsed_pre_tasks: list[PreTaskCommand] = []
    for item in normalized_pre_tasks:
        try:
            parsed_pre_tasks.append(
                PreTaskCommand(
                    id=item.get("id", _generate_pre_task_id()),
                    command=item["command"],
                    enabled=item["enabled"],
                    timeout=item["timeout"],
                )
            )
        except Exception:
            continue

    return TaskPresetSnapshotModel(
        tasks=normalized_tasks,
        taskOptions=normalized_options,
        preTasks=parsed_pre_tasks,
    )


def normalize_task_options_by_task(
    raw_task_options: dict[str, Any] | None,
    task_ids: list[str],
    interface_model: InterfaceModel,
) -> TaskOptionsByTask:
    task_option_maps = _build_task_option_maps(interface_model)
    normalized: TaskOptionsByTask = {}
    normalized_task_ids = [task_id for task_id in task_ids if isinstance(task_id, str)]

    for task_id in normalized_task_ids:
        option_map = task_option_maps.get(task_id, {})
        defaults, value_types = _build_option_defaults(option_map)
        case_name_sets = _build_option_case_name_sets(option_map)

        raw_options_for_task = None
        if isinstance(raw_task_options, dict):
            raw_options_for_task = raw_task_options.get(task_id)

        normalized[task_id] = _normalize_options_for_task(
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
    all_options = interface_model.option or {}
    option_map = {
        option_name: all_options[option_name]
        for option_name in (interface_model.global_option or [])
        if option_name in all_options
    }
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
    valid_task_ids = {task.entry for task in (interface_model.task or [])}
    normalized_task_list: list[str] = []

    if isinstance(raw_task_list, list):
        for task_id in raw_task_list:
            if not isinstance(task_id, str):
                continue
            if task_id not in valid_task_ids:
                continue
            normalized_task_list.append(task_id)

    normalized_task_options = normalize_task_options_by_task(
        raw_task_options if isinstance(raw_task_options, dict) else None,
        normalized_task_list,
        interface_model,
    )

    normalized_pre_tasks: list[PreTaskCommand] = []
    if isinstance(raw_pre_tasks, list):
        for item in raw_pre_tasks:
            if isinstance(item, PreTaskCommand):
                if item.enabled and item.command.strip():
                    normalized_pre_tasks.append(item)
            elif isinstance(item, dict):
                command = item.get("command", "")
                enabled = bool(item.get("enabled", True))
                timeout = item.get("timeout", 30)
                task_id = item.get("id")
                if enabled and isinstance(command, str) and command.strip():
                    try:
                        validated = PreTaskCommand(
                            id=task_id
                            if isinstance(task_id, str)
                            else _generate_pre_task_id(),
                            command=command,
                            enabled=True,
                            timeout=int(timeout)
                            if isinstance(timeout, (int, float))
                            else 30,
                        )
                        normalized_pre_tasks.append(validated)
                    except Exception:
                        continue

    return normalized_task_list, normalized_task_options, normalized_pre_tasks


def build_interface_preset_snapshot(
    interface_model: InterfaceModel, preset: Preset
) -> TaskPresetSnapshotModel:
    task_name_to_entry = {
        task.name: task.entry for task in (interface_model.task or [])
    }
    task_option_maps = _build_task_option_maps(interface_model)

    task_options_by_task: TaskOptionsByTask = {}
    tasks: list[str] = []

    for preset_task in preset.task or []:
        task_entry = task_name_to_entry.get(preset_task.name)
        if task_entry is None or preset_task.enabled is False:
            continue

        tasks.append(task_entry)

        option_map = task_option_maps.get(task_entry, {})
        defaults, _ = _build_option_defaults(option_map)
        target_options = task_options_by_task.setdefault(task_entry, defaults)
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
    if isinstance(snapshot, TaskPresetSnapshotModel):
        return {
            "tasks": [
                task_id for task_id in snapshot.tasks if isinstance(task_id, str)
            ],
            "taskOptions": _normalize_raw_task_options(snapshot.taskOptions),
            "preTasks": _normalize_raw_pre_tasks(snapshot.preTasks),
        }

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
        "preTasks": _normalize_raw_pre_tasks(snapshot.get("preTasks")),
    }


def _normalize_raw_task_options(value: Any) -> dict[str, dict[str, TaskOptionValue]]:
    normalized: dict[str, dict[str, TaskOptionValue]] = {}
    if not isinstance(value, dict):
        return normalized

    for task_id, option_map in value.items():
        if not isinstance(task_id, str) or not isinstance(option_map, dict):
            continue

        normalized_options: dict[str, TaskOptionValue] = {}
        for option_name, option_value in option_map.items():
            if not isinstance(option_name, str):
                continue

            normalized_option_value = _normalize_option_value_for_storage(option_value)
            if normalized_option_value is None:
                continue
            normalized_options[option_name] = normalized_option_value

        normalized[task_id] = normalized_options

    return normalized


def _normalize_raw_pre_tasks(value: Any) -> list[dict[str, Any]]:
    """Normalize preTasks for JSON serialization."""
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, PreTaskCommand):
                result.append(
                    {
                        "id": item.id,
                        "command": item.command,
                        "enabled": item.enabled,
                        "timeout": item.timeout,
                    }
                )
            elif isinstance(item, dict):
                command = item.get("command", "")
                enabled = item.get("enabled", True)
                timeout = item.get("timeout", 30)
                task_id = item.get("id")
                if isinstance(command, str):
                    result.append(
                        {
                            "id": task_id
                            if isinstance(task_id, str)
                            else _generate_pre_task_id(),
                            "command": command,
                            "enabled": bool(enabled),
                            "timeout": int(timeout)
                            if isinstance(timeout, (int, float))
                            else 30,
                        }
                    )
        return result
    return []


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
        task_option_maps[task.entry] = collected

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
            default_value = option.default_case or (
                option.cases[0].name if option.cases else ""
            )
            defaults[option_name] = (
                default_value if isinstance(default_value, str) else ""
            )
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
            normalized_items = [item for item in option_value if isinstance(item, str)]
            allowed_cases = case_name_sets.get(option_key)
            if allowed_cases is not None:
                normalized_items = [
                    item for item in normalized_items if item in allowed_cases
                ]
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
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, dict):
        return {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str)
        }
    return value


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
    parts = [part.strip() for part in value.split("+") if part.strip()]
    unsupported_keys = {"META", "SUPER", "WIN", "CMD", "COMMAND"}
    return len(parts) <= 3 and not any(
        part.upper() in unsupported_keys for part in parts
    )
