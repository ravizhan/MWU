import type {
  FocusModal,
  RealtimeEvent,
  RealtimeEventLevel,
  RealtimeEventName,
} from "@/types/realtimeModel"
import { tryCatch } from "@/utils/tryCatch"

const VALID_EVENT_LEVELS: ReadonlySet<string> = new Set(["info", "success", "error"])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function isRealtimeEventName(value: unknown): value is RealtimeEventName {
  return typeof value === "string"
}

function isValidEventLevel(level: unknown): level is RealtimeEventLevel {
  return typeof level === "string" && VALID_EVENT_LEVELS.has(level)
}

function extractFocusModals(data: Record<string, unknown>): FocusModal[] | null {
  const value = data.focus_modals
  return Array.isArray(value) ? value : null
}

function extractString(data: unknown, key: string): string | undefined {
  if (!isRecord(data)) return undefined
  const value = data[key]
  return typeof value === "string" ? value : undefined
}

function extractStringArray(data: unknown, key: string): string[] {
  if (!isRecord(data)) return []
  const value = data[key]
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : []
}

function extractEventType(data: unknown): RealtimeEventName {
  if (!isRecord(data)) return "log"
  const raw = data.event
  return isRealtimeEventName(raw) ? raw : "log"
}

function extractLevel(data: unknown): RealtimeEventLevel {
  if (!isRecord(data)) return "info"
  const raw = "level" in data ? data.level : undefined
  return isValidEventLevel(raw) ? raw : "info"
}

function extractDetails(data: unknown): Record<string, unknown> | null {
  if (!isRecord(data)) return null
  const details = "details" in data ? data.details : null
  return isRecord(details) ? details : null
}

export class SSEClient {
  private eventSource: EventSource | null = null
  private url: string
  private listeners: Map<string, Set<(data: RealtimeEvent) => void>> = new Map()
  private baseReconnectInterval: number = 1000
  private maxReconnectInterval: number = 30000
  private reconnectAttempts: number = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private isManuallyClosed: boolean = false

  constructor(url: string) {
    this.url = url
    this.connect()
  }

  private connect(): void {
    if (this.isManuallyClosed) return

    this.clearReconnectTimer()
    this.eventSource?.close()
    this.eventSource = new EventSource(this.url)

    this.eventSource.onmessage = (event) => {
      const [parsed, parseErr] = tryCatch(() => JSON.parse(event.data))
      if (parseErr) {
        console.error("SSE消息解析错误:", parseErr)
        return
      }
      const data = this.normalizeEvent(parsed)
      if (!data) {
        return
      }
      this.dispatchEvent(data.event, data)
    }

    this.eventSource.onopen = () => {
      this.reconnectAttempts = 0
    }

    this.eventSource.onerror = (error) => {
      console.error("SSE连接错误:", error)
      this.eventSource?.close()
      this.eventSource = null
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.isManuallyClosed || this.reconnectTimer) return

    const exponentialDelay = Math.min(
      this.maxReconnectInterval,
      this.baseReconnectInterval * 2 ** this.reconnectAttempts,
    )
    const jitter = Math.floor(Math.random() * 500)
    const delay = exponentialDelay + jitter

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.reconnectAttempts++
      this.connect()
    }, delay)
  }

  private clearReconnectTimer(): void {
    if (!this.reconnectTimer) return
    clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
  }

  public addEventListener(type: string, callback: (data: RealtimeEvent) => void): void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set())
    }
    this.listeners.get(type)?.add(callback)
  }

  public removeEventListener(type: string, callback: (data: RealtimeEvent) => void): void {
    this.listeners.get(type)?.delete(callback)
  }

  private normalizeEvent(data: unknown): RealtimeEvent | null {
    if (!isRecord(data)) {
      return null
    }

    const event = extractEventType(data)
    const message = extractString(data, "message")
    // modal 快照的 message 恒为空串，靠 focus_modals 承载状态
    if (message === undefined || (!message && event !== "focus.modal")) {
      return null
    }

    return {
      event,
      level: extractLevel(data),
      message,
      time: extractString(data, "time") ?? "",
      notify: extractStringArray(data, "notify"),
      title: extractString(data, "title") ?? null,
      details: extractDetails(data),
      display: "display" in data ? Boolean(data.display) : true,
      focus_modals: extractFocusModals(data),
    }
  }

  private dispatchEvent(type: string, data: RealtimeEvent): void {
    this.listeners.get(type)?.forEach((callback) => callback(data))
  }

  public close(): void {
    this.isManuallyClosed = true
    this.clearReconnectTimer()
    this.eventSource?.close()
    this.eventSource = null
  }

  public reconnect(): void {
    this.isManuallyClosed = false
    this.reconnectAttempts = 0
    this.connect()
  }
}

export const sse = new SSEClient("/api/logs")
