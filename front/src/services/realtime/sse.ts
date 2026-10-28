import type { RealtimeEvent, RealtimeEventName } from "@/types/realtimeModel"
import { tryCatch } from "@/utils/tryCatch"

/** `EventSource.CLOSED`: the browser has given up reconnecting on its own. */
const EVENT_SOURCE_CLOSED = 2
const REOPEN_DELAY_MS = 5000

/**
 * 后端由 pydantic `RealtimeEvent` 保证字段完整，这里只校验身份字段，
 * 其余字段按契约断言。
 */
function isRealtimeEvent(value: unknown): value is RealtimeEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    "event" in value &&
    typeof value.event === "string" &&
    "message" in value &&
    typeof value.message === "string"
  )
}

export class SSEClient {
  private eventSource: EventSource | null = null
  private url: string
  private listeners: Map<string, Set<(data: RealtimeEvent) => void>> = new Map()
  private reopenTimer: ReturnType<typeof setTimeout> | null = null
  private isManuallyClosed: boolean = false

  constructor(url: string) {
    this.url = url
    this.connect()
  }

  private connect(): void {
    if (this.isManuallyClosed) return

    this.clearReopenTimer()
    this.eventSource?.close()
    this.eventSource = new EventSource(this.url)

    this.eventSource.onmessage = (event) => {
      const [parsed, parseErr] = tryCatch(() => JSON.parse(event.data))
      if (parseErr) {
        console.error("SSE消息解析错误:", parseErr)
        return
      }
      if (!isRealtimeEvent(parsed)) {
        return
      }
      this.dispatchEvent(parsed.event, parsed)
    }

    this.eventSource.onerror = (error) => {
      console.error("SSE连接错误:", error)
      // EventSource 自带重连；只有浏览器彻底放弃（CLOSED）时才手动重开一次。
      if (this.eventSource?.readyState !== EVENT_SOURCE_CLOSED) return
      this.scheduleReopen()
    }
  }

  private scheduleReopen(): void {
    if (this.isManuallyClosed || this.reopenTimer) return

    this.reopenTimer = setTimeout(() => {
      this.reopenTimer = null
      this.connect()
    }, REOPEN_DELAY_MS)
  }

  private clearReopenTimer(): void {
    if (!this.reopenTimer) return
    clearTimeout(this.reopenTimer)
    this.reopenTimer = null
  }

  public addEventListener(type: RealtimeEventName, callback: (data: RealtimeEvent) => void): void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set())
    }
    this.listeners.get(type)?.add(callback)
  }

  public removeEventListener(
    type: RealtimeEventName,
    callback: (data: RealtimeEvent) => void,
  ): void {
    this.listeners.get(type)?.delete(callback)
  }

  private dispatchEvent(type: RealtimeEventName, data: RealtimeEvent): void {
    this.listeners.get(type)?.forEach((callback) => callback(data))
  }

  public close(): void {
    this.isManuallyClosed = true
    this.clearReopenTimer()
    this.eventSource?.close()
    this.eventSource = null
  }
}

export const sse = new SSEClient("/api/logs")
