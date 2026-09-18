from __future__ import annotations

_DEFAULT_CONTROLLER_TYPE = "Win32"
_GAMEPAD_CONTROLLER_TYPE = "Gamepad"
_PLAYCOVER_CONTROLLER_TYPE = "PlayCover"
_MAX_MODIFIERS = 2


def _letter_codes(values: list[int]) -> dict[str, int]:
    return {chr(ord("A") + index): value for index, value in enumerate(values)}


def _function_key_codes(values: list[int]) -> dict[str, int]:
    return {f"F{index + 1}": value for index, value in enumerate(values)}


def _symbol_codes(values: list[int]) -> dict[str, int]:
    """符号键名称与前端 utils/hotkey.ts 由 KeyboardEvent.code 派生的名称保持一致。"""
    names = (
        "SEMICOLON",
        "EQUAL",
        "COMMA",
        "MINUS",
        "PERIOD",
        "SLASH",
        "GRAVE",
        "LEFTBRACKET",
        "BACKSLASH",
        "RIGHTBRACKET",
        "APOSTROPHE",
    )
    return dict(zip(names, values, strict=True))


def _numpad_codes(
    digits: list[int],
    *,
    multiply: int,
    add: int,
    subtract: int,
    decimal: int,
    divide: int,
    enter: int,
) -> dict[str, int]:
    return {
        **{f"NUMPAD{digit}": code for digit, code in enumerate(digits)},
        "NUMPADMULTIPLY": multiply,
        "NUMPADADD": add,
        "NUMPADSUBTRACT": subtract,
        "NUMPADDECIMAL": decimal,
        "NUMPADDIVIDE": divide,
        "NUMPADENTER": enter,
    }


# 键码来源：
#   Win32   https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
#   Adb     android.view.KeyEvent
#   Linux   include/uapi/linux/input-event-codes.h
#   MacOS   HIToolbox/Events.h（CGKeyCode，由 CGEventCreateKeyboardEvent 消费）
#   Gamepad include/MaaFramework/MaaDef.h 的 MaaGamepadButton_*
HOTKEY_KEY_MAP: dict[str, dict[str, int]] = {
    "Win32": {
        "BACKSPACE": 0x08,
        "TAB": 0x09,
        "ENTER": 0x0D,
        "SHIFT": 0x10,
        "CTRL": 0x11,
        "ALT": 0x12,
        "META": 0x5B,
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
        **_symbol_codes(
            [0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE]
        ),
        **_numpad_codes(
            list(range(0x60, 0x6A)),
            multiply=0x6A,
            add=0x6B,
            subtract=0x6D,
            decimal=0x6E,
            divide=0x6F,
            enter=0x0D,
        ),
    },
    "Adb": {
        "BACKSPACE": 67,
        "TAB": 61,
        "ENTER": 66,
        "SHIFT": 59,
        "CTRL": 113,
        "ALT": 57,
        "META": 117,
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
        **_symbol_codes([74, 70, 55, 69, 56, 76, 68, 71, 73, 72, 75]),
        **_numpad_codes(
            list(range(144, 154)),
            multiply=155,
            add=157,
            subtract=156,
            decimal=158,
            divide=154,
            enter=160,
        ),
    },
    "Linux": {
        "BACKSPACE": 14,
        "TAB": 15,
        "ENTER": 28,
        "SHIFT": 42,
        "CTRL": 29,
        "ALT": 56,
        "META": 125,
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
        **_symbol_codes([39, 13, 51, 12, 52, 53, 41, 26, 43, 27, 40]),
        **_numpad_codes(
            [82, 79, 80, 81, 75, 76, 77, 71, 72, 73],
            multiply=55,
            add=78,
            subtract=74,
            decimal=83,
            divide=98,
            enter=96,
        ),
    },
    "MacOS": {
        "BACKSPACE": 0x33,
        "TAB": 0x30,
        "ENTER": 0x24,
        "SHIFT": 0x38,
        "CTRL": 0x3B,
        "ALT": 0x3A,
        "META": 0x37,
        "ESC": 0x35,
        "SPACE": 0x31,
        "PAGEUP": 0x74,
        "PAGEDOWN": 0x79,
        "END": 0x77,
        "HOME": 0x73,
        "LEFT": 0x7B,
        "UP": 0x7E,
        "RIGHT": 0x7C,
        "DOWN": 0x7D,
        "DELETE": 0x75,
        **dict(
            zip(
                "0123456789",
                [0x1D, 0x12, 0x13, 0x14, 0x15, 0x17, 0x16, 0x1A, 0x1C, 0x19],
                strict=True,
            )
        ),
        **_letter_codes(
            [
                0x00,
                0x0B,
                0x08,
                0x02,
                0x0E,
                0x03,
                0x05,
                0x04,
                0x22,
                0x26,
                0x28,
                0x25,
                0x2E,
                0x2D,
                0x1F,
                0x23,
                0x0C,
                0x0F,
                0x01,
                0x11,
                0x20,
                0x09,
                0x0D,
                0x07,
                0x10,
                0x06,
            ]
        ),
        "F1": 0x7A,
        "F2": 0x78,
        "F3": 0x63,
        "F4": 0x76,
        "F5": 0x60,
        "F6": 0x61,
        "F7": 0x62,
        "F8": 0x64,
        "F9": 0x65,
        "F10": 0x6D,
        "F11": 0x67,
        "F12": 0x6F,
        **_symbol_codes(
            [0x29, 0x18, 0x2B, 0x1B, 0x2F, 0x2C, 0x32, 0x21, 0x2A, 0x1E, 0x27]
        ),
        **_numpad_codes(
            [0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5B, 0x5C],
            multiply=0x43,
            add=0x45,
            subtract=0x4E,
            decimal=0x41,
            divide=0x4B,
            enter=0x4C,
        ),
    },
    # Gamepad 没有键盘语义，键码为 MaaGamepadButton_*，且不存在修饰键概念。
    "Gamepad": {
        "A": 0x1000,
        "B": 0x2000,
        "X": 0x4000,
        "Y": 0x8000,
        "UP": 0x0001,
        "DOWN": 0x0002,
        "LEFT": 0x0004,
        "RIGHT": 0x0008,
        "ENTER": 0x0010,
        "START": 0x0010,
        "ESC": 0x0020,
        "BACK": 0x0020,
        "LB": 0x0100,
        "RB": 0x0200,
        "GUIDE": 0x0400,
        "PS": 0x10000,
        "TOUCHPAD": 0x20000,
    },
}


