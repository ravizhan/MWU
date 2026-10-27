import { afterAll, afterEach, beforeAll, vi } from "vitest"
import { server } from "./mocks/server"

beforeAll(() => server.listen({ onUnhandledFrame: "error" }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

// Mock EventSource globally since sse.ts creates an instance at module level
// Use a class so `new EventSource(url)` works
const mockInstances: Array<{
  close: ReturnType<typeof vi.fn>
  onopen: (() => void) | null
  onmessage: ((event: { data: string }) => void) | null
  onerror: ((event: unknown) => void) | null
  readyState: number
  url: string
}> = []

// eslint-disable-next-line @typescript-eslint/consistent-type-assertions
const MockEventSource = vi.fn(function (this: unknown, url: string) {
  const instance = {
    close: vi.fn(),
    onopen: null,
    onmessage: null,
    onerror: null,
    readyState: 0,
    url,
  }
  mockInstances.push(instance)
  return instance
}) as unknown as new (url: string) => EventSource

vi.stubGlobal("EventSource", MockEventSource)
