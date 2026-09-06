import type { RealtimeEvent, RealtimeEventName } from "@/types/realtimeModel"
import type { useIndexStore } from "@/stores/panel/session"
import type { useSettingsStore } from "@/stores/settings/settings"
import type { FocusInteractionStoreContract } from "@/stores/focus/focusInteraction"
import { formatRealtimeLog, showBrowserRealtimeNotification, showToastMessage } from "./events"

export interface RealtimeStoreRefs {
  indexStore: ReturnType<typeof useIndexStore>
  settingsStore: ReturnType<typeof useSettingsStore>
  focusInteractionStore?: FocusInteractionStoreContract
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

/** 焦点交互（dialog/modal）：details.phase=created → pending 入列；finished → 移除。 */
function handleFocusInteraction(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  if (!stores.focusInteractionStore || !event.details) {
    return
  }
  stores.focusInteractionStore.applyRealtime(event.details)
  // modal 内容在 details 里没有（message 才是内容），补齐最新一条 pending 的内容
  const store = stores.focusInteractionStore
  if (event.details.phase === "created" && store.pending.length > 0) {
    const latest = store.pending[store.pending.length - 1]
    if (!latest.content) {
      latest.content = event.message
    }
  }
}

/**
 * Per-event-type handlers. Events not listed here fall through to
 * handleCommon (log + notify channels only).
 *
 * Emitted RealtimeEventName values: log, focus.display, task.started,
 * task.completed, task.failed, notification.test.
 */
const typeHandlers: Partial<
  Record<RealtimeEventName, (event: RealtimeEvent, stores: RealtimeStoreRefs) => void>
> = {
  "task.started": handleTaskStarted,
  "task.completed": handleTaskCompleted,
  "task.failed": handleTaskFailed,
  "focus.interaction": handleFocusInteraction,
}

/**
 * Unified SSE event dispatcher. Routes incoming RealtimeEvents by type,
 * applying common handling (log + notify channels) plus type-specific
 * side effects (e.g. task lifecycle → store state updates).
 */
export function dispatchRealtimeEvent(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  const handler = typeHandlers[event.event]
  if (handler) {
    handler(event, stores)
    return
  }
  handleCommon(event, stores)
}
