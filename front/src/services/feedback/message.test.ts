import { describe, expect, it, beforeEach, vi } from "vitest"
import type { MessageApiInjection } from "naive-ui/es/message/src/MessageProvider"
import type { DialogApiInjection } from "naive-ui/es/dialog/src/DialogProvider"

let showGlobalMessage: (type: "info" | "success" | "warning" | "error", content: string) => void
let registerMessageApi: (api: MessageApiInjection) => void
let showGlobalDialog: (
  type: "info" | "success" | "warning" | "error",
  content: string,
  title?: string,
) => void
let registerDialogApi: (api: DialogApiInjection) => void
let _resetMessageApiForTest: () => void

function makeApiSpy(): MessageApiInjection {
  return {
    create: vi.fn<MessageApiInjection["create"]>(),
    info: vi.fn<MessageApiInjection["info"]>(),
    success: vi.fn<MessageApiInjection["success"]>(),
    warning: vi.fn<MessageApiInjection["warning"]>(),
    error: vi.fn<MessageApiInjection["error"]>(),
    loading: vi.fn<MessageApiInjection["loading"]>(),
    destroyAll: vi.fn<MessageApiInjection["destroyAll"]>(),
  }
}

function makeDialogApiSpy(): DialogApiInjection {
  return {
    create: vi.fn<DialogApiInjection["create"]>(),
    info: vi.fn<DialogApiInjection["info"]>(),
    success: vi.fn<DialogApiInjection["success"]>(),
    warning: vi.fn<DialogApiInjection["warning"]>(),
    error: vi.fn<DialogApiInjection["error"]>(),
    destroyAll: vi.fn<DialogApiInjection["destroyAll"]>(),
  }
}

describe("message service", () => {
  beforeEach(async () => {
    vi.resetModules()
    const messageModule = await import("@/services/feedback/message")
    showGlobalMessage = messageModule.showGlobalMessage
    registerMessageApi = messageModule.registerMessageApi
    showGlobalDialog = messageModule.showGlobalDialog
    registerDialogApi = messageModule.registerDialogApi
    _resetMessageApiForTest = messageModule._resetMessageApiForTest
    _resetMessageApiForTest()
  })

  it("delegates to the registered naive message api", () => {
    const api = makeApiSpy()
    registerMessageApi(api)
    showGlobalMessage("success", "operation completed")
    expect(api.create).toHaveBeenCalledWith("operation completed", {
      type: "success",
      duration: 3000,
    })
  })

  it("passes the message type through", () => {
    const api = makeApiSpy()
    registerMessageApi(api)
    showGlobalMessage("error", "failure")
    expect(api.create).toHaveBeenCalledWith("failure", { type: "error", duration: 3000 })
  })

  it("auto-dismisses after 3 seconds via duration option", () => {
    const api = makeApiSpy()
    registerMessageApi(api)
    showGlobalMessage("info", "temporary message")
    expect(api.create).toHaveBeenCalledWith("temporary message", {
      type: "info",
      duration: 3000,
    })
  })

  it("queues messages before registration and flushes them on register", () => {
    showGlobalMessage("warning", "queued before mount")
    const api = makeApiSpy()
    registerMessageApi(api)
    expect(api.create).toHaveBeenCalledWith("queued before mount", {
      type: "warning",
      duration: 3000,
    })
  })

  it("shows a one-shot dialog through the registered dialog provider", () => {
    const api = makeDialogApiSpy()
    registerDialogApi(api)

    showGlobalDialog("warning", "Please choose", "Task interaction")

    expect(api.warning).toHaveBeenCalledWith({
      title: "Task interaction",
      content: "Please choose",
      positiveText: "确定",
      maskClosable: true,
      closeOnEsc: true,
    })
  })

  it("does not queue a dialog before the provider is registered", () => {
    showGlobalDialog("info", "ephemeral")
    const api = makeDialogApiSpy()
    registerDialogApi(api)

    expect(api.info).not.toHaveBeenCalled()
  })
})
