import { describe, expect, it } from "vitest"

import {
  darkModeSchema,
  localeSchema,
  makeRuntimeNumberSchema,
  updateChannelSchema,
} from "./settings"

describe("enum schemas", () => {
  it.each([
    [updateChannelSchema, "stable", "alpha"],
    [localeSchema, "zh-CN", "fr-FR"],
    [darkModeSchema, "auto", "dark"],
  ])("accepts valid and rejects invalid members", (schema, accepted, rejected) => {
    expect(schema.safeParse(accepted).success).toBe(true)
    expect(schema.safeParse(rejected).success).toBe(false)
  })

  it("darkModeSchema accepts booleans", () => {
    expect(darkModeSchema.safeParse(true).success).toBe(true)
    expect(darkModeSchema.safeParse(false).success).toBe(true)
  })
})

describe("makeRuntimeNumberSchema", () => {
  const schema = makeRuntimeNumberSchema(60, 3600)

  it("parses string and number input", () => {
    expect(schema.parse("300")).toBe(300)
    expect(schema.parse(300)).toBe(300)
  })

  it("clamps into range", () => {
    expect(schema.parse("10")).toBe(60)
    expect(schema.parse("9999")).toBe(3600)
  })

  it("returns undefined for empty or non-numeric input", () => {
    expect(schema.parse("")).toBeUndefined()
    expect(schema.parse("abc")).toBeUndefined()
  })
})
