from __future__ import annotations


def _letter_codes(values: list[int]) -> dict[str, int]:
    return {chr(ord("A") + index): value for index, value in enumerate(values)}


def _function_key_codes(values: list[int]) -> dict[str, int]:
    return {f"F{index + 1}": value for index, value in enumerate(values)}


HOTKEY_KEY_MAP: dict[str, dict[str, int]] = {
    "Win32": {
        "BACKSPACE": 0x08,
        "TAB": 0x09,
        "ENTER": 0x0D,
        "SHIFT": 0x10,
        "CTRL": 0x11,
        "ALT": 0x12,
        "ESC": 0x1B,
        "SPACE": 0x20,
        "PAGEUP": 0x21,
        "PAGEDOWN": 0x22,
        "END": 0x23,
        "HOME": 0x24,
        "LEFT": 0x25,
        "UP": 0x26,
        "RIGHT": 0x27,
        "DOWN": 0x28,
        "DELETE": 0x2E,
        **{str(value): 0x30 + value for value in range(10)},
        **_letter_codes(list(range(0x41, 0x5B))),
        **_function_key_codes(list(range(0x70, 0x7C))),
    },
    "Adb": {
        "BACKSPACE": 67,
        "TAB": 61,
        "ENTER": 66,
        "SHIFT": 59,
        "CTRL": 113,
        "ALT": 57,
        "SPACE": 62,
        "ESC": 111,
        "DELETE": 112,
        "HOME": 3,
        "END": 123,
        "PAGEUP": 92,
        "PAGEDOWN": 93,
        "LEFT": 21,
        "RIGHT": 22,
        "UP": 19,
        "DOWN": 20,
        **{str(value): 7 + value for value in range(10)},
        **_letter_codes(list(range(29, 55))),
        **_function_key_codes(list(range(131, 143))),
    },
    # Linux evdev 键码（原 WlRoots 表）
    "Linux": {
        "BACKSPACE": 14,
        "TAB": 15,
        "ENTER": 28,
        "SHIFT": 42,
        "CTRL": 29,
        "ALT": 56,
        "SPACE": 57,
        "ESC": 1,
        "DELETE": 111,
        "HOME": 102,
        "END": 107,
        "PAGEUP": 104,
        "PAGEDOWN": 109,
        "LEFT": 105,
        "RIGHT": 106,
        "UP": 103,
        "DOWN": 108,
        **dict(zip("0123456789", [11, 2, 3, 4, 5, 6, 7, 8, 9, 10], strict=True)),
        **_letter_codes(
            [
                30,
                48,
                46,
                32,
                18,
                33,
                34,
                35,
                23,
                36,
                37,
                38,
                50,
                49,
                24,
                25,
                16,
                19,
                31,
                20,
                22,
                47,
                17,
                45,
                21,
                44,
            ]
        ),
        **_function_key_codes([*range(59, 69), 87, 88]),
    },
    # Apple HIToolbox CGKeyCode（MacOSX10.15.sdk Events.h）。
    # 注意：kVK_ANSI_* 表示物理键位，不是字符 Unicode 值；MacOS A=0 是有效键码。
    "MacOS": {
        "BACKSPACE": 51,  # kVK_Delete（Mac 上即退格）
        "TAB": 48,
        "ENTER": 36,  # kVK_Return
        "SHIFT": 56,  # kVK_Shift
        "CTRL": 59,  # kVK_Control
        "ALT": 58,  # kVK_Option
        "CMD": 55,  # kVK_Command
        "COMMAND": 55,
        "META": 55,
        "ESC": 53,  # kVK_Escape
        "SPACE": 49,
        "PAGEUP": 116,
        "PAGEDOWN": 121,
        "END": 115,  # kVK_End... 见下：HOME=115/END=119
        "HOME": 115,
        "LEFT": 123,
        "UP": 126,
        "RIGHT": 124,
        "DOWN": 125,
        "DELETE": 117,  # kVK_ForwardDelete
        "0": 29,
        "1": 18,
        "2": 19,
        "3": 20,
        "4": 21,
        "5": 23,
        "6": 22,
        "7": 26,
        "8": 28,
        "9": 25,
        # kVK_ANSI_A(0x00) 起：A S D F H G Z X C V B Q W E R Y T
        **_letter_codes(
            [
                0,
                1,
                2,
                3,
                4,
                5,
                6,
                7,
                8,
                9,
                11,
                12,
                13,
                14,
                15,
                16,
                17,
                # O U [ ] I P L J K
                31,
                32,
                33,
                30,
                34,
                35,
                37,
                38,
                40,
                # N M , . /
                45,
                46,
                43,
                47,
                44,
            ]
        ),
        **_function_key_codes([122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111]),
    },
}

