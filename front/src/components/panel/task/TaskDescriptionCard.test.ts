import { createPinia } from "pinia"
import { afterEach, describe, expect, it, vi } from "vitest"
import { createApp, nextTick } from "vue"
import type { App } from "vue"
import { createI18n } from "vue-i18n"
import TaskDescriptionCard from "@/components/panel/task/TaskDescriptionCard.vue"
import { useIndexStore, useInterfaceStore } from "@/stores"

function deferredResponse(promise: Promise<string>): Response {
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  return { ok: true, text: () => promise } as unknown as Response
}

// tsconfig lib predates ES2024, so Promise.withResolvers is unavailable.
function withResolvers<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input
  return input instanceof URL ? input.href : input.url
}

// The stale continuation and the Vue render it would trigger are all queued as
// microtasks, so flushing microtasks settles them deterministically.
async function flushPendingWork() {
  for (let i = 0; i < 10; i++) {
    await nextTick()
  }
}

describe("TaskDescriptionCard", () => {
  const apps: App[] = []

  afterEach(() => {
    while (apps.length) apps.pop()?.unmount()
    document.body.innerHTML = ""
  })

  it("ignores a previous task description resolving after the selected task changed", async () => {
    const oldContent = withResolvers<string>()
    const newContent = withResolvers<string>()
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = requestUrl(input)
      if (url.includes("old.md")) return Promise.resolve(deferredResponse(oldContent.promise))
      if (url.includes("new.md")) return Promise.resolve(deferredResponse(newContent.promise))
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })

    const pinia = createPinia()
    const interfaceStore = useInterfaceStore(pinia)
    interfaceStore.interface = {
      task: [
        { name: "task-a", entry: "A", description: "old.md" },
        { name: "task-b", entry: "B", description: "new.md" },
      ],
    }
    const sessionStore = useIndexStore(pinia)
    sessionStore.SelectedTaskID = "task-a"

    const i18n = createI18n({
      legacy: false,
      locale: "en-US",
      messages: { "en-US": { panel: { empty: "empty" } } },
    })

    const el = document.createElement("div")
    document.body.appendChild(el)
    const app = createApp(TaskDescriptionCard)
    app.use(pinia)
    app.use(i18n)
    app.mount(el)
    apps.push(app)

    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1))
    sessionStore.SelectedTaskID = "task-b"
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))

    newContent.resolve("New description")
    await vi.waitFor(() => expect(el.textContent).toContain("New description"))

    oldContent.resolve("Old description")
    await flushPendingWork()
    expect(el.textContent).toContain("New description")
    expect(el.textContent).not.toContain("Old description")
  })
})
