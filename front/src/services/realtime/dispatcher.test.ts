import { describe, expect, it, vi, beforeEach } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import type { RealtimeEvent } from "@/types/realtimeModel"
import { dispatchRealtimeEvent, type RealtimeStoreRefs } from "@/services/realtime/dispatcher"
import { useIndexStore } from "@/stores/panel/session"
import { useSettingsStore } from "@/stores/settings/settings"
import { useFocusStore } from "@/stores/focus/focus"

vi.mock("@/services/feedback/message", () => ({
  showGlobalMessage: vi.fn<() => void>(),
}))

vi.mock("@/services/realtime/events", () => ({
  formatRealtimeLog: vi.fn<(e: RealtimeEvent) => string>(
    (e: RealtimeEvent) => `${e.time} ${e.message}`,
  ),
  showToastMessage: vi.fn<() => void>(),
  showBrowserRealtimeNotification: vi.fn<() => void>(),
}))

import { showToastMessage, showBrowserRealtimeNotification } from "@/services/realtime/events"

const baseEvent: RealtimeEvent = {
  event: "log",
  level: "info",
  message: "hello",
  time: "2024-01-01T00:00:00Z",
  notify: [],
  display: true,
}

function makeStores() {
  return {
    indexStore: useIndexStore(),
    settingsStore: useSettingsStore(),
    focusStore: useFocusStore(),
  } satisfies RealtimeStoreRefs
}

describe("dispatchRealtimeEvent", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(showToastMessage).mockClear()
    vi.mocked(showBrowserRealtimeNotification).mockClear()
  })

  describe("common handling (all event types)", () => {
    it("appends to log when display=true", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent }, stores)
      expect(stores.indexStore.RunningLog).toContain("hello")
    })

    it("does not append to log when display=false", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, display: false }, stores)
      expect(stores.indexStore.RunningLog).toBe("")
    })

    it("shows toast when notify includes 'toast'", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, notify: ["toast"] }, stores)
      expect(showToastMessage).toHaveBeenCalledTimes(1)
    })

    it("does not show toast when notify is empty", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, notify: [] }, stores)
      expect(showToastMessage).not.toHaveBeenCalled()
    })

    it("shows browser notification when notify includes 'notification'", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, notify: ["notification"] }, stores)
      expect(showBrowserRealtimeNotification).toHaveBeenCalledTimes(1)
    })

    it("does not show browser notification when notify is empty", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, notify: [] }, stores)
      expect(showBrowserRealtimeNotification).not.toHaveBeenCalled()
    })

    it("handles both toast and notification channels once each", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, notify: ["toast", "notification"] }, stores)
      expect(showToastMessage).toHaveBeenCalledTimes(1)
      expect(showBrowserRealtimeNotification).toHaveBeenCalledTimes(1)
    })
  })

  describe("task lifecycle dispatch", () => {
    it("sets TaskRunning=true on task.started", () => {
      const stores = makeStores()
      expect(stores.indexStore.TaskRunning).toBe(false)
      dispatchRealtimeEvent({ ...baseEvent, event: "task.started" }, stores)
      expect(stores.indexStore.TaskRunning).toBe(true)
    })

    it("sets TaskRunning=false on task.completed", () => {
      const stores = makeStores()
      stores.indexStore.setTaskRunning(true)
      dispatchRealtimeEvent({ ...baseEvent, event: "task.completed" }, stores)
      expect(stores.indexStore.TaskRunning).toBe(false)
    })

    it("sets TaskRunning=false on task.failed", () => {
      const stores = makeStores()
      stores.indexStore.setTaskRunning(true)
      dispatchRealtimeEvent({ ...baseEvent, event: "task.failed" }, stores)
      expect(stores.indexStore.TaskRunning).toBe(false)
    })

    it("still applies common handling for task lifecycle events", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, event: "task.started", notify: ["toast"] }, stores)
      expect(stores.indexStore.TaskRunning).toBe(true)
      expect(stores.indexStore.RunningLog).toContain("hello")
      expect(showToastMessage).toHaveBeenCalledTimes(1)
    })
  })

  describe("focus presentation", () => {
    it("replaces modal state without logging, notifying, or changing task state", () => {
      const stores = makeStores()
      stores.indexStore.setTaskRunning(true)
      const modal = { id: "gate", message: "Confirm", level: baseEvent.level }
      dispatchRealtimeEvent(
        { ...baseEvent, event: "focus.modal", message: "", display: false, focus_modals: [modal] },
        stores,
      )
      expect(stores.focusStore.active).toEqual({ kind: "modal", ...modal })
      expect(stores.indexStore.RunningLog).toBe("")
      expect(stores.indexStore.TaskRunning).toBe(true)
      expect(showToastMessage).not.toHaveBeenCalled()
      expect(showBrowserRealtimeNotification).not.toHaveBeenCalled()
      dispatchRealtimeEvent(
        { ...baseEvent, event: "focus.modal", message: "", display: false, focus_modals: [] },
        stores,
      )
      expect(stores.focusStore.active).toBeNull()
      expect(stores.indexStore.TaskRunning).toBe(true)
    })

    it.each([true, false])("queues dialog independently of log display=%s and toast", (display) => {
      const stores = makeStores()
      dispatchRealtimeEvent(
        { ...baseEvent, event: "focus.display", display, notify: ["dialog", "toast"] },
        stores,
      )
      expect(stores.focusStore.active).toMatchObject({ kind: "dialog", message: "hello" })
      expect(stores.indexStore.RunningLog).toBe(display ? `${baseEvent.time} hello\n` : "")
      expect(showToastMessage).toHaveBeenCalledTimes(1)
      expect(stores.indexStore.TaskRunning).toBe(false)
    })
  })

  describe("non-task event behavior", () => {
    it.each(["log", "focus.display", "notification.test"] as const)(
      "event '%s' does not change TaskRunning",
      (eventName) => {
        const stores = makeStores()
        dispatchRealtimeEvent({ ...baseEvent, event: eventName }, stores)
        expect(stores.indexStore.TaskRunning).toBe(false)
      },
    )

    it("focus.display still gets common handling (log + toast)", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, event: "focus.display", notify: ["toast"] }, stores)
      expect(stores.indexStore.RunningLog).toContain("hello")
      expect(showToastMessage).toHaveBeenCalledTimes(1)
      expect(stores.indexStore.TaskRunning).toBe(false)
    })
  })
})
