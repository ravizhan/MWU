from importlib import metadata
from typing import TYPE_CHECKING, Any

import json_utils as json
from maa_worker.agent_loader import load_agents

if TYPE_CHECKING:
    from maa_utils import MaaWorker


PI_INTERFACE_VERSION = "v2.6.0"
PI_CLIENT_LANGUAGE = "zh_cn"


class AgentService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _get_agent_configs(self):
        if self.worker.interface.agent is None:
            return []
        if isinstance(self.worker.interface.agent, list):
            return self.worker.interface.agent
        return [self.worker.interface.agent]

    def _lookup_i18n_text(self, key: str) -> str | None:
        # main.load_interface_translations() 已按路径约束加载全部语言文件
        translations = self.worker.context.interface_translations or {}
        mapping = translations.get(PI_CLIENT_LANGUAGE)
        if not isinstance(mapping, dict):
            return None

        normalized_key = key.removeprefix("$")
        if not normalized_key:
            return None

        current: Any = mapping
        for part in normalized_key.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if isinstance(current, str):
            return current

        flat_value = mapping.get(normalized_key)
        if isinstance(flat_value, str):
            return flat_value
        return None

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
        with open("version", encoding="utf-8") as f:
            client_version = f.read().strip()
        return {
            "PI_INTERFACE_VERSION": PI_INTERFACE_VERSION,
            "PI_CLIENT_NAME": "MWU",
            "PI_CLIENT_VERSION": client_version,
            "PI_CLIENT_LANGUAGE": PI_CLIENT_LANGUAGE,
            "PI_CLIENT_MAAFW_VERSION": "v" + metadata.version("maafw"),
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
