import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"
import type { FocusInteractionPayload } from "@/services/api/modules/focus"
import type { GlobalMessageType } from "@/services/feedback/message"

vi.mock("@/services/api/modules/focus", () => {
  class FocusInteractionError extends Error {
    readonly httpStatus: number | null

    constructor(message: string, httpStatus: number | null) {
      super(message)
      this.httpStatus = httpStatus
    }
  }

  return {
    fetchFocusInteractions: vi.fn<() => Promise<FocusInteractionPayload[]>>(),
    acknowledgeFocusInteraction: vi.fn<(id: string) => Promise<void>>(),
    cancelFocusInteraction: vi.fn<(id: string) => Promise<void>>(),
    FocusInteractionError,
  }
})

vi.mock("@/services/feedback/message", () => ({
  showGlobalDialog: vi.fn<(type: GlobalMessageType, content: string, title?: string) => void>(),
  showGlobalMessage: vi.fn<(type: GlobalMessageType, content: string) => void>(),
}))

import { acknowledgeFocusInteraction, cancelFocusInteraction } from "@/services/api/modules/focus"
import { showGlobalDialog, showGlobalMessage } from "@/services/feedback/message"
import { useFocusInteractionStore } from "@/stores/focus/focusInteraction"

describe("useFocusInteractionStore realtime focus events", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(showGlobalDialog).mockClear()
    vi.mocked(showGlobalMessage).mockClear()
    vi.mocked(acknowledgeFocusInteraction).mockReset()
    vi.mocked(cancelFocusInteraction).mockReset()
  })

  it("shows a created dialog once without adding it to modal pending", () => {
    const store = useFocusInteractionStore()
    const payload = {
      id: "dialog-1",
      run_id: "run-1",
      mode: "dialog",
      phase: "created",
      state: "pending",
      content: "A non-blocking notice",
      title: "Task interaction",
      level: "info",
    }

    store.applyRealtime(payload)
    store.applyRealtime({ ...payload, phase: "finished", state: "acknowledged" })

    expect(showGlobalDialog).toHaveBeenCalledTimes(1)
    expect(showGlobalDialog).toHaveBeenCalledWith(
      "info",
      "A non-blocking notice",
      "Task interaction",
    )
    expect(store.pending).toEqual([])
  })

  it("keeps created modal content in the pending interaction", () => {
    const store = useFocusInteractionStore()

    store.applyRealtime({
      id: "modal-1",
      run_id: "run-1",
      mode: "modal",
      phase: "created",
      state: "pending",
      content: "Continue?",
    })

    expect(store.pending).toHaveLength(1)
    expect(store.pending[0]).toMatchObject({
      id: "modal-1",
      mode: "modal",
      content: "Continue?",
    })
  })

  it("does not resurrect a modal finished by SSE when ack or cancel fails", async () => {
    const store = useFocusInteractionStore()

    let rejectAcknowledge!: (reason?: unknown) => void
    vi.mocked(acknowledgeFocusInteraction).mockImplementationOnce(
      () => new Promise<void>((_, reject) => (rejectAcknowledge = reject)),
    )
    store.applyRealtime({
      id: "modal-ack",
      run_id: "run-1",
      mode: "modal",
      phase: "created",
      state: "pending",
      content: "Ack me",
    })
    const acknowledgeRequest = store.acknowledge("modal-ack")

    // The SSE finished event can win while the HTTP request is in flight.
    store.applyRealtime({
      id: "modal-ack",
      run_id: "run-1",
      mode: "modal",
      phase: "finished",
      state: "acknowledged",
      content: "Ack me",
    })
    rejectAcknowledge(new Error("ack network failure"))
    expect(await acknowledgeRequest).toBe(false)
    expect(store.pending).toEqual([])

    let rejectCancel!: (reason?: unknown) => void
    vi.mocked(cancelFocusInteraction).mockImplementationOnce(
      () => new Promise<void>((_, reject) => (rejectCancel = reject)),
    )
    store.applyRealtime({
      id: "modal-cancel",
      run_id: "run-1",
      mode: "modal",
      phase: "created",
      state: "pending",
      content: "Cancel me",
    })
    const cancelRequest = store.cancel("modal-cancel")
    store.applyRealtime({
      id: "modal-cancel",
      run_id: "run-1",
      mode: "modal",
      phase: "finished",
      state: "cancelled",
      content: "Cancel me",
    })
    rejectCancel(new Error("cancel network failure"))

    expect(await cancelRequest).toBe(false)
    expect(store.pending).toEqual([])
    expect(showGlobalMessage).toHaveBeenCalledTimes(2)
  })
})
