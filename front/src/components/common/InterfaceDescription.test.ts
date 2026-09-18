import { createPinia } from "pinia"
import { afterEach, describe, expect, it, vi } from "vitest"
import { createApp, defineComponent, h, nextTick, ref } from "vue"
import type { App } from "vue"
import InterfaceDescription from "@/components/common/InterfaceDescription.vue"

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

describe("InterfaceDescription", () => {
  const apps: App[] = []

  afterEach(() => {
    while (apps.length) apps.pop()?.unmount()
    document.body.innerHTML = ""
  })

  it("ignores an earlier file-backed description resolving after a newer one", async () => {
    const oldContent = withResolvers<string>()
    const newContent = withResolvers<string>()
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = requestUrl(input)
      if (url.includes("old.md")) return Promise.resolve(deferredResponse(oldContent.promise))
      if (url.includes("new.md")) return Promise.resolve(deferredResponse(newContent.promise))
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })

    const text = ref("old.md")
    const el = document.createElement("div")
    document.body.appendChild(el)
    const app = createApp(
      defineComponent({
        setup() {
          return () => h(InterfaceDescription, { text: text.value })
        },
      }),
    )
    app.use(createPinia())
    app.mount(el)
    apps.push(app)

    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1))
    text.value = "new.md"
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))

    newContent.resolve("New description")
    await vi.waitFor(() => expect(el.textContent).toContain("New description"))

    oldContent.resolve("Old description")
    await flushPendingWork()
    expect(el.textContent).toContain("New description")
    expect(el.textContent).not.toContain("Old description")
  })
})
