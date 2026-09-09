"""共享 PI 翻译映射查找：嵌套路径优先，再查完整平键。

供 AgentService（自定义动作/识别的 i18n）与 InterfaceContentService
（文档/展示文本 i18n）复用，保证两处查找语义一致。
"""

from __future__ import annotations

from typing import Any


def lookup_i18n_value(mapping: dict[str, Any], ref: str) -> str | None:
    """在翻译映射中解析 ``ref``（不含 ``$`` 前缀）。

    先按 ``.`` 拆分的嵌套路径查找，再退回到完整平键；命中非空字符串返回，
    否则返回 None。
    """
    if not isinstance(mapping, dict) or not mapping or not ref:
        return None

    current: Any = mapping
    for part in ref.split("."):
        if not isinstance(current, dict) or part not in current:
            current = None
            break
        current = current[part]
    if isinstance(current, str) and current:
        return current

    flat_value = mapping.get(ref)
    if isinstance(flat_value, str) and flat_value:
        return flat_value
    return None
