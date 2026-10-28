import { z } from "zod"

export const updateChannelSchema = z.enum(["stable", "beta"])

export const localeSchema = z.enum(["zh-CN", "en-US"])

export const darkModeSchema = z.union([z.literal("auto"), z.boolean()])

/** Runtime number schema: empty string = no update, otherwise finite integer with clamp. */
export function makeRuntimeNumberSchema(min: number, max: number) {
  return z.union([z.literal(""), z.string(), z.number()]).transform((val) => {
    if (val === "") return undefined // no update
    const n = typeof val === "string" ? Number(val) : val
    if (Number.isNaN(n) || !Number.isFinite(n) || !Number.isInteger(n)) return undefined
    return Math.round(Math.min(Math.max(n, min), max))
  })
}
