import importlib.metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import json_utils as json
from maa_worker.agent_loader import load_agents

if TYPE_CHECKING:
    from maa_utils import MaaWorker

from services.i18n_lookup import lookup_i18n_value
from services.runtime_info import mwu_version, normalize_language


PI_INTERFACE_VERSION = "v2.9.2"


class AgentService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _get_agent_configs(self):
        if self.worker.interface.agent is None:
            return []
        if isinstance(self.worker.interface.agent, list):
            return self.worker.interface.agent
        return [self.worker.interface.agent]

    def _load_i18n_mapping(self) -> dict[str, Any]:
        context = self.worker.context
        """加载全部语言映射（不再只缓存第一种语言）。"""
        if context.i18n_text_mapping is not None:
            return context.i18n_text_mapping

        mappings: dict[str, Any] = {}
        for locale, language_file in (self.worker.interface.languages or {}).items():
            if not isinstance(language_file, str) or not language_file.strip():
                continue
            language_path = (context.interface_base_dir / language_file).resolve()
            try:
                with language_path.open("r", encoding="utf-8") as f:
                    mapping = json.load(f)
                if isinstance(mapping, dict):
                    mappings[locale] = mapping
            except Exception as exc:
                self.worker.events.send_log(f"加载语言映射失败: {exc}")
        context.i18n_text_mapping = mappings
        return mappings

    def _lookup_i18n_text(self, key: str) -> str | None:
        return self._lookup_i18n_text_for_language(key, self._client_language())

    def _client_language(self) -> str:
        """运行开始时保存的 ui.language 快照（规范化为 PI zh_cn/en_us）。"""
        settings = self.worker.state.settings
        ui_language = getattr(settings, "ui", None) if settings is not None else None
        raw = getattr(ui_language, "language", "zh-CN")
        return normalize_language(raw if isinstance(raw, str) else "zh-CN")

    def _lookup_i18n_text_for_language(self, key: str, pi_language: str) -> str | None:
        mappings = self._load_i18n_mapping()
        mapping = mappings.get(pi_language)
        if not isinstance(mapping, dict) or not mapping:
            return None

        normalized_key = key.removeprefix("$")
        if not normalized_key:
            return None

        return lookup_i18n_value(mapping, normalized_key)

    def _resolve_i18n_payload(self, payload: Any):
        if isinstance(payload, dict):
            return {
                key: self._resolve_i18n_payload(value) for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self._resolve_i18n_payload(item) for item in payload]
        if isinstance(payload, str) and payload.startswith("$"):
            translated = self._lookup_i18n_text(payload)
            if translated is not None:
                return translated
        return payload

    def _get_selected_controller_payload(self) -> dict[str, Any]:
        controller = self.worker.device.get_controller_definition(
            self.worker.device_state.controller_name
        )
        if controller is None:
            return {}
        payload = controller.model_dump(exclude_none=True, mode="json")
        resolved_payload = self._resolve_i18n_payload(payload)
        if isinstance(resolved_payload, dict):
            return resolved_payload
        return {}

    def _get_selected_resource_payload(self) -> dict[str, Any]:
        resource_definition = self.worker.device.get_current_resource_definition()
        if resource_definition is None:
            return {}
        payload = resource_definition.model_dump(exclude_none=True, mode="json")
        resolved_payload = self._resolve_i18n_payload(payload)
        if isinstance(resolved_payload, dict):
            return resolved_payload
        return {}

    def build_pi_env(self) -> dict[str, str]:
        controller_payload = self._get_selected_controller_payload()
        resource_payload = self._get_selected_resource_payload()
        client_language = self._client_language()
        return {
            "PI_INTERFACE_VERSION": PI_INTERFACE_VERSION,
            "PI_CLIENT_NAME": "MWU",
            "PI_CLIENT_VERSION": mwu_version(),
            "PI_CLIENT_LANGUAGE": client_language,
            "PI_CLIENT_MAAFW_VERSION": "v" + importlib.metadata.version("maafw"),
            "PI_VERSION": self.worker.interface.version or "",
            "PI_CONTROLLER": json.dumps(
                controller_payload, ensure_ascii=False, separators=(",", ":")
            ),
            "PI_RESOURCE": json.dumps(
                resource_payload, ensure_ascii=False, separators=(",", ":")
            ),
        }

    def load(self, pi_env: dict[str, str] | None = None):
        processes = load_agents(
            self._get_agent_configs(),
            self.worker,
            pi_env=pi_env,
        )
        self.worker.agent_state.processes = processes

    def ensure_started_once(self) -> bool:
        configs = self._get_agent_configs()
        if not configs:
            return True

        state = self.worker.agent_state
        if state.started_once:
            return state.start_succeeded

        with state.start_lock:
            if state.started_once:
                return state.start_succeeded

            state.started_once = True
            try:
                state.pi_env = self.build_pi_env()
                self.load(state.pi_env)
                state.start_succeeded = True
                self.worker.events.send_log("Agent加载完成")
            except Exception as exc:
                state.start_succeeded = False
                state.start_error = str(exc) or "未知错误"
                self.worker.events.send_log(f"Agent初始化失败: {state.start_error}")

        return state.start_succeeded
