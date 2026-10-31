import { describe, expect, it } from "vitest"
import {
  buildDefaultsFromOptionMap,
  buildOrderedCheckboxValue,
  normalizeOptionValueForBoundary,
} from "@/utils/task-config/options"
import type { Option } from "@/types/interfaceModel"
import type { TaskOptionValue } from "@/types/schedulerModel"

describe("buildOrderedCheckboxValue", () => {
  it("preserves case order, not default_case order", () => {
    // cases: c, a, b — default_case picks "a" and "c"
    // result should follow the *cases* order: c then a
    const option: Extract<Option, { type: "checkbox" }> = {
      type: "checkbox",
      cases: [{ name: "c" }, { name: "a" }, { name: "b" }],
      default_case: ["a", "c"],
    }

    const result = buildOrderedCheckboxValue(option)
    expect(result).toEqual(["c", "a"])
  })

  it("filters out names not present in cases", () => {
    const option: Extract<Option, { type: "checkbox" }> = {
      type: "checkbox",
      cases: [{ name: "a" }, { name: "b" }],
      default_case: ["a", "c", "b"],
    }

    const result = buildOrderedCheckboxValue(option)
    expect(result).toEqual(["a", "b"])
  })

  it("handles undefined default_case", () => {
    const option: Extract<Option, { type: "checkbox" }> = {
      type: "checkbox",
      cases: [{ name: "a" }, { name: "b" }],
    }

    const result = buildOrderedCheckboxValue(option)
    expect(result).toEqual([])
  })
})

describe("buildDefaultsFromOptionMap", () => {
  it("builds defaults for select types", () => {
    const optionMap: Record<string, Option> = {
      difficulty: {
        type: "select",
        cases: [{ name: "easy" }, { name: "hard" }],
        default_case: "hard",
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ difficulty: "hard" })
  })

  it("uses first case when no default_case for select", () => {
    const optionMap: Record<string, Option> = {
      mode: {
        type: "select",
        cases: [{ name: "auto" }, { name: "manual" }],
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ mode: "auto" })
  })

  it("uses first case when default_case is not one of the cases", () => {
    const optionMap: Record<string, Option> = {
      bad: {
        type: "select",
        cases: [{ name: "a" }, { name: "b" }],
        default_case: "missing",
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ bad: "a" })
  })

  it("produces empty string when cases array is empty for select", () => {
    const optionMap: Record<string, Option> = {
      empty: {
        type: "select",
        cases: [],
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ empty: "" })
  })

  it("builds defaults for input types", () => {
    const optionMap: Record<string, Option> = {
      params: {
        type: "input",
        inputs: [{ name: "host", default: "localhost" }, { name: "port" }],
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({
      params: { host: "localhost", port: "" },
    })
  })

  it("builds object defaults for hotkey types", () => {
    const optionMap: Record<string, Option> = {
      shortcuts: {
        type: "hotkey",
        hotkeys: [{ name: "start", default: "Ctrl+S" }, { name: "stop" }],
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({
      shortcuts: { start: "Ctrl+S", stop: "" },
    })
  })

  it("builds defaults for switch types", () => {
    const optionMap: Record<string, Option> = {
      toggle: {
        type: "switch",
        cases: [{ name: "off" }, { name: "on" }],
        default_case: "on",
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ toggle: "on" })
  })

  it("uses first case when no default_case for switch", () => {
    const optionMap: Record<string, Option> = {
      toggle: {
        type: "switch",
        cases: [{ name: "off" }, { name: "on" }],
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ toggle: "off" })
  })

  it("builds defaults for checkbox types", () => {
    const optionMap: Record<string, Option> = {
      features: {
        type: "checkbox",
        cases: [{ name: "a" }, { name: "b" }, { name: "c" }],
        default_case: ["a", "c"],
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ features: ["a", "c"] })
  })

  it("handles scan_select like select", () => {
    const optionMap: Record<string, Option> = {
      tool: {
        type: "scan_select",
        scan_dir: "./tools",
        scan_filter: "*.json",
        cases: [{ name: "hammer" }, { name: "screwdriver" }],
        default_case: "hammer",
      },
    }

    const result = buildDefaultsFromOptionMap(optionMap)
    expect(result).toEqual({ tool: "hammer" })
  })
})

describe("normalizeOptionValueForBoundary", () => {
  it("returns undefined for undefined input", () => {
    expect(normalizeOptionValueForBoundary(undefined)).toBeUndefined()
  })

  it("returns empty string for null input", () => {
    expect(normalizeOptionValueForBoundary(null)).toBe("")
  })

  it("passes strings through unchanged", () => {
    expect(normalizeOptionValueForBoundary("hello")).toBe("hello")
  })

  it("filters non-string items from arrays", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const result = normalizeOptionValueForBoundary(["a", 123, "b", null, "c"] as TaskOptionValue)
    expect(result).toEqual(["a", "b", "c"])
  })

  it("normalizes object values to string record", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const result = normalizeOptionValueForBoundary({
      host: "localhost",
      port: 8080,
    } as unknown as TaskOptionValue)
    expect(result).toEqual({ host: "localhost" })
  })

  it("normalizes malformed persisted non-object to empty record", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const result = normalizeOptionValueForBoundary(42 as unknown as TaskOptionValue)
    expect(result).toEqual({})
  })
})
