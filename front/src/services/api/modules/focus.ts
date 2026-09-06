import type { ApiResponse } from "@/services/api/core/types"

/** 后端 focus 交互（dialog / modal）公开状态。 */
export interface FocusInteractionPayload {
  id: string
  run_id: string
  mode: "dialog" | "modal"
  state: "pending" | "acknowledged" | "cancelled"
  content: string
  created_at: number
}

interface FocusInteractionListResponse extends ApiResponse {
  status: "success"
  data: FocusInteractionPayload[]
}

interface FocusInteractionResponse extends ApiResponse {
  status: "success"
  data: FocusInteractionPayload
}

/** 拉取当前 pending 的焦点交互。失败抛错（调用方自行决定静默）。 */
export async function fetchFocusInteractions(): Promise<FocusInteractionPayload[]> {
  const response = await fetch("/api/focus/interactions")
  const payload = (await response.json()) as
    | FocusInteractionListResponse
    | (ApiResponse & { status: "failed" })
  if (payload.status !== "success" || !Array.isArray(payload.data)) {
    throw new Error(
      payload.status === "failed" && payload.message ? payload.message : "获取焦点交互失败",
    )
  }
  return payload.data
}

/** 确认一个交互。后端 409/404 视为已结束（抛错由调用方吞掉）。 */
export async function acknowledgeFocusInteraction(id: string): Promise<void> {
  const response = await fetch(`/api/focus/interactions/${id}/ack`, {
    method: "POST",
  })
  const payload = (await response.json()) as
    | FocusInteractionResponse
    | (ApiResponse & { status: "failed" })
  if (payload.status !== "success") {
    throw new Error(payload.status === "failed" && payload.message ? payload.message : "确认失败")
  }
}

/** 取消一个交互。后端 409/404 视为已结束。 */
export async function cancelFocusInteraction(id: string): Promise<void> {
  const response = await fetch(`/api/focus/interactions/${id}/cancel`, {
    method: "POST",
  })
  const payload = (await response.json()) as
    | FocusInteractionResponse
    | (ApiResponse & { status: "failed" })
  if (payload.status !== "success") {
    throw new Error(payload.status === "failed" && payload.message ? payload.message : "取消失败")
  }
}
