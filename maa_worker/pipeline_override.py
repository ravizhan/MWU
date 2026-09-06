import copy
from typing import TYPE_CHECKING, cast

import json_utils as json
from maa_worker.hotkey import hotkey_value_to_codes
from models.interface import PipelineOverride, is_option_applicable_any
from models.scheduler import TaskOptionValue

if TYPE_CHECKING:
    from maa_utils import MaaWorker


class PipelineOverrideService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _deep_merge(
        self,
        base: PipelineOverride | None,
        override: PipelineOverride | None,
    ) -> PipelineOverride:
        merged: PipelineOverride = copy.deepcopy(base) if base else {}
        if not override:
            return merged

        for key, value in override.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = self._deep_merge(existing, value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    def _get_current_task_definition(self, task_name: str):
        return next(
            (
                task
                for task in self.worker.interface.task or []
                if task.name == task_name
            ),
            None,
        )

    def _is_option_active_for_context(self, option, controller_names: set[str]) -> bool:
        return is_option_applicable_any(
            option,
            controller_names,
            self.worker.device_state.current_resource_name,
        )

    def _normalize_choice_value(
        self, option_name: str, option, options: dict[str, TaskOptionValue]
    ) -> str:
        assert option.cases is not None
        case_names = [case.name for case in option.cases]
        default_value = (
            option.default_case if isinstance(option.default_case, str) else ""
        )
        if default_value not in case_names:
            default_value = case_names[0] if case_names else ""

        raw_value = options.get(option_name)
        if isinstance(raw_value, str) and raw_value in case_names:
            return raw_value
        return default_value

    def _normalize_checkbox_values(
        self,
        option_name: str,
        option,
        options: dict[str, TaskOptionValue],
    ) -> list[str]:
        assert option.cases is not None
        case_order = [case.name for case in option.cases]
        default_values = (
            option.default_case if isinstance(option.default_case, list) else []
        )
        raw_value = options.get(option_name)

        if raw_value is None:
            selected_values = [
                value for value in default_values if isinstance(value, str)
            ]
        elif isinstance(raw_value, list):
            selected_values = [value for value in raw_value if isinstance(value, str)]
        elif isinstance(raw_value, str):
            try:
                parsed_value = json.loads(raw_value)
            except json.JSONDecodeError:
                parsed_value = [raw_value] if raw_value in case_order else []

            if isinstance(parsed_value, list):
                selected_values = [
                    value for value in parsed_value if isinstance(value, str)
                ]
            else:
                selected_values = []
        else:
            selected_values = []

        selected_set = set(selected_values)
        return [case_name for case_name in case_order if case_name in selected_set]

    def _coerce_input_value(
        self, raw_value: str, pipeline_type: str | None
    ) -> tuple[object, str]:
        if pipeline_type == "bool":
            typed_value = raw_value.lower() in {"true", "1", "yes", "y", "on"}
            return typed_value, "true" if typed_value else "false"
        if pipeline_type == "int":
            typed_value = int(raw_value)
            return typed_value, str(typed_value)
        return raw_value, raw_value

    def _substitute_placeholders(
        self,
        value,
        typed_replacements: dict[str, object],
        text_replacements: dict[str, str],
    ):
        if isinstance(value, dict):
            return {
                key: self._substitute_placeholders(
                    nested_value,
                    typed_replacements,
                    text_replacements,
                )
                for key, nested_value in value.items()
            }
        if isinstance(value, list):
            return [
                self._substitute_placeholders(
                    item,
                    typed_replacements,
                    text_replacements,
                )
                for item in value
            ]
        if isinstance(value, str):
            if value in typed_replacements:
                return copy.deepcopy(typed_replacements[value])

            substituted = value
            for placeholder, replacement in text_replacements.items():
                substituted = substituted.replace(placeholder, replacement)
            return substituted
        return copy.deepcopy(value)

    def _assign_scan_select_attach_value(
        self,
        value,
        option_name: str,
        selected_value: str,
    ):
        if isinstance(value, dict):
            copied = {
                key: self._assign_scan_select_attach_value(
                    nested_value,
                    option_name,
                    selected_value,
                )
                for key, nested_value in value.items()
            }
            attach_value = copied.get("attach")
            if isinstance(attach_value, dict) and option_name in attach_value:
                updated_attach = copy.deepcopy(attach_value)
                updated_attach[option_name] = selected_value
                copied["attach"] = updated_attach
            return copied
        if isinstance(value, list):
            return [
                self._assign_scan_select_attach_value(
                    item,
                    option_name,
                    selected_value,
                )
                for item in value
            ]
        return copy.deepcopy(value)

    def _build_input_override(
        self,
        option_name: str,
        option,
        options: dict[str, TaskOptionValue],
    ) -> PipelineOverride:
        if not option.pipeline_override or not option.inputs:
            return {}

        typed_replacements: dict[str, object] = {}
        text_replacements: dict[str, str] = {}
        for field in option.inputs:
            raw_option_value = options.get(option_name)
            raw_text = field.default or ""
            if isinstance(raw_option_value, dict):
                field_value = raw_option_value.get(field.name)
                if isinstance(field_value, str):
                    raw_text = field_value
            elif isinstance(raw_option_value, str):
                raw_text = raw_option_value
            elif isinstance(raw_option_value, list):
                raw_text = raw_option_value[0] if raw_option_value else ""

            typed_value, text_value = self._coerce_input_value(
                raw_text,
                field.pipeline_type,
            )
            placeholder = f"{{{field.name}}}"
            typed_replacements[placeholder] = typed_value
            text_replacements[placeholder] = text_value

        return cast(
            PipelineOverride,
            self._substitute_placeholders(
                option.pipeline_override,
                typed_replacements,
                text_replacements,
            ),
        )

    def _build_hotkey_override(
        self,
        option_name: str,
        option,
        options: dict[str, TaskOptionValue],
        controller_type: str | None,
        *,
        use_win32_vk_code: bool = False,
    ) -> PipelineOverride:
        if not option.pipeline_override or not option.hotkeys:
            return {}

        typed_replacements: dict[str, object] = {}
        raw_option_value = options.get(option_name)
        for field in option.hotkeys:
            raw_text = field.default or ""
            if isinstance(raw_option_value, dict):
                field_value = raw_option_value.get(field.name)
                if isinstance(field_value, str):
                    raw_text = field_value

            try:
                primary_code, modifier1_code, modifier2_code = hotkey_value_to_codes(
                    raw_text,
                    controller_type,
                    use_win32_vk_code=use_win32_vk_code,
                )
            except ValueError as exc:
                raise ValueError(
                    f"选项 {option_name} 的快捷键字段 {field.name} 配置错误: {exc}"
                ) from exc
            typed_replacements[f"{{{field.name}}}"] = primary_code
            typed_replacements[f"{{{field.name}.primary}}"] = primary_code
            typed_replacements[f"{{{field.name}.modifier1}}"] = modifier1_code
            typed_replacements[f"{{{field.name}.modifier2}}"] = modifier2_code

        return cast(
            PipelineOverride,
            self._substitute_placeholders(
                option.pipeline_override,
                typed_replacements,
                {},
            ),
        )

    def _build_scan_select_override(
        self,
        option_name: str,
        option,
        options: dict[str, TaskOptionValue],
    ) -> PipelineOverride:
        if not option.pipeline_override:
            return {}

        if option.cases is None:
            return copy.deepcopy(option.pipeline_override)

        selected_value = self._normalize_choice_value(option_name, option, options)
        return cast(
            PipelineOverride,
            self._assign_scan_select_attach_value(
                option.pipeline_override,
                option_name,
                selected_value,
            ),
        )

    def _build_option_override(
        self,
        option_name: str,
        options: dict[str, TaskOptionValue],
        controller_names: set[str],
        lineage: set[str] | None = None,
    ) -> PipelineOverride:
        option_map = self.worker.interface.option or {}
        option = option_map.get(option_name)
        if option is None:
            return {}
        if not self._is_option_active_for_context(option, controller_names):
            return {}

        lineage = lineage or set()
        if option_name in lineage:
            return {}
        next_lineage = {*lineage, option_name}

        merged: PipelineOverride = {}
        if option.type == "hotkey":
            controller_definitions = (
                self.worker.device.get_active_controller_definitions()
            )
            controller_type = (
                controller_definitions[0].type if controller_definitions else None
            )
            if (
                controller_definitions
                and controller_type == "Linux"
                and controller_definitions[0].linux
                and controller_definitions[0].linux.use_win32_vk_code
            ):
                return self._deep_merge(
                    merged,
                    self._build_hotkey_override(
                        option_name,
                        option,
                        options,
                        "Linux",
                        use_win32_vk_code=True,
                    ),
                )
            return self._deep_merge(
                merged,
                self._build_hotkey_override(
                    option_name,
                    option,
                    options,
                    controller_type,
                ),
            )

        if option.type == "input":
            return self._deep_merge(
                merged,
                self._build_input_override(option_name, option, options),
            )

        if option.type == "scan_select":
            merged = self._deep_merge(
                merged,
                self._build_scan_select_override(option_name, option, options),
            )
        elif option.pipeline_override:
            merged = self._deep_merge(merged, option.pipeline_override)

        if option.type in {"select", "switch"} and option.cases:
            active_case_name = self._normalize_choice_value(
                option_name, option, options
            )
            active_case = next(
                (case for case in option.cases if case.name == active_case_name),
                None,
            )
            if active_case and active_case.pipeline_override:
                merged = self._deep_merge(merged, active_case.pipeline_override)
            if active_case and active_case.option:
                merged = self._deep_merge(
                    merged,
                    self._build_option_group_override(
                        active_case.option,
                        options,
                        controller_names,
                        next_lineage,
                    ),
                )
            return merged

        if option.type == "checkbox" and option.cases:
            selected_case_names = set(
                self._normalize_checkbox_values(option_name, option, options)
            )
            for case in option.cases:
                if case.name not in selected_case_names:
                    continue
                if case.pipeline_override:
                    merged = self._deep_merge(merged, case.pipeline_override)
                if case.option:
                    merged = self._deep_merge(
                        merged,
                        self._build_option_group_override(
                            case.option,
                            options,
                            controller_names,
                            next_lineage,
                        ),
                    )
        return merged

    def _build_option_group_override(
        self,
        option_names: list[str],
        options: dict[str, TaskOptionValue],
        controller_names: set[str],
        lineage: set[str] | None = None,
    ) -> PipelineOverride:
        merged: PipelineOverride = {}
        for option_name in option_names:
            merged = self._deep_merge(
                merged,
                self._build_option_override(
                    option_name,
                    options,
                    controller_names,
                    lineage,
                ),
            )
        return merged

    def build_task_pipeline_override(
        self,
        task_name: str,
        options: dict[str, TaskOptionValue],
        global_options: dict[str, TaskOptionValue] | None = None,
    ) -> PipelineOverride:
        task_definition = self._get_current_task_definition(task_name)
        if task_definition is None:
            return {}

        controller_names = self.worker.device.get_active_controller_names()
        resource_definition = self.worker.device.get_current_resource_definition()
        controller_option_names: list[str] = []
        for controller in self.worker.device.get_active_controller_definitions():
            if controller.option:
                controller_option_names.extend(controller.option)

        merged = copy.deepcopy(task_definition.pipeline_override) or {}
        merged = self._deep_merge(
            merged,
            self._build_option_group_override(
                self.worker.interface.global_option or [],
                global_options or {},
                controller_names,
            ),
        )
        option_groups = [
            resource_definition.option
            if resource_definition and resource_definition.option
            else [],
            controller_option_names,
            task_definition.option or [],
        ]
        for option_names in option_groups:
            merged = self._deep_merge(
                merged,
                self._build_option_group_override(
                    option_names,
                    options,
                    controller_names,
                ),
            )
        return merged
