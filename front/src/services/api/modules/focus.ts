import { z } from "zod"

/** 后端 focus 交互（dialog / modal）公开状态。 */
export interface FocusInteractionPayload {
  id: string
  run_id: string
  mode: "dialog" | "modal"
  state: "pending" | "acknowledged" | "cancelled"
  content: string
  created_at: number
}

/** 携带 HTTP 状态码的错误，供调用方区分 404/409（后端已结束）与网络/5xx。 */
export class FocusInteractionError extends Error {
  readonly httpStatus: number | null

  constructor(message: string, httpStatus: number | null) {
    super(message)
    this.name = "FocusInteractionError"
    this.httpStatus = httpStatus
  }
}

const focusInteractionSchema = z.object({
  id: z.string(),
  run_id: z.string(),
  mode: z.union([z.literal("dialog"), z.literal("modal")]),
  state: z.union([z.literal("pending"), z.literal("acknowledged"), z.literal("cancelled")]),
  content: z.string(),
  created_at: z.number(),
})

const focusResponseSchema = z.object({
  status: z.string().optional(),
  message: z.string().optional(),
  data: z.unknown().optional(),
})

type FocusResponse = z.infer<typeof focusResponseSchema>

async function readEnvelope(response: Response): Promise<FocusResponse | null> {
  const parsed = focusResponseSchema.safeParse(await response.json().catch(() => null))
  return parsed.success ? parsed.data : null
}

/** 拉取当前 pending 的焦点交互。失败抛错（调用方自行决定静默）。 */
export async function fetchFocusInteractions(): Promise<FocusInteractionPayload[]> {
  const response = await fetch("/api/focus/interactions")
  const envelope = await readEnvelope(response)
  const parsed = z.array(focusInteractionSchema).safeParse(envelope?.data)
  if (envelope?.status !== "success" || !parsed.success) {
    throw new FocusInteractionError(envelope?.message || "获取焦点交互失败", response.status)
  }
  return parsed.data
}

/** 确认一个交互。404/409 表示后端已结束（由调用方区分）。 */
export async function acknowledgeFocusInteraction(id: string): Promise<void> {
  const response = await fetch(`/api/focus/interactions/${id}/ack`, {
    method: "POST",
  })
  const envelope = await readEnvelope(response)
  if (envelope?.status !== "success") {
    throw new FocusInteractionError(envelope?.message || "确认失败", response.status)
  }
}

/** 取消一个交互。404/409 表示后端已结束（由调用方区分）。 */
export async function cancelFocusInteraction(id: string): Promise<void> {
  const response = await fetch(`/api/focus/interactions/${id}/cancel`, {
    method: "POST",
  })
  const envelope = await readEnvelope(response)
  if (envelope?.status !== "success") {
    throw new FocusInteractionError(envelope?.message || "取消失败", response.status)
  }
}
