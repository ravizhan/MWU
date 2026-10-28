import { describe, expect, it, vi } from "vitest"
import {
  formatTrigger,
  formatDateTime,
  getOriginLabel,
  getStatusType,
  getStatusLabel,
} from "@/utils/scheduler/display"
import type {
  ExecutionOrigin,
  ExecutionStatus,
  IntervalTriggerConfig,
} from "@/types/schedulerModel"

const t = vi.fn<(key: string) => string>((key: string) => key)

describe("formatTrigger", () => {
  it("formats cron triggers", () => {
    expect(formatTrigger(t, "zh-CN", { type: "cron", cron: "0 0 * * *" })).toBe(
      "settings.scheduler.formatter.cron 0 0 * * *",
    )
  })

  it("formats date triggers with a formatted date", () => {
    const result = formatTrigger(t, "zh-CN", { type: "date", run_date: "2024-06-15T08:30:00Z" })
    expect(result).toContain("settings.scheduler.formatter.date")
    expect(result).toContain("2024")
  })

  it("formats interval triggers", () => {
    const config: IntervalTriggerConfig = {
      type: "interval",
      weeks: 1,
      days: 2,
      hours: 3,
      minutes: 4,
      seconds: 5,
    }
    expect(formatTrigger(t, "zh-CN", config)).toBe(
      "settings.scheduler.formatter.interval " +
        "1settings.scheduler.formatter.week " +
        "2settings.scheduler.formatter.day " +
        "3settings.scheduler.formatter.hour " +
        "4settings.scheduler.formatter.minute " +
        "5settings.scheduler.formatter.second",
    )
  })

  it("formats an empty interval as unset", () => {
    expect(formatTrigger(t, "zh-CN", { type: "interval" })).toBe(
      "settings.scheduler.formatter.interval settings.scheduler.formatter.unset",
    )
  })
})

describe("formatDateTime", () => {
  it("formats a valid date string", () => {
    expect(formatDateTime(t, "zh-CN", "2024-06-15T08:30:00Z")).toMatch(/2024/)
  })

  it("returns unset for a missing date", () => {
    expect(formatDateTime(t, "zh-CN", undefined)).toBe("settings.scheduler.formatter.unset")
    expect(formatDateTime(t, "zh-CN", "")).toBe("settings.scheduler.formatter.unset")
  })
})

describe("getStatusType", () => {
  it.each([
    ["success", "success"],
    ["failed", "error"],
    ["running", "info"],
    ["stopped", "warning"],
    ["skipped_busy_manual", "warning"],
  ] satisfies [ExecutionStatus, ReturnType<typeof getStatusType>][])(
    "maps %s to %s",
    (status, expected) => {
      expect(getStatusType(status)).toBe(expected)
    },
  )

  it("returns default for unknown status", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getStatusType("unknown" as ExecutionStatus)).toBe("default")
  })
})

describe("getStatusLabel", () => {
  it.each([
    ["success", "settings.scheduler.status.success"],
    ["failed", "settings.scheduler.status.failed"],
    ["skipped_update_in_progress", "settings.scheduler.status.skippedUpdateInProgress"],
  ] satisfies [ExecutionStatus, string][])("maps %s to %s", (status, expected) => {
    expect(getStatusLabel(t, status)).toBe(expected)
  })

  it("returns unknown for unknown status", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getStatusLabel(t, "unknown" as ExecutionStatus)).toBe("common.unknown")
  })
})

describe("getOriginLabel", () => {
  it.each([
    ["manual", "settings.scheduler.origin.manual"],
    ["in_app", "settings.scheduler.origin.inApp"],
    ["native", "settings.scheduler.origin.native"],
  ] satisfies [ExecutionOrigin, string][])("maps %s to %s", (origin, expected) => {
    expect(getOriginLabel(t, origin)).toBe(expected)
  })

  it("returns unknown for unknown origin", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(getOriginLabel(t, "unknown" as ExecutionOrigin)).toBe("common.unknown")
  })
})
