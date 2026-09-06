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

const linuxAddressShape = {
  kind: z.enum(["wlr", "gamescope", "portal"]),
  display_no: z.number().int().nonnegative().optional(),
  wlr_socket_path: z
    .string()
    .transform((value) => value.trim())
    .optional(),
  uinput_path: z
    .string()
    .transform((value) => value.trim())
    .optional(),
  uinput_screen_width: z.number().int().positive().optional(),
  uinput_screen_height: z.number().int().positive().optional(),
  eis_socket_path: z
    .string()
    .transform((value) => value.trim())
    .optional(),
}

const linuxAddressObjectSchema = z
  .object(linuxAddressShape)
  .strict()
  .superRefine((value, ctx) => {
    if (value.kind === "wlr" && !value.wlr_socket_path) {
      ctx.addIssue({
        code: "custom",
        path: ["wlr_socket_path"],
        message: "wlr mode requires a non-empty wlr_socket_path",
      })
    }
    if (value.kind === "gamescope" && value.display_no === undefined) {
      ctx.addIssue({
        code: "custom",
        path: ["display_no"],
        message: "gamescope mode requires a non-negative display_no",
      })
    }

    const hasUInputFields =
      value.uinput_path !== undefined ||
      value.uinput_screen_width !== undefined ||
      value.uinput_screen_height !== undefined
    if (
      hasUInputFields &&
      (value.uinput_screen_width === undefined || value.uinput_screen_height === undefined)
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["uinput_screen_width"],
        message: "UInput requires positive uinput_screen_width and uinput_screen_height",
      })
    }
  })
  .transform((value) => {
    if (
      !value.uinput_path &&
      (value.uinput_screen_width !== undefined || value.uinput_screen_height !== undefined)
    ) {
      return { ...value, uinput_path: "/dev/uinput" }
    }
    return value
  })

const linuxRuntimeAddressObjectSchema = z
  .object(linuxAddressShape)
  .strict()
  .transform((value) => {
    if (
      !value.uinput_path &&
      (value.uinput_screen_width !== undefined || value.uinput_screen_height !== undefined)
    ) {
      return { ...value, uinput_path: "/dev/uinput" }
    }
    return value
  })

function decodeJsonAddress(address: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(address) }
  } catch {
    return { ok: false }
  }
}

function canonicalizeLinuxAddress(value: object): string {
  const serialize = (field: unknown): string => {
    const serialized = JSON.stringify(field) ?? "null"
    return serialized.replace(
      /[^\u0000-\u007f]/g,
      (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
    )
  }
  const fields = Object.entries(value)
    .filter(([, field]) => field !== undefined)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([key, field]) => `${serialize(key)}: ${serialize(field)}`)
  return `{${fields.join(", ")}}`
}

const linuxCustomAddressSchema = z
  .string()
  .trim()
  .transform((address, ctx) => {
    const decoded = decodeJsonAddress(address)
    if (!decoded.ok) {
      ctx.issues.push({
        code: "custom",
        input: address,
        message: "Linux address must be a JSON object string",
      })
      return z.NEVER
    }
    const result = linuxAddressObjectSchema.safeParse(decoded.value)
    if (!result.success) {
      ctx.issues.push({
        code: "custom",
        input: address,
        message: result.error.issues[0]?.message || "Invalid Linux device address",
      })
      return z.NEVER
    }
    return canonicalizeLinuxAddress(result.data)
  })

const linuxRuntimeAddressSchema = z
  .string()
  .trim()
  .transform((address, ctx) => {
    const decoded = decodeJsonAddress(address)
    if (!decoded.ok) {
      ctx.issues.push({
        code: "custom",
        input: address,
        message: "Linux address must be a JSON object string",
      })
      return z.NEVER
    }
    const result = linuxRuntimeAddressObjectSchema.safeParse(decoded.value)
    if (!result.success) {
      ctx.issues.push({
        code: "custom",
        input: address,
        message: result.error.issues[0]?.message || "Invalid Linux device address",
      })
      return z.NEVER
    }
    return canonicalizeLinuxAddress(result.data)
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
    type: z.literal("MacOS"),
    address: positiveIntegerSchema,
  }),
  z.object({
    type: z.literal("Linux"),
    address: linuxCustomAddressSchema,
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
    type: z.literal("MacOS"),
    address: positiveIntegerSchema,
  }),
  z.object({
    type: z.literal("Linux"),
    address: linuxRuntimeAddressSchema,
  }),
])

/** PlayCover address schema for connection store. */
export const playCoverAddressSchema = hostPortSchema
