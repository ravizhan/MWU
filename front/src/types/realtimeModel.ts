export type RealtimeEventName =
  | "log"
  | "focus.display"
  | "focus.interaction"
  | "task.started"
  | "task.completed"
  | "task.failed"
  | "notification.test"

export type RealtimeEventLevel = "info" | "success" | "error"

export interface RealtimeEvent {
  event: RealtimeEventName
  level: RealtimeEventLevel
  message: string
  time: string
  notify: string[]
  title?: string | null
  details?: Record<string, unknown> | null
  display: boolean
}