def split_hotkey_combo(value: str) -> tuple[str, list[str]]:
    parts = [part.strip() for part in value.split("+") if part.strip()]
    if not parts:
        return "", []
    return parts[-1], parts[:-1]


_META_ALIASES = {"CMD", "COMMAND", "WIN", "SUPER"}


def _key_map_for_controller(controller_type: str | None) -> dict[str, int]:
    if controller_type == _PLAYCOVER_CONTROLLER_TYPE:
        raise ValueError("PlayCover 控制器不支持按键操作")
    return HOTKEY_KEY_MAP.get(
        controller_type or "", HOTKEY_KEY_MAP[_DEFAULT_CONTROLLER_TYPE]
    )


def _lookup_key(key_map: dict[str, int], name: str) -> int:
    key_name = name.upper()
    if key_name in _META_ALIASES:
        key_name = "META"
    code = key_map.get(key_name)
    if code is None:
        raise ValueError(f"未知快捷键: {name}")
    return code


def hotkey_value_to_codes(
    value: str, controller_type: str | None
) -> tuple[int, int, int]:
    primary, modifiers = split_hotkey_combo(value)
    if not primary:
        return (0, 0, 0)

    key_map = _key_map_for_controller(controller_type)

    if controller_type == _GAMEPAD_CONTROLLER_TYPE:
        if modifiers:
            raise ValueError("Gamepad 控制器不支持组合键")
        return (_lookup_key(key_map, primary), 0, 0)

    if len(modifiers) > _MAX_MODIFIERS:
        raise ValueError("快捷键最多支持两个修饰键")

    modifier_codes = [_lookup_key(key_map, modifier) for modifier in modifiers]
    modifier_codes.extend([0] * (_MAX_MODIFIERS - len(modifier_codes)))
    return (_lookup_key(key_map, primary), modifier_codes[0], modifier_codes[1])
