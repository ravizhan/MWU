import type { RealtimeEvent, RealtimeEventName } from "@/types/realtimeModel"
import type { useIndexStore } from "@/stores/panel/session"
import type { useSettingsStore } from "@/stores/settings/settings"
import type { FocusInteractionRealtimePayload } from "@/stores/focus/focusInteraction"
import { formatRealtimeLog, showBrowserRealtimeNotification, showToastMessage } from "./events"

/** dispatcher 所需的 device store 最小契约。 */
export interface DeviceElevationContract {
  showElevationPrompt: boolean
  handleTaskStarted: (runId: string) => void
}

/**
 * dispatcher 所需的 focus 交互 store 最小契约：SSE focus.interaction 事件
 * 经本文件构造后调用 store.applyRealtime（详情字段按 realtimeModel 的
 * Record<string, unknown> 流入，由 store 内部收窄）。
 */
export interface FocusInteractionConsumer {
  applyRealtime: (payload: FocusInteractionRealtimePayload) => void
}

export interface RealtimeStoreRefs {
  indexStore: ReturnType<typeof useIndexStore>
  settingsStore: ReturnType<typeof useSettingsStore>
  deviceStore?: DeviceElevationContract
  focusInteractionStore?: FocusInteractionConsumer
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
  const runId = event.details?.run_id
  if (stores.deviceStore && typeof runId === "string" && runId.trim()) {
    stores.deviceStore.handleTaskStarted(runId)
  }
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
  // 权限检查在准入后的 _complete_run → prepare_connection 异步失败，只能经
  // task.failed 到达（/api/start 成功仅代表准入，永远不含 permission_required）。
  // 此处补出"以管理员权限重启"入口，否则用户看不到提权动作。
  if (event.message.includes("permission_required") && stores.deviceStore) {
    stores.deviceStore.showElevationPrompt = true
  }
}

/** 焦点交互（dialog/modal）：details.phase=created → pending 入列；finished → 移除。 */
function handleFocusInteraction(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  if (!stores.focusInteractionStore || !event.details) {
    return
  }
  const payload: FocusInteractionRealtimePayload = {
    ...event.details,
    content: event.message,
    title: event.title,
    level: event.level,
  }
  stores.focusInteractionStore.applyRealtime(payload)
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
