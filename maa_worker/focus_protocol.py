"""
Focus 协议实现 — 遵循 PI V2 v2.9.2 官方规范。

将 MAA 底层 sink 回调统一解析为 FocusDisplayEvent，
按 `display` 字段指定的渠道（log / toast / notification / dialog / modal）分发。
"""

from dataclasses import dataclass, field

from models.api import RealtimeEventLevel

# ---------------------------------------------------------------------------
# Supported display channels (PI V2 v2.9.2)
# ---------------------------------------------------------------------------

DISPLAY_LOG = "log"
DISPLAY_TOAST = "toast"
DISPLAY_NOTIFICATION = "notification"
DISPLAY_DIALOG = "dialog"
DISPLAY_MODAL = "modal"

_VALID_DISPLAYS = frozenset(
    {DISPLAY_LOG, DISPLAY_TOAST, DISPLAY_NOTIFICATION, DISPLAY_DIALOG, DISPLAY_MODAL}
)

# trace 默认授权的消息：仅 Node.PipelineNode.Failed
_TRACE_DEFAULT_TRUE_MSG = "Node.PipelineNode.Failed"

# ---------------------------------------------------------------------------
# FocusTemplate — 表示 interface.json 中一条 focus 模板
# ---------------------------------------------------------------------------


@dataclass
class FocusTemplate:
    """Focus 模板（v2.9.2 对象格式）。

    简写纯字符串在 from_raw() 中自动升级：
        "text" → FocusTemplate(content="text", display=["log"])
    """

    content: str
    display: list[str] = field(default_factory=lambda: [DISPLAY_LOG])
    trace: bool | None = None

    # ---- 工厂方法 ------------------------------------------------------------

    @staticmethod
    def from_raw(raw: object) -> "FocusTemplate":
        """从 interface.json 的 focus 值构造模板。

        支持：
        - str : 简写，等价 display=["log"]
        - dict: 完整对象 { "content": "...", "display": [...], "trace": bool }
        """
        if isinstance(raw, str):
            return FocusTemplate(content=raw, display=[DISPLAY_LOG])

        if isinstance(raw, dict):
            content = raw.get("content", "")
            if not isinstance(content, str):
                content = str(content)

            raw_display = raw.get("display", DISPLAY_LOG)
            if isinstance(raw_display, str):
                display = (
                    [raw_display] if raw_display in _VALID_DISPLAYS else [DISPLAY_LOG]
                )
            elif isinstance(raw_display, (list, tuple)):
                display = [
                    d
                    for d in raw_display
                    if isinstance(d, str) and d in _VALID_DISPLAYS
                ]
                if not display:
                    display = [DISPLAY_LOG]
            else:
                display = [DISPLAY_LOG]

            raw_trace = raw.get("trace")
            trace = raw_trace if isinstance(raw_trace, bool) else None

            return FocusTemplate(content=content, display=display, trace=trace)

        # 兜底：无法识别的类型
        return FocusTemplate(content=str(raw), display=[DISPLAY_LOG])


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

    对应官方协议 Client 处理流程：
    「根据 display 指定的渠道将文本展示给用户」。
    """

    content: str
    display_channels: list[str]
    level: RealtimeEventLevel = "info"
    raw_msg: str = ""
    trace_allowed: bool = False

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

    @property
    def has_displayable_content(self) -> bool:
        """存在可展示内容：非空文本（trace-only 模板不产生空 UI）。"""
        return bool(self.content and self.content.strip())


# ---------------------------------------------------------------------------
# UnifiedFocusResolver — 统一解析入口
# ---------------------------------------------------------------------------


class UnifiedFocusResolver:
    """将 MAA 原始 (msg, details) 统一解析为 FocusDisplayEvent。

    遵循 PI V2 v2.9.2 Client 处理流程：
    1. 从 details.focus[msg] 查找模板（精确消息键，无 name/状态后缀回退）
    2. 简写字符串自动升级为 {content, display:["log"]}
    3. 无匹配时使用 AutoFocusGenerator（普通自动日志保留）
    4. 占位符替换 {name}/{task_id}/{entry}/{list}（未知占位符保留）
    5. 推导 level
    6. trace 判定：显式 bool 优先，否则仅 Node.PipelineNode.Failed 默认 true
    7. 返回 FocusDisplayEvent
    """

    @staticmethod
    def resolve(msg: str, details: dict) -> FocusDisplayEvent:
        template = UnifiedFocusResolver._find_template(msg, details)
        content = UnifiedFocusResolver._substitute(template.content, details)
        level = UnifiedFocusResolver._derive_level(msg)
        channels = _sanitize_display(template.display)
        trace_allowed = UnifiedFocusResolver._resolve_trace(msg, template)

        return FocusDisplayEvent(
            content=content,
            display_channels=channels,
            level=level,
            raw_msg=msg,
            trace_allowed=trace_allowed,
        )

    # ---- 内部方法 ------------------------------------------------------------

    @staticmethod
    def _find_template(msg: str, details: dict) -> FocusTemplate:
        """从 details.focus 中按精确消息键查找模板。

        严格新格式：不再回退 name/状态后缀旧 PI 键。
        """
        focus = details.get("focus")
        if isinstance(focus, dict):
            raw = focus.get(msg)
            if raw is not None:
                return FocusTemplate.from_raw(raw)

        # 无 focus 定义 → 自动生成默认模板
        return FocusTemplate(
            content=AutoFocusGenerator.generate(msg, details),
            display=[DISPLAY_LOG],
        )

    @staticmethod
    def _resolve_trace(msg: str, template: FocusTemplate) -> bool:
        """trace 授权：显式 bool 优先；否则仅 Node.PipelineNode.Failed 默认 true。"""
        if isinstance(template.trace, bool):
            return template.trace
        return msg == _TRACE_DEFAULT_TRUE_MSG

    @staticmethod
    def _substitute(content: str, details: dict) -> str:
        """替换占位符：{name}, {task_id}, {entry}, {list}。

        未知占位符保留原文以便诊断，不执行表达式。
        """
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


def _sanitize_display(raw: list[str]) -> list[str]:
    """过滤只保留支持的 display 通道，确保至少有一个。"""
    valid = [d for d in raw if d in _VALID_DISPLAYS]
    return valid if valid else [DISPLAY_LOG]
