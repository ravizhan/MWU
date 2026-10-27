export type RealtimeEventName =
  | "log"
  | "focus.display"
  | "focus.modal"
  | "task.started"
  | "task.completed"
  | "task.failed"
  | "notification.test"

export type RealtimeEventLevel = "info" | "success" | "error"

export interface FocusModal {
  id: string
  message: string
  level: RealtimeEventLevel
}

interface RealtimeEventFields {
  level: RealtimeEventLevel
  message: string
  time: string
  notify: string[]
  title?: string | null
  details?: Record<string, unknown> | null
  display: boolean
}

export type RealtimeEvent = RealtimeEventFields &
  (
    | { event: Exclude<RealtimeEventName, "focus.modal"> }
    | { event: "focus.modal"; focus_modals: FocusModal[] }
  )
