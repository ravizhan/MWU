import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"
import { confirmFocusModal, stopTask } from "@/services/api"
import { useFocusStore } from "./focus"
import type { FocusModal } from "@/types/realtimeModel"

vi.mock("@/services/api", () => ({
  confirmFocusModal: vi.fn<(id: string) => Promise<boolean>>(),
  stopTask: vi.fn<() => Promise<boolean>>(),
}))

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => undefined
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve
  })
  return { promise, resolve: resolvePromise }
}

const modalA: FocusModal = { id: "A", message: "First gate", level: "info" }
const modalB: FocusModal = { id: "B", message: "Second gate", level: "error" }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe("focus queues", () => {
  it("keeps independent identical dialogs in FIFO order across modal preemption", () => {
    const store = useFocusStore()
    store.enqueueDialog("Message", "info")
    store.enqueueDialog("Message", "info")
    const first = store.active
    expect(first).toEqual({ kind: "dialog", id: 0, message: "Message", level: "info" })

    store.replaceModals([modalA, modalB])
    store.replaceModals([modalA, modalB])
    expect(store.modals).toEqual([modalA, modalB])
    expect(store.active).toEqual({ kind: "modal", ...modalA })
    store.replaceModals([modalB])
    expect(store.active).toEqual({ kind: "modal", ...modalB })
    store.replaceModals([])
    expect(store.active).toEqual(first)
    store.dismissDialog(0)
    expect(store.active).toEqual({ kind: "dialog", id: 1, message: "Message", level: "info" })
    store.dismissDialog(0)
    expect(store.active?.id).toBe(1)
    store.dismissDialog(1)
    expect(store.active).toBeNull()
    expect(confirmFocusModal).not.toHaveBeenCalled()
  })

  const cases = [true, false].flatMap((success) =>
    ["same", "duplicate", "next", "empty"].map((snapshot) => ({ success, snapshot })),
  )
  it.each(cases)(
    "preserves server state after $snapshot snapshots while confirmation resolves $success",
    async ({ success, snapshot }) => {
      const store = useFocusStore()
      store.enqueueDialog("Retained dialog", "success")
      const dialog = store.active
      store.replaceModals([modalA])
      const request = deferred<boolean>()
      vi.mocked(confirmFocusModal).mockReturnValueOnce(request.promise)
      const confirming = store.confirmModal(modalA.id)
      expect(store.busy).toBe(true)

      store.replaceModals([modalA])
      if (snapshot !== "same") store.replaceModals([modalA])
      if (snapshot === "next") store.replaceModals([modalB])
      if (snapshot === "empty") store.replaceModals([])
      const expected =
        snapshot === "empty"
          ? dialog
          : { kind: "modal", ...(snapshot === "next" ? modalB : modalA) }
      expect(store.busy).toBe(true)
      request.resolve(success)
      await expect(confirming).resolves.toBe(success)
      expect(store.busy).toBe(false)
      expect(store.active).toEqual(expected)
      expect(store.dialogs).toEqual([{ id: 0, message: "Retained dialog", level: "success" }])
    },
  )

  it("keeps the modal after a failed stop and busy until the request finishes", async () => {
    const store = useFocusStore()
    store.replaceModals([modalA])
    const request = deferred<boolean>()
    vi.mocked(stopTask).mockReturnValueOnce(request.promise)
    const stopping = store.stopTaskFromModal()
    store.replaceModals([modalA])
    expect(store.busy).toBe(true)
    request.resolve(false)
    await expect(stopping).resolves.toBe(false)
    expect(store.busy).toBe(false)
    expect(store.active).toEqual({ kind: "modal", ...modalA })
  })

  it("does not restore a stopped modal after an empty server snapshot", async () => {
    const store = useFocusStore()
    store.replaceModals([modalA])
    const request = deferred<boolean>()
    vi.mocked(stopTask).mockReturnValueOnce(request.promise)
    const stopping = store.stopTaskFromModal()
    store.replaceModals([])
    expect(store.active).toBeNull()
    expect(store.busy).toBe(true)
    request.resolve(true)
    await stopping
    expect(store.active).toBeNull()
    expect(store.busy).toBe(false)
  })
})
