export class SSEClient {
  private eventSource: EventSource | null = null
  private url: string
  private listeners: Map<string, Set<(data: any) => void>> = new Map()
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
      try {
        const data = JSON.parse(event.data)
        this.dispatchEvent(data.type, data)
      } catch (error) {
        console.error("SSE消息解析错误:", error)
      }
    }

    this.eventSource.onopen = () => {
      console.log("SSE连接成功")
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
      console.log(`SSE重连尝试 #${this.reconnectAttempts}，等待 ${delay}ms`)
      this.connect()
    }, delay)
  }

  private clearReconnectTimer(): void {
    if (!this.reconnectTimer) return
    clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
  }

  public addEventListener(type: string, callback: (data: any) => void): void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set())
    }
    this.listeners.get(type)?.add(callback)
  }

  public removeEventListener(type: string, callback: (data: any) => void): void {
    this.listeners.get(type)?.delete(callback)
  }

  private dispatchEvent(type: string, data: any): void {
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
