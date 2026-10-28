import { nextTick } from "vue"

/** Minimal `Response` whose body resolves with `promise`. */
export function deferredResponse(promise: Promise<string>): Response {
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  return { ok: true, text: () => promise } as unknown as Response
}

// tsconfig lib predates ES2024, so Promise.withResolvers is unavailable.
export function withResolvers<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

export function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input
  return input instanceof URL ? input.href : input.url
}

// The stale continuation and the Vue render it would trigger are all queued as
// microtasks, so flushing microtasks settles them deterministically.
export async function flushPendingWork() {
  for (let i = 0; i < 10; i++) {
    await nextTick()
  }
}
