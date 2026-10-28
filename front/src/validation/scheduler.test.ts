import { describe, expect, it } from "vitest"

import { schedulerTaskFormSchema, triggerConfigSchema } from "./scheduler"

describe("triggerConfigSchema", () => {
  it("accepts a cron trigger and rejects an invalid expression", () => {
    expect(triggerConfigSchema.safeParse({ type: "cron", cron: "0 9 * * *" }).success).toBe(true)
    expect(triggerConfigSchema.safeParse({ type: "cron", cron: "bad" }).success).toBe(false)
  })

  it("requires a future date", () => {
    const future = new Date(Date.now() + 86400000).toISOString()
    const past = new Date(Date.now() - 86400000).toISOString()
    expect(triggerConfigSchema.safeParse({ type: "date", run_date: future }).success).toBe(true)
    expect(triggerConfigSchema.safeParse({ type: "date", run_date: past }).success).toBe(false)
  })

  it("requires an interval of at least one second", () => {
    expect(triggerConfigSchema.safeParse({ type: "interval", hours: 1 }).success).toBe(true)
    expect(triggerConfigSchema.safeParse({ type: "interval" }).success).toBe(false)
    expect(triggerConfigSchema.safeParse({ type: "interval", seconds: -1 }).success).toBe(false)
  })

  it("reports an end date before the start date on the end_date field", () => {
    const result = triggerConfigSchema.safeParse({
      type: "interval",
      hours: 1,
      start_date: "2026-10-28T10:00:00",
      end_date: "2026-10-28T09:00:00",
    })
    expect(result.success).toBe(false)
    expect(result.error?.issues[0].path).toEqual(["end_date"])
  })

  it("rejects an unknown trigger type", () => {
    expect(triggerConfigSchema.safeParse({ type: "unknown" }).success).toBe(false)
  })
})

describe("schedulerTaskFormSchema", () => {
  const validPayload = {
    name: "test task",
    trigger_config: { type: "cron" as const, cron: "0 9 * * *" },
    task_list: ["task1"],
  }

  it("accepts a valid payload", () => {
    expect(schedulerTaskFormSchema.safeParse(validPayload).success).toBe(true)
  })

  it("trims the name and rejects a blank one", () => {
    expect(schedulerTaskFormSchema.parse({ ...validPayload, name: "  hello  " }).name).toBe("hello")
    expect(schedulerTaskFormSchema.safeParse({ ...validPayload, name: "   " }).success).toBe(false)
  })

  it("rejects an empty task_list", () => {
    expect(schedulerTaskFormSchema.safeParse({ ...validPayload, task_list: [] }).success).toBe(
      false,
    )
  })
})
