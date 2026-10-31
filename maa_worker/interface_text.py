from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from maa_utils import MaaWorker


def language_key(ui_language: str, languages: dict[str, str] | None) -> str:
    """把 UI 语言（如 en-US）映射为 interface.languages 的键（如 en_us）。"""
    normalized = ui_language.replace("-", "_").lower()
    for key in languages or {}:
        if key.replace("-", "_").lower() == normalized:
            return key
    return normalized


class InterfaceText:
    """按当前 UI 语言解析 interface 中的 `$key` 文本。"""

    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def language(self) -> str:
        settings = self.worker.state.settings
        ui_language = settings.ui.language if settings is not None else None
        return language_key(ui_language or "zh-CN", self.worker.interface.languages)

    def resolve(self, value: str | None) -> str | None:
        if not value or not value.startswith("$"):
            return value
        translations = self.worker.context.interface_translations or {}
        mapping = translations.get(self.language()) or {}
        key = value[1:]
        found: Any = mapping.get(key)
        if not isinstance(found, str):
            found = mapping
            for part in key.split("."):
                found = found.get(part) if isinstance(found, dict) else None
        return found if isinstance(found, str) else None

    def resolve_tree(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {key: self.resolve_tree(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self.resolve_tree(item) for item in payload]
        if isinstance(payload, str):
            resolved = self.resolve(payload)
            return payload if resolved is None else resolved
        return payload

    def app_name(self) -> str:
        interface = self.worker.interface
        return self.resolve(interface.title) or self.resolve(interface.label) or "MWU"
