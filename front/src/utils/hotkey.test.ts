import { describe, expect, it } from "vitest"

import { buildHotkeyCombo, getHotkeyCaptureIssue } from "@/utils/hotkey"

function keydownEvent(init: KeyboardEventInit): KeyboardEvent {
  return new KeyboardEvent("keydown", init)
}

describe("buildHotkeyCombo", () => {
  it("orders two modifiers consistently", () => {
    const event = keydownEvent({ code: "KeyA", key: "a", ctrlKey: true, altKey: true })

    expect(buildHotkeyCombo(event)).toBe("Ctrl+Alt+A")
  })

  it("keeps Meta as a supported modifier", () => {
    const event = keydownEvent({ code: "KeyA", key: "a", metaKey: true })

    expect(getHotkeyCaptureIssue(event)).toBeNull()
    expect(buildHotkeyCombo(event)).toBe("Meta+A")
  })

  it("rejects shortcuts with more than two modifiers", () => {
    const event = keydownEvent({
      code: "KeyA",
      key: "a",
      ctrlKey: true,
      altKey: true,
      shiftKey: true,
    })

    expect(getHotkeyCaptureIssue(event)).toBe("too_many_modifiers")
    expect(buildHotkeyCombo(event)).toBeNull()
  })

  it("reports keys outside the supported set", () => {
    const event = keydownEvent({ code: "F13", key: "F13" })

    expect(getHotkeyCaptureIssue(event)).toBe("unsupported_key")
    expect(buildHotkeyCombo(event)).toBeNull()
  })

  it.each([
    ["ControlLeft", "Control"],
    ["AltRight", "Alt"],
    ["ShiftLeft", "Shift"],
    ["MetaLeft", "Meta"],
  ])("returns null for a pure %s modifier", (code, key) => {
    const event = keydownEvent({ code, key })

    expect(buildHotkeyCombo(event)).toBeNull()
    expect(getHotkeyCaptureIssue(event)).toBeNull()
  })

  it.each([
    ["KeyA", "A"],
    ["KeyZ", "Z"],
    ["Digit7", "7"],
  ])("maps %s to %s", (code, expected) => {
    const event = keydownEvent({ code, key: code.slice(-1) })

    expect(buildHotkeyCombo(event)).toBe(expected)
  })

  it.each([
    ["F1", "F1"],
    ["F12", "F12"],
  ])("maps function key %s to %s", (code, expected) => {
    const event = keydownEvent({ code, key: code })

    expect(buildHotkeyCombo(event)).toBe(expected)
  })

  it.each([
    ["Semicolon", "SEMICOLON"],
    ["Equal", "EQUAL"],
    ["Comma", "COMMA"],
    ["Minus", "MINUS"],
    ["Period", "PERIOD"],
    ["Slash", "SLASH"],
    ["Backquote", "GRAVE"],
    ["BracketLeft", "LEFTBRACKET"],
    ["Backslash", "BACKSLASH"],
    ["BracketRight", "RIGHTBRACKET"],
    ["Quote", "APOSTROPHE"],
  ])("maps symbol key %s to %s", (code, expected) => {
    const event = keydownEvent({ code, key: "?" })

    expect(buildHotkeyCombo(event)).toBe(expected)
  })

  it.each([
    ["Numpad5", "NUMPAD5"],
    ["Numpad0", "NUMPAD0"],
    ["NumpadAdd", "NUMPADADD"],
    ["NumpadDecimal", "NUMPADDECIMAL"],
    ["NumpadEnter", "NUMPADENTER"],
  ])("maps numpad key %s to %s", (code, expected) => {
    const event = keydownEvent({ code, key: "5" })

    expect(buildHotkeyCombo(event)).toBe(expected)
  })

  it.each([
    ["ArrowLeft", "LEFT"],
    ["ArrowRight", "RIGHT"],
    ["ArrowUp", "UP"],
    ["ArrowDown", "DOWN"],
    ["Escape", "ESC"],
    ["Space", "SPACE"],
  ])("maps %s to %s", (code, expected) => {
    const event = keydownEvent({ code, key: code })

    expect(buildHotkeyCombo(event)).toBe(expected)
  })

  it("derives the primary key from code rather than the shifted character", () => {
    const event = keydownEvent({ code: "Digit1", key: "!", shiftKey: true })

    expect(buildHotkeyCombo(event)).toBe("Shift+1")
  })
})
