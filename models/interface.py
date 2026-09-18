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
    screencap: Literal["ScreenCaptureKit"] | None = None

    @field_validator("title_regex", mode="before")
    @classmethod
    def check_regex(cls, v: Any, info: ValidationInfo):
        return validate_regex(v, info)


class LinuxController(BaseModel):
    """Linux 控制器配置（仅 Linux）"""

    input: Literal["Wlr", "Libei"] | None = None
    screencap: Literal["Wlr", "PipeWire"] | None = None
    pipewire_source: Literal["Gamescope", "Portal"] | None = "Gamescope"
    use_win32_vk_code: bool | None = False

    @model_validator(mode="after")
    def check_supported_combination(self):
        input_method = self.input or "Wlr"
        screencap = self.screencap or "Wlr"
        pipewire_source = self.pipewire_source or "Gamescope"
        if input_method == "Libei" and (
            screencap != "PipeWire" or pipewire_source != "Gamescope"
        ):
            raise ValueError(
                "input=Libei 需要 screencap=PipeWire 且 pipewire_source=Gamescope"
            )
        return self


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
    linux: LinuxController | None = None
    gamepad: GamepadController | None = None

    @model_validator(mode="after")
    def check_display_fields_mutual_exclusive(self):
        # 检查是否设置了多个互斥字段（非默认值）
        fields_set = []
        if self.display_short_side is not None and self.display_short_side != 720:
            fields_set.append("display_short_side")
        if self.display_long_side is not None:
            fields_set.append("display_long_side")
        if self.display_raw is True:
            fields_set.append("display_raw")
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

    @model_validator(mode="after")
    def set_variable_if_none(self):
        if self.label is None:
            self.label = self.name
        if self.title is None and self.label and self.version:
            self.title = f"{self.label} {self.version}"
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
