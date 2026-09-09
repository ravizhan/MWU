"""PI 内容解析：i18n 文本查找与文档（URL / 文件 / 直接文本）读取。

前端 ``front/src/utils/interface/content.ts`` 的同一语义在后端的承载，
供 ``POST /api/interface/document`` 与 focus 可信回调共用。

安全约束：
- 文件读取复用 interface 根目录 containment（拒绝绝对路径/盘符/父路径/UNC）；
- 远程请求不携带 cookies、认证或 settings 中的任何凭据；
- 超时 10 秒、正文上限 1 MiB、至多 3 次重定向。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from models.interface_loader import resolve_interface_relative_path
from services.i18n_lookup import lookup_i18n_value

if TYPE_CHECKING:
    from models.interface import InterfaceModel

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = httpx.Timeout(10.0)
_MAX_BODY_BYTES = 1024 * 1024
_MAX_REDIRECTS = 3
_ALLOWED_SCHEMES = {"http", "https"}


class InterfaceContentError(ValueError):
    """内容解析失败（i18n 引用无效 / 文件不可读 / 远程获取失败）。"""


def _candidate_locale_keys(locale: str) -> list[str]:
    """语言候选：原 locale、'-'→'_' 小写、zh_cn/zh-CN 互通。"""
    keys: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        if candidate and candidate not in seen:
            seen.add(candidate)
            keys.append(candidate)

    add(locale)
    if locale in {"zh-CN", "zh_cn", "zh-CN".lower()}:
        add("zh_cn")
        add("zh-CN")
    normalized = locale.replace("-", "_").lower()
    add(normalized)
    if normalized == "zh_cn":
        add("zh-CN")
    return keys


def _is_i18n_reference(value: str) -> bool:
    """形如 ``$key.path`` 的 i18n 引用（至少一个字符的键）。"""
    return value.startswith("$") and len(value) > 1


def _is_http_url(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://"))


class InterfaceContentService:
    """以已加载 PI 及其翻译映射为上下文的内容解析服务。"""

    def __init__(
        self,
        interface: InterfaceModel,
        interface_base_dir: Path,
        translations: dict[str, Any] | None = None,
    ):
        self._interface = interface
        self._base_dir = interface_base_dir
        self._translations = translations or {}

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def resolve_i18n(self, value: str | None, locale: str) -> str | None:
        """解析 ``$key`` i18n 引用；非引用或未命中返回 None。"""
        if not value or not _is_i18n_reference(value):
            return None
        ref = value[1:]
        for locale_key in _candidate_locale_keys(locale):
            mapping = self._translations.get(locale_key)
            if not isinstance(mapping, dict):
                continue
            resolved = lookup_i18n_value(mapping, ref)
            if resolved is not None:
                return resolved
        return None

    # ------------------------------------------------------------------
    # 文本
    # ------------------------------------------------------------------

    def resolve_text(self, value: str | None, locale: str, fallback: str = "") -> str:
        """解析展示文本：先 i18n，再原样返回；空值返回 fallback。"""
        if not value or not value.strip():
            return fallback
        resolved = self.resolve_i18n(value, locale)
        if resolved is not None:
            return resolved
        return value

    # ------------------------------------------------------------------
    # 文档
    # ------------------------------------------------------------------

    def _read_document_file(self, relative_path: str) -> str:
        try:
            resolved = resolve_interface_relative_path(
                self._base_dir, relative_path, field_name="document"
            )
        except ValueError as exc:
            raise InterfaceContentError(str(exc)) from exc
        try:
            return resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise InterfaceContentError(
                f"文档文件不可读: {relative_path}: {exc}"
            ) from exc

    def _fetch_document_url(self, url: str) -> str:
        try:
            with httpx.Client(
                timeout=_HTTP_TIMEOUT,
                follow_redirects=True,
                max_redirects=_MAX_REDIRECTS,
                trust_env=False,
            ) as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            raise InterfaceContentError(f"文档获取失败: {exc}") from exc
        if response.status_code != 200:
            raise InterfaceContentError(f"文档获取失败: HTTP {response.status_code}")
        body = response.content
        if len(body) > _MAX_BODY_BYTES:
            raise InterfaceContentError(f"文档超过大小上限 ({_MAX_BODY_BYTES} bytes)")
        return response.text

    def resolve_document(self, value: str | None, locale: str) -> str:
        """解析文档内容：i18n → HTTP(S) URL / 根目录内文件 / 直接文本。"""
        text = self.resolve_text(value, locale)
        if not text:
            raise InterfaceContentError("文档内容为空")
        if _is_http_url(text):
            return self._fetch_document_url(text)
        # 含路径分隔符且无换行的短值视为文件引用；其余按直接文本处理。
        if (
            "/" in text
            and "\n" not in text
            and len(text) < 512
            and not text.startswith("<")
        ):
            return self._read_document_file(text)
        return text

    # ------------------------------------------------------------------
    # 允许的文档来源集合
    # ------------------------------------------------------------------

    def collect_document_sources(self) -> dict[str, bool]:
        """当前 PI 中所有文档字段及其翻译值的来源集合。

        键为原始值（或 ``$key`` 引用），值恒 True（存在即允许）。
        仅用于白名单校验，不开放任意 URL 代理或任意路径读取。
        """
        sources: dict[str, bool] = {}

        def add(value: str | None) -> None:
            if isinstance(value, str) and value.strip():
                sources[value] = True
                # 该值在各语言下的解析结果（可能是 URL/文件路径）同样允许
                for locale in ("zh-CN", "en-US"):
                    resolved = self.resolve_text(value, locale)
                    if isinstance(resolved, str) and resolved.strip():
                        sources[resolved] = True

        interface = self._interface
        add(interface.welcome)
        add(interface.description)
        for task in interface.task or []:
            for doc in (task.doc, task.desc, task.description):
                if isinstance(doc, str):
                    add(doc)
                elif isinstance(doc, list):
                    for item in doc:
                        add(item)
        for pretask in _pretask_list(interface):
            add(pretask.description)
        for group in interface.group or []:
            add(group.description)
        for option in (interface.option or {}).values():
            add(option.description)
            for case in option.cases or []:
                add(case.description)
        for resource in interface.resource or []:
            add(resource.description)
        for controller in interface.controller or []:
            add(controller.description)
        for preset in interface.preset or []:
            add(preset.description)
        for section in interface.setting or []:
            add(section.description)
        return sources


def _pretask_list(interface: "InterfaceModel") -> list[Any]:
    pretask = interface.pretask
    if pretask is None:
        return []
    if isinstance(pretask, list):
        return pretask
    return [pretask]
