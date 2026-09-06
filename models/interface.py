import math
import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

DocumentContent = str | list[str]
PipelineOverride = dict[str, Any]
PresetOptionValue = str | list[str] | dict[str, str]
_UNSUPPORTED_HOTKEY_KEYS = {"META", "SUPER", "WIN", "CMD", "COMMAND"}


def validate_regex(v: Any, info: ValidationInfo) -> Any:
    if v is None or isinstance(v, re.Pattern):
        return v
    try:
        return re.compile(v)
    except (re.error, TypeError):
        raise ValueError(f"{info.field_name} 无法编译为正则表达式")


def _pipeline_override_contains_attach_option(value: Any, option_name: str) -> bool:
    if isinstance(value, dict):
        attach_value = value.get("attach")
        if isinstance(attach_value, dict) and option_name in attach_value:
            return True
        for nested_value in value.values():
            if _pipeline_override_contains_attach_option(nested_value, option_name):
                return True
        return False
    if isinstance(value, list):
        return any(
            _pipeline_override_contains_attach_option(item, option_name)
            for item in value
        )
    return False


class AdbController(BaseModel):
    """Adb 控制器配置，V2 协议中 input/screencap 由 MaaFramework 自动检测"""

    model_config = ConfigDict(extra="allow")


class Win32Controller(BaseModel):
    class_regex: re.Pattern | None = None
    window_regex: re.Pattern | None = None
    mouse: (
        Literal[
            "Seize",
            "SendMessage",
            "PostMessage",
            "LegacyEvent",
            "SendMessageWithCursorPos",
            "PostMessageWithCursorPos",
            "SendMessageWithWindowPos",
            "PostMessageWithWindowPos",
        ]
        | None
    ) = None
    keyboard: (
        Literal[
            "Seize",
            "SendMessage",
            "PostMessage",
            "LegacyEvent",
            "SendMessageWithCursorPos",
            "PostMessageWithCursorPos",
            "SendMessageWithWindowPos",
            "PostMessageWithWindowPos",
        ]
        | None
    ) = None
    screencap: (
        Literal[
            "GDI",
            "FramePool",
            "DXGI_DesktopDup",
            "DXGI_DesktopDup_Window",
            "PrintWindow",
            "ScreenDC",
            "Foreground",
            "Background",
        ]
        | None
    ) = None

    @field_validator("class_regex", "window_regex", mode="before")
    @classmethod
    def check_regex(cls, v: Any, info: ValidationInfo):
        return validate_regex(v, info)

    @model_validator(mode="after")
    def method_to_int(self):
        maps = {
            "screencap": {
                "GDI": 1,
                "FramePool": 2,
                "DXGI_DesktopDup": 4,
                "DXGI_DesktopDup_Window": 8,
                "PrintWindow": 16,
                "ScreenDC": 32,
                "Foreground": 64,
                "Background": 128,
            },
            "keyboard": {
                "Seize": 1,
                "SendMessage": 2,
                "PostMessage": 4,
                "LegacyEvent": 8,
                "SendMessageWithCursorPos": 32,
                "PostMessageWithCursorPos": 64,
                "SendMessageWithWindowPos": 128,
                "PostMessageWithWindowPos": 256,
            },
            "mouse": {
                "Seize": 1,
                "SendMessage": 2,
                "PostMessage": 4,
                "LegacyEvent": 8,
                "SendMessageWithCursorPos": 32,
                "PostMessageWithCursorPos": 64,
                "SendMessageWithWindowPos": 128,
                "PostMessageWithWindowPos": 256,
            },
        }
        # 将输入的字符串方法转换为对应的整数值
        for field, mapping in maps.items():
            value = getattr(self, field, None)
            if isinstance(value, str):
                if value in mapping:
                    setattr(self, field, mapping[value])
                else:
                    raise ValueError(f"无效的 {field} 方法: {value}")
        return self


class PlayCoverController(BaseModel):
    """PlayCover 控制器配置（仅 macOS）"""

    uuid: str | None = None


