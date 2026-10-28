import { z } from "zod"
import { cronExpressionSchema } from "./cron"

const taskNameSchema = z
  .string()
  .trim()
  .min(1, "task name must not be empty")
  .max(100, "task name must be at most 100 characters")

const cronTriggerSchema = z.object({
  type: z.literal("cron"),
  cron: cronExpressionSchema,
})

const dateTriggerSchema = z.object({
  type: z.literal("date"),
  run_date: z
    .string()
    .min(1, "date is required")
    .refine((val) => {
      const d = new Date(val)
      return !Number.isNaN(d.getTime())
    }, "invalid date")
    .refine((val) => new Date(val).getTime() >= Date.now(), {
      message: "date must be in the future",
    }),
})

const intervalTriggerSchema = z
  .object({
    type: z.literal("interval"),
    weeks: z.number().int().min(0).optional(),
    days: z.number().int().min(0).optional(),
    hours: z.number().int().min(0).optional(),
    minutes: z.number().int().min(0).optional(),
    seconds: z.number().int().min(0).optional(),
    start_date: z.string().optional(),
    end_date: z.string().optional(),
  })
  .refine(
    (val) => {
      const total =
        (val.weeks ?? 0) * 604800 +
        (val.days ?? 0) * 86400 +
        (val.hours ?? 0) * 3600 +
        (val.minutes ?? 0) * 60 +
        (val.seconds ?? 0)
      return total >= 1
    },
    { message: "interval must be at least 1 second" },
  )
  .refine(
    (val) => {
      if (!val.start_date || !val.end_date) return true
      return new Date(val.end_date).getTime() >= new Date(val.start_date).getTime()
    },
    { message: "end date must not be before start date", path: ["end_date"] },
  )

export const triggerConfigSchema = z.discriminatedUnion("type", [
  cronTriggerSchema,
  dateTriggerSchema,
  intervalTriggerSchema,
])

/**
 * 只校验用户可在对话框里改错的部分；description / task_options / preTasks /
 * device 等字段由后端 pydantic 模型负责。
 */
export const schedulerTaskFormSchema = z.object({
  name: taskNameSchema,
  trigger_config: triggerConfigSchema,
  task_list: z.array(z.string()).min(1, "task list must not be empty"),
})
