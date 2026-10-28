import type { RealtimeEvent, RealtimeEventName } from "@/types/realtimeModel"
import type { useIndexStore } from "@/stores/panel/session"
import type { useSettingsStore } from "@/stores/settings/settings"
import type { useFocusStore } from "@/stores/focus/focus"
import { formatRealtimeLog, showBrowserRealtimeNotification, showToastMessage } from "./events"

export interface RealtimeStoreRefs {
  indexStore: ReturnType<typeof useIndexStore>
  settingsStore: ReturnType<typeof useSettingsStore>
  focusStore: ReturnType<typeof useFocusStore>
}

/**
 * Common handling for every SSE event:
 * 1. Append to the running log panel (if display=true)
 * 2. Show an in-app toast (if notify includes "toast")
 * 3. Show a browser Notification (if notify includes "notification")
 *
 * Toast and browser notification are independent channels — never both
 * from a single unconditional path (that used to duplicate toasts).
 */
function handleCommon(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  if (event.display) {
    stores.indexStore.UpdateLog(formatRealtimeLog(event))
  }
  if (event.notify.includes("toast")) {
    showToastMessage(event)
  }
  if (event.notify.includes("notification")) {
    showBrowserRealtimeNotification(event, stores.settingsStore.settings.notification)
  }
}

function handleFocusDisplay(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  handleCommon(event, stores)
  if (event.notify.includes("dialog")) {
    stores.focusStore.enqueueDialog(event.message, event.level)
  }
}

/** Task batch started — set running state so the UI can react. */
function handleTaskStarted(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  handleCommon(event, stores)
  stores.indexStore.setTaskRunning(true)
}

/** Task batch completed — clear running state. */
function handleTaskCompleted(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  handleCommon(event, stores)
  stores.indexStore.setTaskRunning(false)
}

/** Task batch failed — clear running state. */
function handleTaskFailed(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  handleCommon(event, stores)
  stores.indexStore.setTaskRunning(false)
}

/**
 * Per-event-type handlers. Events not listed here fall through to
 * handleCommon (log + notify channels only).
 *
 * Modal snapshots are handled separately and never enter common handling.
 */
const typeHandlers: Partial<
  Record<RealtimeEventName, (event: RealtimeEvent, stores: RealtimeStoreRefs) => void>
> = {
  "focus.display": handleFocusDisplay,
  "task.started": handleTaskStarted,
  "task.completed": handleTaskCompleted,
  "task.failed": handleTaskFailed,
}

/**
 * Unified SSE event dispatcher. Routes incoming RealtimeEvents by type,
 * applying common handling (log + notify channels) plus type-specific
 * side effects (e.g. task lifecycle → store state updates).
 */
export function dispatchRealtimeEvent(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  if (event.event === "focus.modal") {
    stores.focusStore.replaceModals(event.focus_modals ?? [])
    return
  }
  const handler = typeHandlers[event.event]
  if (handler) {
    handler(event, stores)
    return
  }
  handleCommon(event, stores)
}