class MacOSController(BaseModel):
    """MacOS 控制器配置"""

    title_regex: re.Pattern | None = None
    input: Literal["GlobalEvent", "PostToPid"] | None = None
    screencap: Literal["ScreenCaptureKit"] | None = "ScreenCaptureKit"

    @field_validator("title_regex", mode="before")
    @classmethod
    def check_regex(cls, v: Any, info: ValidationInfo):
        return validate_regex(v, info)


class LinuxControllerConfig(BaseModel):
    """Linux 控制器配置（仅 Linux）

    截图与输入方式枚举与 MaaFramework beta6 LinuxControlUnitMgr 一致：
    Wlr=1 / UInput=2 / Libei=4 / PipeWire=4。ExtImage 虽在 SDK 枚举中保留，
    但控制方式文档未列出且 LinuxControlUnitMgr 未实现，不向用户提供。
    """

    use_win32_vk_code: bool | None = False
    pipewire_source: Literal["Gamescope", "Portal"] | None = "Gamescope"
    screencap: Literal["Wlr", "PipeWire"] | None = "Wlr"
    input: Literal["Wlr", "UInput", "Libei"] | None = "Wlr"


class GamepadController(BaseModel):
    """虚拟游戏手柄控制器配置（仅 Windows）"""

    class_regex: re.Pattern | None = None
    window_regex: re.Pattern | None = None
    gamepad_type: Literal["Xbox360", "DualShock4", "DS4"] | None = "Xbox360"
    screencap: (
        Literal[
            "GDI",
            "FramePool",
            "DXGI_DesktopDup",
            "DXGI_DesktopDup_Window",
            "PrintWindow",
            "ScreenDC",
        ]
        | None
    ) = None

    @field_validator("class_regex", "window_regex", mode="before")
    @classmethod
    def check_regex(cls, v: Any, info: ValidationInfo):
        return validate_regex(v, info)

    @model_validator(mode="after")
    def method_to_int(self):
        maps = {
            "screencap": {
                "GDI": 1,
                "FramePool": 2,
                "DXGI_DesktopDup": 4,
                "DXGI_DesktopDup_Window": 8,
                "PrintWindow": 16,
                "ScreenDC": 32,
            },
            "gamepad_type": {"Xbox360": 0, "DualShock4": 1, "DS4": 1},
        }
        # 将输入的字符串方法转换为对应的整数值
        for field, mapping in maps.items():
            value = getattr(self, field, None)
            if isinstance(value, str):
                if value in mapping:
                    setattr(self, field, mapping[value])
                else:
                    raise ValueError(f"无效的 {field} 方法: {value}")
        return self


