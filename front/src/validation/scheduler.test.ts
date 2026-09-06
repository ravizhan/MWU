import { describe, expect, it } from "vitest"

import { schedulerTaskFormSchema, triggerConfigSchema } from "./scheduler"

describe("triggerConfigSchema", () => {
  it("accepts cron trigger", () => {
    const r = triggerConfigSchema.safeParse({ type: "cron", cron: "0 9 * * *" })
    expect(r.success).toBe(true)
  })

  it("rejects invalid cron", () => {
    expect(triggerConfigSchema.safeParse({ type: "cron", cron: "bad" }).success).toBe(false)
  })

  it("accepts date trigger", () => {
    const future = new Date(Date.now() + 86400000).toISOString()
    const r = triggerConfigSchema.safeParse({ type: "date", run_date: future })
    expect(r.success).toBe(true)
  })

  it("rejects past date", () => {
    const past = new Date(Date.now() - 86400000).toISOString()
    expect(triggerConfigSchema.safeParse({ type: "date", run_date: past }).success).toBe(false)
  })

  it("accepts interval trigger", () => {
    const r = triggerConfigSchema.safeParse({ type: "interval", hours: 1 })
    expect(r.success).toBe(true)
  })

  it("rejects zero interval", () => {
    expect(triggerConfigSchema.safeParse({ type: "interval" }).success).toBe(false)
  })

  it("rejects negative interval component", () => {
    expect(triggerConfigSchema.safeParse({ type: "interval", seconds: -1 }).success).toBe(false)
  })

  it("rejects unknown type", () => {
    expect(triggerConfigSchema.safeParse({ type: "unknown" }).success).toBe(false)
  })
})

describe("schedulerTaskFormSchema", () => {
  const validPayload = {
    name: "test task",
    trigger_config: { type: "cron" as const, cron: "0 9 * * *" },
    task_identity: "name",
    task_list: ["task1"],
  }

  it("accepts valid payload", () => {
    const r = schedulerTaskFormSchema.safeParse(validPayload)
    expect(r.success).toBe(true)
  })

  it("rejects empty name", () => {
    expect(schedulerTaskFormSchema.safeParse({ ...validPayload, name: "" }).success).toBe(false)
  })

  it("rejects whitespace-only name", () => {
    expect(schedulerTaskFormSchema.safeParse({ ...validPayload, name: "   " }).success).toBe(false)
  })

  it("strips name", () => {
    const r = schedulerTaskFormSchema.safeParse({ ...validPayload, name: "  hello  " })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.name).toBe("hello")
  })

  it("rejects empty task_list", () => {
    expect(schedulerTaskFormSchema.safeParse({ ...validPayload, task_list: [] }).success).toBe(
      false,
    )
  })

  it("rejects a missing task identity marker", () => {
    const payloadWithoutIdentity = {
      name: validPayload.name,
      trigger_config: validPayload.trigger_config,
      task_list: validPayload.task_list,
    }

    expect(schedulerTaskFormSchema.safeParse(payloadWithoutIdentity).success).toBe(false)
  })

  it("rejects the legacy entry task identity marker", () => {
    expect(
      schedulerTaskFormSchema.safeParse({ ...validPayload, task_identity: "entry" }).success,
    ).toBe(false)
  })
})
