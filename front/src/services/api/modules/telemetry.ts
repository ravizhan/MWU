import { z } from "zod"

/** 遥测接收方脱敏信息（不含密钥部分）。 */
export interface TelemetryRecipient {
  project: string
  host: string
  path: string
  project_id: string
}

export interface TelemetryStatus {
  configured: boolean
  buildAllowed: boolean
  active: boolean
  configId: string
  recipient: TelemetryRecipient | null
  consent: "unknown" | "granted" | "denied"
  failureAttachments: boolean
}

export interface TelemetryConsentResult {
  success: boolean
  staleTarget: boolean
  message: string
  status: TelemetryStatus | null
}

const telemetryRecipientSchema = z.object({
  project: z.string(),
  host: z.string(),
  path: z.string(),
  project_id: z.string(),
})

const telemetryStatusSchema = z.object({
  configured: z.boolean(),
  buildAllowed: z.boolean(),
  active: z.boolean(),
  configId: z.string(),
  recipient: telemetryRecipientSchema.nullable(),
  consent: z.union([z.literal("unknown"), z.literal("granted"), z.literal("denied")]),
  failureAttachments: z.boolean(),
})

const telemetryEnvelopeSchema = z.object({
  status: z.string().optional(),
  message: z.string().optional(),
})

function parseStatus(data: unknown): TelemetryStatus | null {
  const parsed = telemetryStatusSchema.safeParse(data)
  return parsed.success ? parsed.data : null
}

/** 拉取遥测状态（授权门禁/接收方/附件授权）。失败抛错。 */
export async function getTelemetryStatus(): Promise<TelemetryStatus> {
  const response = await fetch("/api/telemetry")
  const parsed = telemetryStatusSchema
    .extend(telemetryEnvelopeSchema.shape)
    .safeParse(await response.json().catch(() => null))
  if (!parsed.success || parsed.data.status !== "success") {
    throw new Error(parsed.success ? parsed.data.message || "获取遥测状态失败" : "获取遥测状态失败")
  }
  const { status: _status, message: _message, ...status } = parsed.data
  return status
}

/** 提交遥测授权。409（目标变化）返回 staleTarget=true。 */
export async function postTelemetryConsent(payload: {
  configId: string
  consent: "granted" | "denied"
  failureAttachments?: boolean
}): Promise<TelemetryConsentResult> {
  const response = await fetch("/api/telemetry/consent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      configId: payload.configId,
      consent: payload.consent,
      failureAttachments: payload.failureAttachments ?? false,
    }),
  })
  const raw: unknown = await response.json().catch(() => null)
  const envelope = telemetryEnvelopeSchema.safeParse(raw)
  const status = parseStatus(raw)
  if (envelope.success && envelope.data.status === "success" && status) {
    return { success: true, staleTarget: false, message: "授权已保存", status }
  }
  return {
    success: false,
    staleTarget: response.status === 409,
    message: (envelope.success && envelope.data.message) || "授权保存失败",
    status: null,
  }
}
