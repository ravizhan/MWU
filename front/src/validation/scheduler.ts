import { z } from "zod"
import { cronExpressionSchema } from "./cron"
import { runtimeDeviceAddressSchema } from "./device"

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
    { message: "end date must not be before start date" },
  )

export const triggerConfigSchema = z.discriminatedUnion("type", [
  cronTriggerSchema,
  dateTriggerSchema,
  intervalTriggerSchema,
])

const preTaskCommandSchema = z.object({
  id: z.string().optional(),
  command: z.string(),
  enabled: z.boolean().default(true),
  timeout: z.number().int().min(1).max(3600).default(30),
})

const deviceConfigSchema = z
  .object({
    controller_name: z.string().trim().min(1),
    device_type: z.enum(["Adb", "Win32", "Gamepad", "PlayCover", "MacOS", "Linux"]),
    device_address: z.string().trim().min(1),
  })
  .superRefine((val, ctx) => {
    const result = runtimeDeviceAddressSchema.safeParse({
      type: val.device_type,
      address: val.device_address,
    })
    if (!result.success) {
      for (const issue of result.error.issues) {
        ctx.addIssue({ ...issue, path: ["device_address"] })
      }
    }
  })

/** Full scheduler task form payload schema. */
export const schedulerTaskFormSchema = z.object({
  name: taskNameSchema,
  description: z.string().max(500).optional().nullable(),
  enabled: z.boolean().default(true),
  wakeup_enabled: z.boolean().default(false),
  trigger_config: triggerConfigSchema,
  task_identity: z.literal("name"),
  task_list: z.array(z.string()).min(1, "task list must not be empty"),
  task_options: z
    .record(
      z.string(),
      z.record(
        z.string(),
        z.union([z.string(), z.array(z.string()), z.record(z.string(), z.string())]),
      ),
    )
    .default({}),
  preTasks: z.array(preTaskCommandSchema).default([]),
  controller_name: z.string().nullable().optional(),
  device: deviceConfigSchema.nullable().optional(),
  resource_name: z.string().nullable().optional(),
})
