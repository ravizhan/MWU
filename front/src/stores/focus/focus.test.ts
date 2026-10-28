import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"
import { useFocusStore } from "./focus"
import type { FocusModal } from "@/types/realtimeModel"

vi.mock("@/services/api", () => ({
  confirmFocusModal: vi.fn<(id: string) => Promise<boolean>>(),
  stopTask: vi.fn<() => Promise<boolean>>(),
}))

const modalA: FocusModal = { id: "A", message: "First gate", level: "info" }
const modalB: FocusModal = { id: "B", message: "Second gate", level: "error" }

beforeEach(() => {
  setActivePinia(createPinia())
})

describe("focus store", () => {
  it("shows modals before dialogs and dialogs in FIFO order", () => {
    const store = useFocusStore()
    store.enqueueDialog("Message", "info")
    store.enqueueDialog("Message", "info")
    const first = store.active
    expect(first).toEqual({ kind: "dialog", id: 0, message: "Message", level: "info" })

    store.replaceModals([modalA, modalB])
    expect(store.active).toEqual({ kind: "modal", ...modalA })
    store.replaceModals([modalB])
    expect(store.active).toEqual({ kind: "modal", ...modalB })
    store.replaceModals([])
    expect(store.active).toEqual(first)

    store.dismissDialog(0)
    expect(store.active).toEqual({ kind: "dialog", id: 1, message: "Message", level: "info" })
    store.dismissDialog(1)
    expect(store.active).toBeNull()
  })
})
