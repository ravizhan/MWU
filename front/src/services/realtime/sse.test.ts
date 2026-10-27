import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// Since setup.ts already provides a global EventSource mock,
// we can import the module safely
import { SSEClient } from "@/services/realtime/sse"
import type { FocusModal, RealtimeEvent } from "@/types/realtimeModel"

describe("SSEClient", () => {
  let mockEventSourceCtor: ReturnType<typeof vi.fn>

  function getESInstance(index = 0) {
    const instance = mockEventSourceCtor.mock.results[index]?.value
    if (!instance) {
      throw new Error(`No EventSource instance at index ${index}`)
    }
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    return instance as {
      close: ReturnType<typeof vi.fn>
      onopen: (() => void) | null
      onmessage: ((event: { data: string }) => void) | null
      onerror: ((event: unknown) => void) | null
    }
  }

  beforeEach(() => {
    vi.useFakeTimers()
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    mockEventSourceCtor = vi.mocked(globalThis.EventSource as unknown as ReturnType<typeof vi.fn>)
    mockEventSourceCtor.mockClear()
    // Suppress console output from sse.ts error/reconnect paths exercised below.
    // Tests that assert on console.error re-spy on top of this stub.
    vi.spyOn(console, "error").mockImplementation(() => {})
    vi.spyOn(console, "log").mockImplementation(() => {})
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe("connection lifecycle", () => {
    it("connects on construction", () => {
      const client = new SSEClient("/api/logs")
      expect(mockEventSourceCtor).toHaveBeenCalledWith("/api/logs")
      client.close()
    })

    it("closes the EventSource on close()", () => {
      const client = new SSEClient("/api/logs")
      const instance = getESInstance()
      client.close()
      expect(instance.close).toHaveBeenCalled()
    })

    it("does not reconnect when manually closed", () => {
      const client = new SSEClient("/api/logs")
      client.close()

      const instance = getESInstance()
      instance.onerror?.(new Event("error"))

      vi.advanceTimersByTime(5000)

      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)
    })

    it("reconnect re-establishes connection", () => {
      const client = new SSEClient("/api/logs")
      client.close()

      mockEventSourceCtor.mockClear()

      client.reconnect()

      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)
      client.close()
    })

    it("close() after error clears pending reconnect timer", () => {
      const client = new SSEClient("/api/logs")

      const instance = getESInstance()
      instance.onerror?.(new Event("error"))

      client.close()

      // Advance time past the reconnect window
      vi.advanceTimersByTime(5000)

      // Should not have reconnected because close() cleared the timer
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)
    })
  })

  describe("event dispatching", () => {
    it("accepts empty-message modal snapshots including the empty state", () => {
      const client = new SSEClient("/api/logs")
      let modals: FocusModal[] = []
      client.addEventListener("focus.modal", (event: RealtimeEvent) => {
        if (event.event === "focus.modal") modals = event.focus_modals
      })
      const instance = getESInstance()
      const modal: FocusModal = { id: "gate", message: "Confirm", level: "info" }
      instance.onmessage?.({
        data: JSON.stringify({ event: "focus.modal", message: "", focus_modals: [modal] }),
      })
      expect(modals).toEqual([modal])
      instance.onmessage?.({
        data: JSON.stringify({ event: "focus.modal", message: "", focus_modals: [] }),
      })
      expect(modals).toEqual([])
      client.close()
    })

    it.each([
      undefined,
      null,
      {},
      [null],
      [{ id: 1, message: "Confirm", level: "info" }],
      [{ id: "gate", message: null, level: "info" }],
      [{ id: "gate", message: "Confirm", level: "warning" }],
    ])("does not clear modal state on malformed snapshot %j", (focus_modals) => {
      const client = new SSEClient("/api/logs")
      const modal: FocusModal = { id: "gate", message: "Confirm", level: "info" }
      let modals: FocusModal[] = []
      client.addEventListener("focus.modal", (event: RealtimeEvent) => {
        if (event.event === "focus.modal") modals = event.focus_modals
      })
      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({ event: "focus.modal", message: "", focus_modals: [modal] }),
      })
      instance.onmessage?.({
        data: JSON.stringify({ event: "focus.modal", message: "", focus_modals }),
      })
      expect(modals).toEqual([modal])
      client.close()
    })

    it("dispatches normalized events to registered listeners", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          event: "log",
          level: "info",
          message: "hello world",
          time: "2024-01-01T00:00:00Z",
          notify: [],
        }),
      })

      expect(listener).toHaveBeenCalledTimes(1)
      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          event: "log",
          level: "info",
          message: "hello world",
        }),
      )
      client.close()
    })

    it("ignores invalid JSON messages and logs to console.error", () => {
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {})
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({ data: "not valid json" })

      expect(listener).not.toHaveBeenCalled()
      expect(consoleSpy).toHaveBeenCalledWith("SSE消息解析错误:", expect.any(SyntaxError))
      consoleSpy.mockRestore()
      client.close()
    })

    it("ignores messages without message field", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({ event: "log" }),
      })

      expect(listener).not.toHaveBeenCalled()
      client.close()
    })

    it("adds and removes event listeners", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("task.started", listener)
      client.removeEventListener("task.started", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          event: "task.started",
          level: "info",
          message: "task running",
          time: "",
          notify: [],
        }),
      })

      expect(listener).not.toHaveBeenCalled()
      client.close()
    })

    it("ignores legacy type when event is absent", () => {
      const client = new SSEClient("/api/logs")
      const customListener = vi.fn<() => void>()
      const logListener = vi.fn<() => void>()
      client.addEventListener("custom", customListener)
      client.addEventListener("log", logListener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          type: "custom",
          level: "success",
          message: "legacy format",
          time: "2024-01-01T00:00:00Z",
        }),
      })

      expect(customListener).not.toHaveBeenCalled()
      expect(logListener).toHaveBeenCalledWith(
        expect.objectContaining({
          event: "log",
          level: "success",
          message: "legacy format",
        }),
      )
      client.close()
    })

    it("fills in missing fields with defaults", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          message: "bare message",
        }),
      })

      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          event: "log",
          level: "info",
          message: "bare message",
          time: "",
          notify: [],
          display: true,
        }),
      )
      client.close()
    })

    it("preserves display: false through normalization", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          level: "info",
          message: "hidden log",
          display: false,
        }),
      })

      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          display: false,
        }),
      )
      client.close()
    })

    it("normalizes title and details fields", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          level: "info",
          message: "with details",
          title: "Notification Title",
          details: { key: "value", count: 42 },
        }),
      })

      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Notification Title",
          details: { key: "value", count: 42 },
        }),
      )
      client.close()
    })

    it("sets title to null and details to null when absent", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({
        data: JSON.stringify({
          level: "info",
          message: "no extras",
        }),
      })

      expect(listener).toHaveBeenCalledWith(
        expect.objectContaining({
          title: null,
          details: null,
        }),
      )
      client.close()
    })
  })

  describe("reconnect behavior", () => {
    it("schedules reconnect on error", () => {
      const client = new SSEClient("/api/logs")
      const initialCallCount = mockEventSourceCtor.mock.calls.length

      const instance = getESInstance()
      instance.onerror?.(new Event("error"))

      vi.advanceTimersByTime(1500)

      expect(mockEventSourceCtor.mock.calls.length).toBeGreaterThanOrEqual(initialCallCount + 1)
      client.close()
    })

    it("increases reconnect delay exponentially", () => {
      vi.spyOn(Math, "random").mockReturnValue(0)

      const client = new SSEClient("/api/logs")

      // First error: baseDelay = 1000 * 2^0 = 1000, with jitter=0 → delay=1000
      const instance1 = getESInstance(0)
      instance1.onerror?.(new Event("error"))

      // At t=500ms, reconnect should NOT have happened yet
      vi.advanceTimersByTime(500)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)

      // At t=1000ms, first reconnect fires
      vi.advanceTimersByTime(500)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(2)

      // Second error: baseDelay = 1000 * 2^1 = 2000
      const instance2 = getESInstance(1)
      instance2.onerror?.(new Event("error"))

      // At t=1500ms (1000 + 500), reconnect should NOT have happened yet
      // (2000ms delay from second error)
      vi.advanceTimersByTime(1000)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(2)

      // At t=3500ms (1000 + 2500), second reconnect should have fired
      vi.advanceTimersByTime(2000)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(3)

      vi.spyOn(Math, "random").mockRestore()
      client.close()
    })

    it("onopen resets reconnect attempts (delay returns to base)", () => {
      vi.spyOn(Math, "random").mockReturnValue(0)

      const client = new SSEClient("/api/logs")
      const instance1 = getESInstance(0)

      // First error → attempt #1 fires at t=1000
      instance1.onerror?.(new Event("error"))
      vi.advanceTimersByTime(1000)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(2)

      // Simulate a successful reconnection (onopen fires)
      const instance2 = getESInstance(1)
      instance2.onopen?.()

      // Now trigger another error → should be back to base delay of 1000
      instance2.onerror?.(new Event("error"))
      vi.advanceTimersByTime(500)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(2)

      vi.advanceTimersByTime(500)
      // Third connection should have happened at base delay (1000ms)
      expect(mockEventSourceCtor).toHaveBeenCalledTimes(3)

      vi.spyOn(Math, "random").mockRestore()
      client.close()
    })
  })
})
