"""
Focus 协议实现 — 严格遵循 PI V2 官方规范。

将 MAA 底层 sink 回调统一解析为 FocusDisplayEvent，
按 `display` 字段指定的渠道（log / toast / notification / dialog / modal）分发。
"""

from dataclasses import dataclass, field
from typing import TypedDict

from models.api import RealtimeEventLevel

# ---------------------------------------------------------------------------
# Supported display channels (PI V2)
# ---------------------------------------------------------------------------

DISPLAY_LOG = "log"
DISPLAY_TOAST = "toast"
DISPLAY_NOTIFICATION = "notification"
DISPLAY_DIALOG = "dialog"
DISPLAY_MODAL = "modal"

# ---------------------------------------------------------------------------
# FocusTemplate — 表示 interface.json 中一条 focus 模板
# ---------------------------------------------------------------------------


class FocusRawObject(TypedDict, total=False):
    """协议规定的 focus 对象格式。"""

    content: str
    display: str | list[str]


@dataclass
class FocusTemplate:
    """Focus 模板（对象格式或字符串简写）。

    简写纯字符串在 from_raw() 中自动升级：
        "text" → FocusTemplate(content="text", display=["log"])
    """

    content: str | None
    display: list[str] = field(default_factory=lambda: [DISPLAY_LOG])

    # ---- 工厂方法 ------------------------------------------------------------

    @staticmethod
    def from_raw(raw: str | FocusRawObject) -> "FocusTemplate":
        """从 interface.json 的 focus 值构造模板。

        - str : 简写，等价 display=["log"]
        - dict: 完整对象 { "content": "...", "display": [...] }
        """
        if isinstance(raw, str):
            return FocusTemplate(content=raw, display=[DISPLAY_LOG])

        display = raw.get("display", DISPLAY_LOG)
        return FocusTemplate(
            content=raw.get("content"),
            display=[display] if isinstance(display, str) else display,
        )


# ---------------------------------------------------------------------------
# AutoFocusGenerator — 无 focus 定义时生成默认日志文本
# ---------------------------------------------------------------------------

# 复用原 _PREFIX_MAP 的类别标签
_CATEGORY_LABEL: dict[str, str] = {
    "Resource.Loading": "资源",
    "Controller.Action": "控制器",
    "Tasker.Task": "任务",
    "Node.Recognition": "识别",
    "Node.Action": "动作",
    "Node.WaitFreezes": "等待",
    "Node.NextList": "下一节点",
    "Node.PipelineNode": "流水线",
    "Node.RecognitionNode": "识别节点",
    "Node.ActionNode": "动作节点",
}

_STATUS_CN: dict[str, str] = {
    "Starting": "开始",
    "Succeeded": "成功",
    "Failed": "失败",
}


class AutoFocusGenerator:
    """当 details.focus 无对应条目时，根据消息类型自动生成人类可读的默认文本。"""

    @staticmethod
    def generate(msg: str, details: dict) -> str:
        status_suffix = msg.rsplit(".", 1)[-1] if "." in msg else msg
        status_cn = _STATUS_CN.get(status_suffix, status_suffix)

        # 查找类别标签
        category = "回调"
        for prefix, label in _CATEGORY_LABEL.items():
            if msg.startswith(prefix):
                category = label
                break

        name = details.get("name", "")
        entry = details.get("entry", "")
        path = details.get("path", "")
        res_type = details.get("type", "")
        uuid = details.get("uuid", "")
        hash_val = details.get("hash", "")

        parts: list[str] = []

        if msg.startswith("Tasker.Task"):
            if entry:
                parts.append(f"任务 [{entry}]")
            if uuid:
                parts.append(f"ID={str(uuid)[:8]}")
            parts.append(status_cn)

        elif msg.startswith("Node."):
            parts.append(name if name else category)
            parts.append(status_cn)

        elif msg.startswith("Resource."):
            if path:
                parts.append(f"路径={path}")
            if res_type:
                parts.append(f"类型={res_type}")
            if hash_val:
                parts.append(f"hash={str(hash_val)[:8]}")
            parts.append(status_cn)

        elif msg.startswith("Controller."):
            parts.append(status_cn)

        else:
            parts.append(msg)

        return " ".join(parts) if parts else msg


# ---------------------------------------------------------------------------
# FocusDisplayEvent — 统一事件输出模型
# ---------------------------------------------------------------------------


@dataclass
class FocusDisplayEvent:
    """所有 sink 回调最终产出的统一事件。

    对应官方协议 Client 处理流程第 6 步：
    「根据 display 指定的渠道将文本展示给用户」。
    """

    content: str
    display_channels: list[str]
    level: RealtimeEventLevel = "info"
    raw_msg: str = ""

    @property
    def has_log(self) -> bool:
        return DISPLAY_LOG in self.display_channels

    @property
    def has_toast(self) -> bool:
        return DISPLAY_TOAST in self.display_channels

    @property
    def has_notification(self) -> bool:
        return DISPLAY_NOTIFICATION in self.display_channels

    @property
    def has_dialog(self) -> bool:
        return DISPLAY_DIALOG in self.display_channels

    @property
    def has_modal(self) -> bool:
        return DISPLAY_MODAL in self.display_channels


# ---------------------------------------------------------------------------
# UnifiedFocusResolver — 统一解析入口
# ---------------------------------------------------------------------------


class UnifiedFocusResolver:
    """将 MAA 原始 (msg, details) 统一解析为 FocusDisplayEvent。

    严格遵循 PI V2 Client 处理流程：
    1. 从 details.focus[msg] 查找模板
    2. 简写字符串自动升级为 {content, display:["log"]}
    3. 无匹配时使用 AutoFocusGenerator
    4. 占位符替换 {name}/{task_id}/{entry}/{list}
    5. 推导 level
    6. 返回 FocusDisplayEvent；模板内容为空时不产生展示事件
    """

    @staticmethod
    def resolve(msg: str, details: dict) -> FocusDisplayEvent | None:
        template = UnifiedFocusResolver._find_template(msg, details)
        if template is None:
            template = FocusTemplate(
                content=AutoFocusGenerator.generate(msg, details),
                display=[DISPLAY_LOG],
            )
        if not template.content:
            return None

        return FocusDisplayEvent(
            content=UnifiedFocusResolver._substitute(template.content, details),
            display_channels=template.display,
            level=UnifiedFocusResolver._derive_level(msg),
            raw_msg=msg,
        )

    # ---- 内部方法 ------------------------------------------------------------

    @staticmethod
    def _find_template(msg: str, details: dict) -> FocusTemplate | None:
        """从 details.focus 中查找匹配的模板；无条目返回 None。"""
        focus = details.get("focus")
        if not isinstance(focus, dict) or msg not in focus:
            return None
        return FocusTemplate.from_raw(focus[msg])

    @staticmethod
    def _substitute(content: str, details: dict) -> str:
        """替换占位符：{name}, {task_id}, {entry}, {list}。"""
        if "{" not in content:
            return content

        content = content.replace("{name}", str(details.get("name", "")))
        content = content.replace("{task_id}", str(details.get("task_id", "")))
        content = content.replace("{entry}", str(details.get("entry", "")))
        content = content.replace("{list}", str(details.get("list", "")))
        return content

    @staticmethod
    def _derive_level(msg: str) -> RealtimeEventLevel:
        if msg.endswith(".Succeeded"):
            return "success"
        if msg.endswith(".Failed"):
            return "error"
        return "info"
