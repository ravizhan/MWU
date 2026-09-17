import { z } from "zod"

const integerStringSchema = z.string().regex(z.regexes.integer)
const portSchema = integerStringSchema.pipe(z.coerce.number<string>().int().min(1).max(65535))
const positiveIntegerSchema = z
  .string()
  .trim()
  .pipe(integerStringSchema)
  .pipe(z.coerce.number<string>().int().positive().safe())
  .transform(String)

/** IPv4 or hostname plus TCP port, normalized to host:port. */
export const hostPortSchema = z
  .string()
  .trim()
  .min(1, "address must not be empty")
  .transform((address, ctx) => {
    const separator = address.lastIndexOf(":")
    const rawHost = address.slice(0, separator)
    const ipv4Segments = rawHost.split(".")
    const hostResult =
      ipv4Segments.length === 4 &&
      ipv4Segments.every((segment) => integerStringSchema.safeParse(segment).success)
        ? z.ipv4().safeParse(ipv4Segments.map(Number).join("."))
        : z.hostname().safeParse(rawHost)
    const portResult = portSchema.safeParse(address.slice(separator + 1))

    if (separator <= 0 || !hostResult.success || !portResult.success) {
      ctx.issues.push({
        code: "custom",
        input: address,
        message: "address must be a valid host:port",
      })
      return z.NEVER
    }

    return `${hostResult.data}:${portResult.data}`
  })

const win32AddressSchema = positiveIntegerSchema

const gamepadAddressSchema = z
  .string()
  .trim()
  .transform((address, ctx) => {
    const [rawHwnd, rawType, extra] = address.split("|")
    const hwndResult = positiveIntegerSchema.safeParse(rawHwnd)
    const typeResult = z.enum(["0", "1"]).safeParse(rawType)

    if (extra !== undefined || !hwndResult.success || !typeResult.success) {
      ctx.issues.push({
        code: "custom",
        input: address,
        message: "Gamepad address must be hWnd|type (0 or 1)",
      })
      return z.NEVER
    }

    return `${hwndResult.data}|${typeResult.data}`
  })

/** Custom (user-entered) device address: strict validation. */
export const customDeviceAddressSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("Adb"),
    address: hostPortSchema,
  }),
  z.object({
    type: z.literal("PlayCover"),
    address: hostPortSchema,
  }),
  z.object({
    type: z.literal("Win32"),
    address: win32AddressSchema,
  }),
  z.object({
    type: z.literal("Gamepad"),
    address: gamepadAddressSchema,
  }),
  z.object({
    type: z.literal("Linux"),
    address: z.string().trim().min(1, "Linux device address must not be empty"),
  }),
])

/** Runtime (scanned) device address: Adb allows USB serials. */
export const runtimeDeviceAddressSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("Adb"),
    address: z.string().trim().min(1, "Adb address must not be empty"),
  }),
  z.object({
    type: z.literal("PlayCover"),
    address: hostPortSchema,
  }),
  z.object({
    type: z.literal("Win32"),
    address: win32AddressSchema,
  }),
  z.object({
    type: z.literal("Gamepad"),
    address: gamepadAddressSchema,
  }),
  z.object({
    type: z.literal("Linux"),
    address: z.string().trim().min(1, "Linux device address must not be empty"),
  }),
])

/** PlayCover address schema for connection store. */
export const playCoverAddressSchema = hostPortSchema
