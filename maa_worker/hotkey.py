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
}


def split_hotkey_combo(value: str) -> tuple[str, list[str]]:
    parts = [part.strip() for part in value.split("+") if part.strip()]
    if not parts:
        return "", []
    return parts[-1], parts[:-1]


def hotkey_value_to_codes(
    value: str, controller_type: str | None
) -> tuple[int, int, int]:
    primary, modifiers = split_hotkey_combo(value)
    unsupported_keys = {"META", "SUPER", "WIN", "CMD", "COMMAND"}
    if primary.upper() in unsupported_keys or any(
        modifier.upper() in unsupported_keys for modifier in modifiers
    ):
        raise ValueError("快捷键不支持 Meta/Command/Win 键")
    if len(modifiers) > 2:
        raise ValueError("快捷键最多支持两个修饰键")
    key_map = HOTKEY_KEY_MAP.get(controller_type or "", HOTKEY_KEY_MAP["Win32"])
    modifier_codes = [key_map.get(modifier.upper(), 0) for modifier in modifiers]
    modifier_codes.extend([0] * (2 - len(modifier_codes)))
    return (
        key_map.get(primary.upper(), 0),
        modifier_codes[0],
        modifier_codes[1],
    )
