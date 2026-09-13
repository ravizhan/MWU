import type { MessageApiInjection } from "naive-ui/es/message/src/MessageProvider"
import type { DialogApiInjection } from "naive-ui/es/dialog/src/DialogProvider"

export type GlobalMessageType = "info" | "success" | "warning" | "error"

interface QueuedMessage {
  type: GlobalMessageType
  content: string
}

let messageApi: MessageApiInjection | null = null
let dialogApi: DialogApiInjection | null = null
let queue: QueuedMessage[] = []

/**
 * Registers the naive-ui message API. Called once by FeedbackBridge after mount.
 * Any messages queued before registration are flushed immediately.
 */
export function registerMessageApi(api: MessageApiInjection): void {
  messageApi = api
  const pending = queue
  queue = []
  for (const { type, content } of pending) {
    messageApi.create(content, { type, duration: 3000 })
  }
}

/** Registers the Naive UI dialog API used by non-blocking focus dialogs. */
export function registerDialogApi(api: DialogApiInjection): void {
  dialogApi = api
}

export function showGlobalMessage(type: GlobalMessageType, content: string): void {
  if (messageApi) {
    messageApi.create(content, { type, duration: 3000 })
    return
  }
  queue.push({ type, content })
}

/**
 * Displays a one-shot dialog through the existing NDialogProvider.
 *
 * Unlike messages, dialogs are deliberately not queued: a focus dialog is
 * an ephemeral realtime event and must not be replayed after the provider is
 * mounted.  The dialog is non-blocking for the backend; its positive button
 * only dismisses the UI and never acknowledges a focus interaction.
 */
export function showGlobalDialog(type: GlobalMessageType, content: string, title?: string): void {
  if (!dialogApi) {
    return
  }
  dialogApi[type]({
    ...(title ? { title } : {}),
    content,
    positiveText: "确定",
    maskClosable: true,
    closeOnEsc: true,
  })
}

/** Test-only: resets the bridge so unit tests start from a clean slate. */
export function _resetMessageApiForTest(): void {
  messageApi = null
  dialogApi = null
  queue = []
}

/** Test-only: resets the dialog bridge. */
export function _resetDialogApiForTest(): void {
  dialogApi = null
}
