import { describe, expect, it, vi, beforeEach } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import type { RealtimeEvent } from "@/types/realtimeModel"
import { dispatchRealtimeEvent, type RealtimeStoreRefs } from "@/services/realtime/dispatcher"
import { useIndexStore } from "@/stores/panel/session"
import { useSettingsStore } from "@/stores/settings/settings"

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

function makeStores(): RealtimeStoreRefs {
  return {
    indexStore: useIndexStore(),
    settingsStore: useSettingsStore(),
  }
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
  })

  describe("double-notification bug fix", () => {
    it("does NOT duplicate toast for toast-only events", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, notify: ["toast"] }, stores)
      // showToastMessage is called exactly once — no duplicate
      expect(showToastMessage).toHaveBeenCalledTimes(1)
    })

    it("does NOT show toast for notification-only events", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, notify: ["notification"] }, stores)
      // Only browser notification, no extra toast
      expect(showToastMessage).not.toHaveBeenCalled()
      expect(showBrowserRealtimeNotification).toHaveBeenCalledTimes(1)
    })

    it("handles both toast and notification channels without duplication", () => {
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

    it("passes a non-empty started run id to the device store", () => {
      const handleTaskStarted = vi.fn<(runId: string) => void>()
      const stores = {
        ...makeStores(),
        deviceStore: { showElevationPrompt: false, handleTaskStarted },
      }

      dispatchRealtimeEvent(
        { ...baseEvent, event: "task.started", details: { run_id: "run-123" } },
        stores,
      )

      expect(handleTaskStarted).toHaveBeenCalledWith("run-123")
    })

    it.each([undefined, null, "", "   ", 123])(
      "does not persist a malformed started run id (%s)",
      (runId) => {
        const handleTaskStarted = vi.fn<(value: string) => void>()
        const stores = {
          ...makeStores(),
          deviceStore: { showElevationPrompt: false, handleTaskStarted },
        }

        dispatchRealtimeEvent(
          {
            ...baseEvent,
            event: "task.started",
            details: runId === undefined ? undefined : { run_id: runId },
          },
          stores,
        )

        expect(handleTaskStarted).not.toHaveBeenCalled()
      },
    )
  })

  describe("non-task events fall through to common handler", () => {
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
