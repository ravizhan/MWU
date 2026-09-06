import { defineStore } from "pinia"
import { ref } from "vue"
import {
  fetchFocusInteractions,
  acknowledgeFocusInteraction,
  cancelFocusInteraction,
} from "@/services/api/modules/focus"
import type { FocusInteractionPayload } from "@/services/api/modules/focus"

/** 后端 focus 交互（dialog / modal）的前端状态（API 契约别名）。 */
export type FocusInteraction = FocusInteractionPayload

/** store 公开契约（供 dispatcher 等消费方引用，避免 ReturnType 推导）。 */
export interface FocusInteractionStoreContract {
  pending: FocusInteraction[]
  hydrated: boolean
  upsert: (interaction: FocusInteraction) => void
  removeById: (id: string) => void
  applyRealtime: (payload: {
    id?: unknown
    mode?: unknown
    state?: unknown
    run_id?: unknown
    phase?: unknown
  }) => void
  hydrate: () => Promise<void>
  acknowledge: (id: string) => Promise<void>
  cancel: (id: string) => Promise<void>
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
    if (interaction.state !== "pending") {
      removeById(interaction.id)
      return
    }
    const existing = pending.value.find((item) => item.id === interaction.id)
    if (existing) {
      Object.assign(existing, interaction)
    } else {
      pending.value.push(interaction)
    }
  }

  function removeById(id: string): void {
    const index = pending.value.findIndex((item) => item.id === id)
    if (index >= 0) {
      pending.value.splice(index, 1)
    }
  }

  /** SSE focus.interaction（details.phase = created | finished）。 */
  function applyRealtime(payload: {
    id?: unknown
    mode?: unknown
    state?: unknown
    run_id?: unknown
    phase?: unknown
  }): void {
    const id = typeof payload.id === "string" ? payload.id : ""
    if (!id) {
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
      mode: payload.mode === "dialog" ? "dialog" : "modal",
      state,
      content: "",
      created_at: Date.now(),
    })
  }

  /** 打开页面时拉取后端 pending 项（SSE 之前的漏网）。 */
  async function hydrate(): Promise<void> {
    if (hydrated.value) {
      return
    }
    hydrated.value = true
    try {
      const remote = await fetchFocusInteractions()
      for (const item of remote) {
        upsert(item)
      }
    } catch {
      // 拉取失败不阻塞；SSE 仍会补
    }
  }

  async function acknowledge(id: string): Promise<void> {
    removeById(id)
    try {
      await acknowledgeFocusInteraction(id)
    } catch {
      // 409/404 均意味着后端已结束；本地移除即可
    }
  }

  async function cancel(id: string): Promise<void> {
    removeById(id)
    try {
      await cancelFocusInteraction(id)
    } catch {
      // 同上
    }
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
