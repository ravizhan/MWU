import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { toRaw } from "vue"

vi.mock("@/services/api", () => ({
  getSettings: vi.fn<() => void>(),
  updateSettings: vi.fn<() => void>(),
}))

import * as api from "@/services/api"
import i18n from "@/app/i18n"
import { useSettingsStore } from "@/stores/settings/settings"

function deferred<T>() {
  let resolvePromise: (value: T) => void = () => undefined
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve
  })
  return { promise, resolve: resolvePromise }
}

describe("settings persistence", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("serializes rapid whole-document writes without losing either field", async () => {
    const first = deferred<boolean>()
    const second = deferred<boolean>()
    vi.mocked(api.updateSettings)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const store = useSettingsStore()
    const firstUpdate = store.updateSetting("runtime", "timeout", 120)
    const secondUpdate = store.updateSetting("runtime", "retryInterval", 10)

    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    first.resolve(true)
    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(2))

    expect(vi.mocked(api.updateSettings).mock.calls[1][0].runtime).toMatchObject({
      timeout: 120,
      retryInterval: 10,
    })

    second.resolve(true)
    await expect(Promise.all([firstUpdate, secondUpdate])).resolves.toEqual([true, true])
    expect(store.settings.runtime).toMatchObject({ timeout: 120, retryInterval: 10 })
  })

  it("does not let an older failed write roll back a newer value", async () => {
    const first = deferred<boolean>()
    const second = deferred<boolean>()
    vi.mocked(api.updateSettings)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)

    const store = useSettingsStore()
    const firstUpdate = store.updateSetting("runtime", "timeout", 120)
    const secondUpdate = store.updateSetting("runtime", "timeout", 180)

    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    first.resolve(false)
    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(2))

    expect(store.settings.runtime.timeout).toBe(180)
    expect(vi.mocked(api.updateSettings).mock.calls[1][0].runtime.timeout).toBe(180)

    second.resolve(true)
    await expect(Promise.all([firstUpdate, secondUpdate])).resolves.toEqual([false, true])
    expect(store.settings.runtime.timeout).toBe(180)
  })

  it("restores the previous settings when reset persistence fails", async () => {
    vi.mocked(api.updateSettings).mockResolvedValue(false)
    const store = useSettingsStore()
    store.settings.telemetry.helpImproveSoftware = false
    store.settings.runtime.timeout = 120

    await expect(store.resetSettings()).resolves.toBe(false)

    expect(store.settings.telemetry.helpImproveSoftware).toBe(false)
    expect(store.settings.runtime.timeout).toBe(120)
  })

  it("allows retrying a failed settings load without using defaults as saved consent", async () => {
    const store = useSettingsStore()
    const savedSettings = structuredClone(toRaw(store.settings))
    savedSettings.telemetry.helpImproveSoftware = false
    vi.mocked(api.getSettings)
      .mockRejectedValueOnce(new Error("network error"))
      .mockResolvedValueOnce(savedSettings)

    await expect(store.fetchSettings()).resolves.toBe(false)
    expect(store.initialized).toBe(false)
    expect(store.loadFailed).toBe(true)
    expect(api.updateSettings).not.toHaveBeenCalled()

    await expect(store.fetchSettings()).resolves.toBe(true)
    expect(store.initialized).toBe(true)
    expect(store.loadFailed).toBe(false)
    expect(store.settings.telemetry.helpImproveSoftware).toBe(false)
  })

  it("applies the saved language over the browser cache and backfills only when unset", async () => {
    localStorage.setItem("locale", "zh-CN")
    i18n.global.locale.value = "zh-CN"
    const store = useSettingsStore()
    const saved = structuredClone(toRaw(store.settings))
    saved.ui.language = "en-US"
    vi.mocked(api.getSettings).mockResolvedValueOnce(saved)

    await store.fetchSettings()
    expect(i18n.global.locale.value).toBe("en-US")
    expect(localStorage.getItem("locale")).toBe("en-US")
    expect(api.updateSettings).not.toHaveBeenCalled()

    vi.mocked(api.updateSettings).mockResolvedValue(true)
    vi.mocked(api.getSettings).mockResolvedValueOnce({
      ...saved,
      ui: { ...saved.ui, language: null },
    })
    await store.fetchSettings()
    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.updateSettings).mock.calls[0][0].ui.language).toBe("en-US")
  })

  it("reverts the language only when the last queued save fails", async () => {
    const store = useSettingsStore()
    const saved = structuredClone(toRaw(store.settings))
    saved.ui.language = "zh-CN"
    vi.mocked(api.getSettings).mockResolvedValueOnce(saved)
    await store.fetchSettings()

    const first = deferred<boolean>()
    const second = deferred<boolean>()
    vi.mocked(api.updateSettings)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
      .mockResolvedValueOnce(false)

    const toEnglish = store.updateSetting("ui", "language", "en-US")
    const laterSave = store.updateSetting("runtime", "timeout", 120)
    first.resolve(false)
    await vi.waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(2))
    expect(i18n.global.locale.value).toBe("en-US")
    second.resolve(true)
    await expect(Promise.all([toEnglish, laterSave])).resolves.toEqual([false, true])
    expect(i18n.global.locale.value).toBe("en-US")

    await expect(store.updateSetting("ui", "language", "zh-CN")).resolves.toBe(false)
    expect(store.settings.ui.language).toBe("en-US")
    expect(i18n.global.locale.value).toBe("en-US")
    expect(localStorage.getItem("locale")).toBe("en-US")
  })

  it("keeps the persisted language when a reset fails behind a failed language save", async () => {
    const store = useSettingsStore()
    const saved = structuredClone(toRaw(store.settings))
    saved.ui.language = "en-US"
    vi.mocked(api.getSettings).mockResolvedValueOnce(saved)
    await store.fetchSettings()

    vi.mocked(api.updateSettings).mockResolvedValue(false)
    const toChinese = store.updateSetting("ui", "language", "zh-CN")
    const reset = store.resetSettings()
    await expect(Promise.all([toChinese, reset])).resolves.toEqual([false, false])

    expect(store.settings.ui.language).toBe("en-US")
    expect(i18n.global.locale.value).toBe("en-US")
  })
})