class Controller(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    type: Literal["Adb", "Win32", "MacOS", "PlayCover", "Linux", "Gamepad"]
    display_short_side: int | None = 720
    display_long_side: int | None = None
    display_raw: bool | None = False
    permission_required: bool | None = False
    attach_resource_path: list[str] | None = None
    option: list[str] | None = None
    adb: AdbController | None = None
    win32: Win32Controller | None = None
    macos: MacOSController | None = None
    playcover: PlayCoverController | None = None
    linux: LinuxControllerConfig | None = None
    gamepad: GamepadController | None = None

    @model_validator(mode="after")
    def check_display_fields_mutual_exclusive(self):
        # 互斥判定按“是否显式提供”进行：显式给出 short_side=720 也算提供；
        # 仅当三个字段都未显式给出时才使用默认 short=720。
        explicitly_set = self.model_fields_set
        fields_set = [
            name
            for name in ("display_short_side", "display_long_side", "display_raw")
            if name in explicitly_set
        ]
        if len(fields_set) > 1:
            raise ValueError(
                "display_short_side, display_long_side 和 display_raw 必须互斥"
            )
        return self


class Resource(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    path: list[str]
    controller: list[str] | None = None
    option: list[str] | None = None
    hash: str | None = None


class Agent(BaseModel):
    child_exec: str
    child_args: list[str] | None = None
    identifier: str | None = None
    embedded: bool | None = True


class Task(BaseModel):
    name: str
    label: str | None = None
    entry: str
    default_check: bool | None = False
    description: str | None = None
    doc: DocumentContent | None = None
    desc: DocumentContent | None = None
    icon: str | None = None
    group: list[str] | None = None
    resource: list[str] | None = None
    controller: list[str] | None = None
    pipeline_override: PipelineOverride | None = None
    option: list[str] | None = None


class Pretask(BaseModel):
    resource: list[str] | None = None
    controller: list[str] | None = None
    exec: str
    args: list[str] | None = None
    name: str | None = None
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    option: list[str] | None = None


class Group(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    default_expand: bool | None = True


class SettingSection(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    option: list[str] | None = None
    default_expand: bool | None = True


class OptionCase(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    option: list[str] | None = None
    pipeline_override: PipelineOverride | None = None


class InputCase(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    default: str | None = None
    pipeline_type: Literal["string", "int", "bool"] | None = None
    verify: str | None = None
    pattern_msg: str | None = None


class HotkeyCase(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    default: str | None = None

    @field_validator("default")
    @classmethod
    def check_modifier_count(cls, value: str | None):
        parts = [part.strip() for part in (value or "").split("+") if part.strip()]
        if len(parts) > 3:
            raise ValueError("快捷键最多支持两个修饰键")
        if any(part.upper() in _UNSUPPORTED_HOTKEY_KEYS for part in parts):
            raise ValueError("快捷键不支持 Meta/Command/Win 键")
        return value


class Option(BaseModel):
    type: Literal["select", "input", "checkbox", "switch", "scan_select", "hotkey"] = (
        "select"
    )
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    controller: list[str] | None = None
    resource: list[str] | None = None
    cases: list[OptionCase] | None = None
    inputs: list[InputCase] | None = None
    hotkeys: list[HotkeyCase] | None = None
    scan_dir: str | None = None
    scan_filter: str | None = None
    pipeline_override: PipelineOverride | None = None
    default_case: str | list[str] | None = None

    @model_validator(mode="after")
    def check_type_fields(self):
        if self.type == "select" and not self.cases:
            raise ValueError("当 type 为 select 时，cases 不能为空")
        if self.type == "switch":
            if not self.cases:
                raise ValueError("当 type 为 switch 时，cases 不能为空")
            if len(self.cases) != 2:
                raise ValueError("当 type 为 switch 时，cases 必须有且仅有 2 个元素")
        if self.type == "checkbox":
            if not self.cases:
                raise ValueError("当 type 为 checkbox 时，cases 不能为空")
            if self.default_case is not None and not isinstance(
                self.default_case, list
            ):
                raise ValueError(
                    "当 type 为 checkbox 时，default_case 必须为字符串数组"
                )
        if self.type == "input" and not self.inputs:
            raise ValueError("当 type 为 input 时，inputs 不能为空")
        if self.type == "hotkey" and not self.hotkeys:
            raise ValueError("当 type 为 hotkey 时，hotkeys 不能为空")
        if self.type == "scan_select":
            if not self.scan_dir:
                raise ValueError("当 type 为 scan_select 时，scan_dir 不能为空")
            if not self.scan_filter:
                raise ValueError("当 type 为 scan_select 时，scan_filter 不能为空")
            if not self.pipeline_override:
                raise ValueError(
                    "当 type 为 scan_select 时，pipeline_override 不能为空"
                )
        if (
            self.type in {"select", "switch", "scan_select"}
            and self.default_case is not None
            and not isinstance(self.default_case, str)
        ):
            raise ValueError(
                "当 type 为 select、switch 或 scan_select 时，default_case 必须为字符串"
            )
        return self


def is_option_applicable(
    option: "Option",
    controller_name: str | None,
    resource_name: str | None,
) -> bool:
    """option 是否适用于给定控制器/资源上下文。

    pipeline override 与 pretask 使用同一语义：
    受限而未选择对应上下文的 option 不激活。
    """
    if option.controller:
        if controller_name is None or controller_name not in option.controller:
            return False
    if option.resource:
        if resource_name is None or resource_name not in option.resource:
            return False
    return True


def is_option_applicable_any(
    option: "Option",
    controller_names: set[str],
    resource_name: str | None,
) -> bool:
    """多活跃控制器变体（pipeline override 使用）。"""
    if option.controller and not controller_names.intersection(option.controller):
        return False
    if option.resource and (
        resource_name is None or resource_name not in option.resource
    ):
        return False
    return True


class PresetTask(BaseModel):
    name: str
    enabled: bool | None = True
    option: dict[str, PresetOptionValue] | None = None


class Preset(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    task: list[PresetTask] | None = None


def _validate_sample_rate(value: Any, field_name: str) -> float:
    """有限数值采样率校验：NaN/无穷大/越界是 PI 配置错误，不截断。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} 必须是数值")
    as_float = float(value)
    if not math.isfinite(as_float):
        raise ValueError(f"{field_name} 必须是有限数值")
    if as_float < 0 or as_float > 1:
        raise ValueError(f"{field_name} 必须在 [0, 1] 范围内")
    return as_float


class SentryTelemetryConfig(BaseModel):
    """interface.json telemetry.sentry 配置（PI v2.9.2）"""

    model_config = ConfigDict(extra="ignore")

    dsn: str
    tracing: bool | None = True
    traces_sample_rate: float | None = 1.0
    failure_attachments_sample_rate: float | None = 1.0
    environment: str | None = None

    @field_validator("dsn")
    @classmethod
    def dsn_not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("telemetry.sentry.dsn 必须是非空字符串")
        return value

    @field_validator("traces_sample_rate")
    @classmethod
    def check_traces_sample_rate(cls, value):
        if value is None:
            return None
        return _validate_sample_rate(value, "traces_sample_rate")

    @field_validator("failure_attachments_sample_rate")
    @classmethod
    def check_failure_attachments_sample_rate(cls, value):
        if value is None:
            return None
        return _validate_sample_rate(value, "failure_attachments_sample_rate")


class TelemetryConfig(BaseModel):
    """interface.json telemetry 配置：缺失 sentry/dsn 即不启用。"""

    model_config = ConfigDict(extra="ignore")

    sentry: SentryTelemetryConfig | None = None


class InterfaceModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    interface_version: Literal[2]
    languages: dict[str, str] | None = None
    name: str
    label: str | None = None
    title: str | None = None
    icon: str | None = None
    mirrorchyan_rid: str | None = None
    mirrorchyan_multiplatform: bool | None = None
    github: str | None = None
    version: str | None = None
    contact: str | None = None
    license: str | None = None
    welcome: str | None = None
    description: str | None = None
    controller: list[Controller]
    resource: list[Resource]
    group: list[Group] | None = None
    agent: Agent | list[Agent] | None = None
    task: list[Task] | None = None
    pretask: Pretask | list[Pretask] | None = None
    option: dict[str, Option] | None = None
    global_option: list[str] | None = None
    setting: list[SettingSection] | None = None
    import_: list[str] | None = Field(None, alias="import")
    preset: list[Preset] | None = None
    telemetry: TelemetryConfig | None = None

    @model_validator(mode="after")
    def set_variable_if_none(self):
        if self.label is None:
            self.label = self.name
        if self.title is None:
            base = self.name if self.version is None else f"{self.name} {self.version}"
            self.title = base
        return self

    @model_validator(mode="after")
    def check_scan_select_pipeline_override_placeholder(self):
        if not self.option:
            return self

        for option_name, option in self.option.items():
            if option.type != "scan_select" or option.pipeline_override is None:
                continue

            if not _pipeline_override_contains_attach_option(
                option.pipeline_override,
                option_name,
            ):
                raise ValueError(
                    f"scan_select 选项 {option_name} 的 pipeline_override 必须在任意层级的 attach 中至少包含一次键 {option_name}"
                )
        return self
