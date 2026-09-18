export type HotkeyCaptureIssue = "too_many_modifiers" | "unsupported_key"

const MAX_MODIFIERS = 2
const MAX_FUNCTION_KEY = 12
const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

const modifierCodes: Record<string, true> = {
  ControlLeft: true,
  ControlRight: true,
  ShiftLeft: true,
  ShiftRight: true,
  AltLeft: true,
  AltRight: true,
  MetaLeft: true,
  MetaRight: true,
}

// KeyboardEvent.code → 后端 maa_worker/hotkey.py 的 HOTKEY_KEY_MAP 键名。
// 主键一律由 code 派生，因此不受键盘布局与 Shift 影响（Shift+1 记为 Shift+1，而非 Shift+!）。
const keyNamesByCode: Record<string, string> = {
  Semicolon: "SEMICOLON",
  Equal: "EQUAL",
  Comma: "COMMA",
  Minus: "MINUS",
  Period: "PERIOD",
  Slash: "SLASH",
  Backquote: "GRAVE",
  BracketLeft: "LEFTBRACKET",
  Backslash: "BACKSLASH",
  BracketRight: "RIGHTBRACKET",
  Quote: "APOSTROPHE",
  Space: "SPACE",
  Enter: "ENTER",
  Tab: "TAB",
  Backspace: "BACKSPACE",
  Escape: "ESC",
  Delete: "DELETE",
  Home: "HOME",
  End: "END",
  PageUp: "PAGEUP",
  PageDown: "PAGEDOWN",
  ArrowLeft: "LEFT",
  ArrowRight: "RIGHT",
  ArrowUp: "UP",
  ArrowDown: "DOWN",
  NumpadMultiply: "NUMPADMULTIPLY",
  NumpadAdd: "NUMPADADD",
  NumpadSubtract: "NUMPADSUBTRACT",
  NumpadDecimal: "NUMPADDECIMAL",
  NumpadDivide: "NUMPADDIVIDE",
  NumpadEnter: "NUMPADENTER",
}

for (const letter of LETTERS) {
  keyNamesByCode[`Key${letter}`] = letter
}

for (let digit = 0; digit < 10; digit += 1) {
  keyNamesByCode[`Digit${digit}`] = String(digit)
  keyNamesByCode[`Numpad${digit}`] = `NUMPAD${digit}`
}

for (let index = 1; index <= MAX_FUNCTION_KEY; index += 1) {
  keyNamesByCode[`F${index}`] = `F${index}`
}

export function getHotkeyCaptureIssue(event: KeyboardEvent): HotkeyCaptureIssue | null {
  const modifierCount =
    Number(event.ctrlKey) + Number(event.altKey) + Number(event.shiftKey) + Number(event.metaKey)
  if (modifierCount > MAX_MODIFIERS) return "too_many_modifiers"
  if (modifierCodes[event.code]) return null
  return keyNamesByCode[event.code] === undefined ? "unsupported_key" : null
}

export function buildHotkeyCombo(event: KeyboardEvent): string | null {
  if (getHotkeyCaptureIssue(event)) return null
  if (modifierCodes[event.code]) return null

  const primary = keyNamesByCode[event.code]
  if (primary === undefined) return null

  const parts: string[] = []
  if (event.ctrlKey) parts.push("Ctrl")
  if (event.altKey) parts.push("Alt")
  if (event.shiftKey) parts.push("Shift")
  if (event.metaKey) parts.push("Meta")
  if (parts.length > MAX_MODIFIERS) return null
  parts.push(primary)
  return parts.join("+")
}