# 修正：kVK_Home=115、kVK_End=119（上面初始化后修正，保持表格一处可读）
HOTKEY_KEY_MAP["MacOS"]["HOME"] = 115
HOTKEY_KEY_MAP["MacOS"]["END"] = 119

# 不受支持的 Meta 家族修饰键（Win32/Linux/Adb 无法表示；MacOS 表中已提供 CMD）
_UNSUPPORTED_HOTKEY_KEYS = {"META", "SUPER", "WIN", "CMD", "COMMAND"}

# MacOS 允许 Command 修饰；其余控制器不允许 Meta 家族
_MACOS = "MacOS"


def split_hotkey_combo(value: str) -> tuple[str, list[str]]:
    parts = [part.strip().upper() for part in value.split("+") if part.strip()]
    if not parts:
        return "", []
    return parts[-1], parts[:-1]


def hotkey_value_to_codes(
    value: str,
    controller_type: str | None,
    *,
    use_win32_vk_code: bool = False,
) -> tuple[int, int, int]:
    """将快捷键字符串转换为 (primary, modifier1, modifier2) 键码三元组。

    - 未知 controller_type 不再默认 Win32，抛出错误；
    - Linux `use_win32_vk_code=True` 使用 Win32 VK 表，否则 evdev 表；
    - MacOS 使用 Apple HIToolbox CGKeyCode（A=0 是有效值）；
    - 未知主键/修饰键、空主键抛出可定位的配置错误，不返回 0 兜底。
    """
    if controller_type not in HOTKEY_KEY_MAP:
        raise ValueError(
            f"快捷键需要受支持的控制器类型，得到: {controller_type!r}"
            f"（支持: {', '.join(HOTKEY_KEY_MAP)}）"
        )
    effective_type = controller_type
    if controller_type == "Linux" and use_win32_vk_code:
        effective_type = "Win32"
    key_map = HOTKEY_KEY_MAP[effective_type]

    primary, modifiers = split_hotkey_combo(value or "")
    if not primary:
        raise ValueError("快捷键主键为空")

    if effective_type != _MACOS and (
        primary in _UNSUPPORTED_HOTKEY_KEYS
        or any(modifier in _UNSUPPORTED_HOTKEY_KEYS for modifier in modifiers)
    ):
        raise ValueError("快捷键不支持 Meta/Command/Win 键")
    if len(modifiers) > 2:
        raise ValueError("快捷键最多支持两个修饰键")

    primary_code = key_map.get(primary)
    if primary_code is None:
        raise ValueError(f"快捷键主键 {primary} 不在 {effective_type} 键码表中")
    modifier_codes: list[int] = []
    for modifier in modifiers:
        modifier_code = key_map.get(modifier)
        if modifier_code is None:
            raise ValueError(f"快捷键修饰键 {modifier} 不在 {effective_type} 键码表中")
        modifier_codes.append(modifier_code)
    modifier_codes.extend([0] * (2 - len(modifier_codes)))
    return (
        primary_code,
        modifier_codes[0],
        modifier_codes[1],
    )
