import type { ApiResponse } from "@/services/api/core/types"

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

interface TelemetryStatusResponse extends TelemetryStatus, ApiResponse {
  status: "success"
}

interface TelemetryConsentRequest {
  configId: string
  consent: "granted" | "denied"
  failureAttachments?: boolean
}

/** 拉取遥测状态（授权门禁/接收方/附件授权）。失败抛错。 */
export async function getTelemetryStatus(): Promise<TelemetryStatus> {
  const response = await fetch("/api/telemetry")
  const payload = (await response.json()) as TelemetryStatusResponse
  if (payload.status !== "success") {
    throw new Error(payload.message || "获取遥测状态失败")
  }
  return {
    configured: payload.configured,
    buildAllowed: payload.buildAllowed,
    active: payload.active,
    configId: payload.configId,
    recipient: payload.recipient,
    consent: payload.consent,
    failureAttachments: payload.failureAttachments,
  }
}

export interface TelemetryConsentResult {
  success: boolean
  staleTarget: boolean
  message: string
  status: TelemetryStatus | null
}

/** 提交遥测授权。409（目标变化）返回 staleTarget=true。 */
export async function postTelemetryConsent(
  payload: TelemetryConsentRequest,
): Promise<TelemetryConsentResult> {
  const response = await fetch("/api/telemetry/consent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      configId: payload.configId,
      consent: payload.consent,
      failureAttachments: payload.failureAttachments ?? false,
    }),
  })
  const data = (await response.json()) as
    | TelemetryStatusResponse
    | (ApiResponse & { status: "failed" })
  if (data.status === "success") {
    return {
      success: true,
      staleTarget: false,
      message: "授权已保存",
      status: {
        configured: data.configured,
        buildAllowed: data.buildAllowed,
        active: data.active,
        configId: data.configId,
        recipient: data.recipient,
        consent: data.consent,
        failureAttachments: data.failureAttachments,
      },
    }
  }
  return {
    success: false,
    staleTarget: response.status === 409,
    message: data.message || "授权保存失败",
    status: null,
  }
}
