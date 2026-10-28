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

  it("derives the primary key from code rather than the shifted character", () => {
    const event = keydownEvent({ code: "Digit1", key: "!", shiftKey: true })

    expect(buildHotkeyCombo(event)).toBe("Shift+1")
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
    ["KeyA", "a", "A"],
    ["Digit7", "7", "7"],
    ["F1", "F1", "F1"],
    ["Semicolon", "?", "SEMICOLON"],
    ["Numpad5", "5", "NUMPAD5"],
    ["ArrowLeft", "ArrowLeft", "LEFT"],
    ["Escape", "Escape", "ESC"],
  ])("maps %s to %s", (code, key, expected) => {
    expect(buildHotkeyCombo(keydownEvent({ code, key }))).toBe(expected)
  })
})
