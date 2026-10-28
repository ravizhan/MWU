import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// setup.ts already stubs a global EventSource class; sse.ts instantiates it at
// module scope, so importing the module is safe.
import { SSEClient } from "@/services/realtime/sse"
import type { FocusModal, RealtimeEvent } from "@/types/realtimeModel"

const EVENT_SOURCE_CLOSED = 2

interface MockEventSourceInstance {
  close: ReturnType<typeof vi.fn>
  onopen: (() => void) | null
  onmessage: ((event: { data: string }) => void) | null
  onerror: ((event: unknown) => void) | null
  readyState: number
  url: string
}

describe("SSEClient", () => {
  let mockEventSourceCtor: ReturnType<typeof vi.fn>

  function getESInstance(index = 0): MockEventSourceInstance {
    const instance: MockEventSourceInstance | undefined =
      mockEventSourceCtor.mock.results[index]?.value
    if (!instance) {
      throw new Error(`No EventSource instance at index ${index}`)
    }
    return instance
  }

  beforeEach(() => {
    vi.useFakeTimers()
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    mockEventSourceCtor = vi.mocked(globalThis.EventSource as unknown as ReturnType<typeof vi.fn>)
    mockEventSourceCtor.mockClear()
    vi.spyOn(console, "error").mockImplementation(() => {})
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

    it("leaves reconnection to the browser while the stream is still live", () => {
      const client = new SSEClient("/api/logs")
      const instance = getESInstance()

      instance.onerror?.(new Event("error"))
      vi.advanceTimersByTime(60_000)

      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)
      client.close()
    })

    it("reopens once when the browser gives up", () => {
      const client = new SSEClient("/api/logs")
      const instance = getESInstance()
      instance.readyState = EVENT_SOURCE_CLOSED

      instance.onerror?.(new Event("error"))
      vi.advanceTimersByTime(5000)

      expect(mockEventSourceCtor).toHaveBeenCalledTimes(2)
      client.close()
    })

    it("does not reopen after close()", () => {
      const client = new SSEClient("/api/logs")
      const instance = getESInstance()
      instance.readyState = EVENT_SOURCE_CLOSED

      instance.onerror?.(new Event("error"))
      client.close()
      vi.advanceTimersByTime(60_000)

      expect(mockEventSourceCtor).toHaveBeenCalledTimes(1)
    })
  })

  describe("event dispatching", () => {
    it("keeps empty-message modal snapshots", () => {
      const client = new SSEClient("/api/logs")
      let modals: FocusModal[] | null | undefined = null
      client.addEventListener("focus.modal", (event: RealtimeEvent) => {
        modals = event.focus_modals
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

    it("dispatches events to registered listeners", () => {
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
          display: true,
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

    it("ignores payloads without an event name or message", () => {
      const client = new SSEClient("/api/logs")
      const listener = vi.fn<() => void>()
      client.addEventListener("log", listener)

      const instance = getESInstance()
      instance.onmessage?.({ data: JSON.stringify({ message: "no event name" }) })
      instance.onmessage?.({ data: JSON.stringify({ event: "log" }) })
      instance.onmessage?.({ data: JSON.stringify("plain string") })

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
          display: true,
        }),
      })

      expect(listener).not.toHaveBeenCalled()
      client.close()
    })
  })
})
