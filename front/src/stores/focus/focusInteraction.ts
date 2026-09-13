import { defineStore } from "pinia"
import { ref } from "vue"
import {
  fetchFocusInteractions,
  acknowledgeFocusInteraction,
  cancelFocusInteraction,
  FocusInteractionError,
} from "@/services/api/modules/focus"
import { showGlobalDialog, showGlobalMessage } from "@/services/feedback/message"
import type { FocusInteractionPayload } from "@/services/api/modules/focus"
import { tryCatch } from "@/utils/tryCatch"

/** 后端 focus 交互（dialog / modal）的前端状态（API 契约别名）。 */
export type FocusInteraction = FocusInteractionPayload

type FocusRealtimeLevel = "info" | "success" | "warning" | "error"

/** SSE focus.interaction 负载；字段由 store 在入口处运行时收窄。 */
export interface FocusInteractionRealtimePayload {
  id?: unknown
  mode?: unknown
  state?: unknown
  run_id?: unknown
  phase?: unknown
  content?: unknown
  title?: unknown
  level?: unknown
}

/**
 * pending 焦点交互仓库。
 *
 * - SSE `focus.interaction`（phase=created/finished）驱动状态变化；
 * - 打开页面时 GET /api/focus/interactions 拉取漏掉的 pending 项（去重合并）；
 * - modal 阻塞后端流水线，用户确认/取消后 POST ack/cancel。
 */
export const useFocusInteractionStore = defineStore("focusInteraction", () => {
  const pending = ref<FocusInteraction[]>([])
  /** GET-then-merge 完成标记（App 挂载后执行一次） */
  const hydrated = ref(false)

  function upsert(interaction: FocusInteraction): void {
    // Dialogs are display-only realtime events.  They never enter the modal
    // pending list or the hydrate path.
    if (interaction.mode === "dialog") {
      return
    }
    if (interaction.state !== "pending") {
      removeById(interaction.id)
      return
    }
    const existing = pending.value.find((item) => item.id === interaction.id)
    if (existing) {
      Object.assign(existing, interaction)
      return
    }
    pending.value.push(interaction)
  }

  function removeById(id: string): void {
    const index = pending.value.findIndex((item) => item.id === id)
    if (index >= 0) {
      pending.value.splice(index, 1)
    }
  }

  /** SSE focus.interaction（details.phase = created | finished）。 */
  function applyRealtime(payload: FocusInteractionRealtimePayload): void {
    const id = typeof payload.id === "string" ? payload.id : ""
    if (!id) {
      return
    }
    const mode = payload.mode === "dialog" ? "dialog" : "modal"
    if (payload.phase === "created" && mode === "dialog") {
      const content = typeof payload.content === "string" ? payload.content : ""
      const type: FocusRealtimeLevel =
        payload.level === "success" || payload.level === "warning" || payload.level === "error"
          ? payload.level
          : "info"
      const title = typeof payload.title === "string" ? payload.title : undefined
      showGlobalDialog(type, content, title)
      return
    }
    const state =
      payload.state === "acknowledged" || payload.state === "cancelled" ? payload.state : "pending"
    if (payload.phase === "finished" || state !== "pending") {
      removeById(id)
      return
    }
    upsert({
      id,
      run_id: typeof payload.run_id === "string" ? payload.run_id : "",
      mode,
      state,
      content: typeof payload.content === "string" ? payload.content : "",
      created_at: Date.now(),
    })
  }

  /** 打开页面时拉取后端 pending 项（SSE 之前的漏网）。 */
  async function hydrate(): Promise<void> {
    if (hydrated.value) {
      return
    }
    hydrated.value = true
    const [remote] = await tryCatch(() => fetchFocusInteractions())
    if (!remote) {
      // 拉取失败不阻塞；SSE 仍会补
      return
    }
    for (const item of remote) {
      upsert(item)
    }
  }

  async function acknowledge(id: string): Promise<boolean> {
    const [, error] = await tryCatch(() => acknowledgeFocusInteraction(id))
    if (!error) {
      removeById(id)
      return true
    }
    // 仅 404/409 证明后端交互已结束（本地移除）；网络错误/5xx 时后端仍
    // 阻塞在 wait_modal()，保留仍 pending 项作为用户唯一的解除入口，不能复活
    // 已被 finished 移除的 modal。
    if (error instanceof FocusInteractionError && [404, 409].includes(error.httpStatus ?? 0)) {
      removeById(id)
      return false
    }
    // 非终态失败时保持当前 pending；不要用旧快照复活已由 SSE finished
    // 移除的 modal。
    showGlobalMessage("error", error.message || "确认焦点交互失败")
    return false
  }

  async function cancel(id: string): Promise<boolean> {
    const [, error] = await tryCatch(() => cancelFocusInteraction(id))
    if (!error) {
      removeById(id)
      return true
    }
    // 同上：仅 404/409 视为后端已结束；其余失败保留仍 pending 项，不能复活
    // 已被 finished 移除的 modal。
    if (error instanceof FocusInteractionError && [404, 409].includes(error.httpStatus ?? 0)) {
      removeById(id)
      return false
    }
    // 非终态失败时保持当前 pending；不要用旧快照复活已由 SSE finished
    // 移除的 modal。
    showGlobalMessage("error", error.message || "取消焦点交互失败")
    return false
  }

  return {
    pending,
    hydrated,
    upsert,
    removeById,
    applyRealtime,
    hydrate,
    acknowledge,
    cancel,
  }
})
