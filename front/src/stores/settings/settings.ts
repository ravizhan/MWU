import { defineStore } from "pinia"
import i18n from "@/app/i18n"
import { tryCatch } from "@/utils/tryCatch"
import { getSettings, updateSettings } from "@/services/api"
import type { TaskOptionValue } from "@/types/schedulerModel"
import type { PanelLastConnectedDevice, SettingsModel } from "@/types/settingsModel"
import { localeSchema } from "@/validation/settings"

const defaultSettings: SettingsModel = {
  update: {
    autoUpdate: true,
    updateChannel: "stable",
    proxy: "",
    mirrorchyanCdk: "",
  },
  notification: {
    systemNotification: false,
    browserNotification: false,
    externalNotification: true,
    webhook: "",
    contentType: "application/json",
    headers: "",
    body: "",
    username: "",
    password: "",
    method: "POST",
    notifyOnComplete: true,
    notifyOnError: true,
  },
  ui: {
    darkMode: "auto",
    language: "zh-CN",
  },
  runtime: {
    timeout: 300,
    autoRetry: true,
    maxRetryCount: 3,
    retryInterval: 5,
  },
  panel: {
    lastResource: "",
    lastConnectedDevice: null,
    recentDevices: [],
    customDevices: [],
  },
  telemetry: {
    helpImproveSoftware: true,
  },
  globalOptionValues: {},
}

const DARK_MODE_KEY = "darkMode"
const LOCALE_KEY = "locale"

type UILocale = NonNullable<SettingsModel["ui"]["language"]>

let saveQueue: Promise<void> = Promise.resolve()

function enqueueSettingsSave(save: () => Promise<boolean>): Promise<boolean> {
  const result = saveQueue.then(save)
  saveQueue = result.then(
    () => undefined,
    () => undefined,
  )
  return result
}

function getCachedDarkMode(): "auto" | boolean {
  if (typeof window === "undefined" || typeof localStorage === "undefined") return "auto"
  const cached = localStorage.getItem(DARK_MODE_KEY)
  if (cached === "true") return true
  if (cached === "false") return false
  return "auto"
}

function getCachedLocale(): UILocale {
  if (typeof localStorage === "undefined") return "zh-CN"
  const parsed = localeSchema.safeParse(localStorage.getItem(LOCALE_KEY))
  return parsed.success ? parsed.data : "zh-CN"
}

function applyLocale(language: UILocale): void {
  localStorage.setItem(LOCALE_KEY, language)
  i18n.global.locale.value = language
}

// TS cannot write through generic indexed access (`settings[category][key] = value`),
// so the assignment lives in one typed helper instead of a cast at each call site.
function assignSetting<K extends keyof SettingsModel, P extends keyof SettingsModel[K]>(
  settings: SettingsModel,
  category: K,
  key: P,
  value: SettingsModel[K][P],
): void {
  settings[category][key] = value
}

// Deep clone helper to prevent mutation of default settings
function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj))
}

interface SettingsState {
  settings: SettingsModel
  loading: boolean
  loadFailed: boolean
  pendingSaveCount: number
  /** 后端最后一次确认保存的语言；保存失败后据此回滚界面语言 */
  persistedLanguage: UILocale | null
  initialized: boolean
  systemPrefersDark: boolean
}

export const useSettingsStore = defineStore("settings", {
  state: (): SettingsState => {
    const settings: SettingsModel = {
      ...deepClone(defaultSettings),
      ui: { darkMode: getCachedDarkMode(), language: getCachedLocale() },
    }
    return {
      settings,
      loading: false,
      loadFailed: false,
      pendingSaveCount: 0,
      persistedLanguage: null,
      initialized: false,
      systemPrefersDark:
        typeof window !== "undefined" && window.matchMedia
          ? window.matchMedia("(prefers-color-scheme: dark)").matches
          : false,
    }
  },

  getters: {
    isDarkMode(state): boolean {
      if (state.settings.ui.darkMode === "auto") {
        return state.systemPrefersDark
      }
      return !!state.settings.ui.darkMode
    },
  },

  actions: {
    initSystemThemeListener() {
      if (typeof window === "undefined" || !window.matchMedia) return

      const media = window.matchMedia("(prefers-color-scheme: dark)")
      const listener = (e: MediaQueryListEvent) => {
        this.systemPrefersDark = e.matches
      }

      media.addEventListener("change", listener)
      this.systemPrefersDark = media.matches
    },

    async fetchSettings() {
      this.loading = true
      this.loadFailed = false
      const [data, err] = await tryCatch(() => getSettings())
      if (err) {
        console.error("Failed to fetch settings:", err)
        this.loadFailed = true
        this.loading = false
        return false
      }
      this.settings = data
      // 确保本地缓存与服务器设置同步
      localStorage.setItem(DARK_MODE_KEY, String(this.settings.ui.darkMode))
      this.initialized = true
      this.loading = false
      const savedLanguage = this.settings.ui.language
      this.persistedLanguage = savedLanguage
      if (savedLanguage) {
        applyLocale(savedLanguage)
        return true
      }
      // 后端尚未保存语言：用本机语言补写一次
      this.settings.ui.language = getCachedLocale()
      void this.saveSettings()
      return true
    },

    /**
     * 整份设置保存。写入串行入队，避免两个整文档 POST 互相覆盖；每次调用都
     * 携带调用时刻的完整快照，因此后到的修改不会丢字段。
     */
    async saveSettings(newSettings?: SettingsModel) {
      const payload = deepClone(newSettings ?? this.settings)
      this.pendingSaveCount += 1
      this.loading = true
      const [success, err] = await tryCatch(() =>
        enqueueSettingsSave(() => updateSettings(payload)),
      )
      this.pendingSaveCount -= 1
      this.loading = this.pendingSaveCount > 0
      if (err) console.error("Failed to save settings:", err)
      const saved = !err && success
      if (saved) {
        // 保存成功后更新本地缓存
        localStorage.setItem(DARK_MODE_KEY, String(this.settings.ui.darkMode))
        if (payload.ui.language) this.persistedLanguage = payload.ui.language
      }
      this.reconcileLanguage()
      return saved
    },

    /**
     * 队列清空后，若界面语言不是后端已保存的语言（最后一次保存失败），回滚到已保存语言。
     * 仍有排队的保存时不处理：它们携带更新的选择，由最后一次保存决定结果。
     */
    reconcileLanguage() {
      if (this.pendingSaveCount > 0 || !this.persistedLanguage) return
      if (this.settings.ui.language === this.persistedLanguage) return
      this.settings.ui.language = this.persistedLanguage
      applyLocale(this.persistedLanguage)
    },

    async updateSetting<K extends keyof SettingsModel, P extends keyof SettingsModel[K]>(
      category: K,
      key: P,
      value: SettingsModel[K][P],
    ) {
      assignSetting(this.settings, category, key, value)
      if (category === "ui" && key === "darkMode") {
        localStorage.setItem(DARK_MODE_KEY, String(value))
      }
      if (category === "ui" && key === "language") {
        const parsed = localeSchema.safeParse(value)
        if (parsed.success) applyLocale(parsed.data)
      }
      return this.saveSettings()
    },

    async updateGlobalOptionValue(optionKey: string, value: TaskOptionValue) {
      this.settings.globalOptionValues[optionKey] = value
      return this.saveSettings()
    },

    addRecentDevice(deviceConfig: PanelLastConnectedDevice) {
      const list = this.settings.panel.recentDevices ?? []
      // Deduplicate: remove existing entry with same fingerprint
      const filtered = list.filter((d) => d.fingerprint !== deviceConfig.fingerprint)
      // Add most recent first
      filtered.unshift(deviceConfig)
      // Keep max 5
      this.settings.panel.recentDevices = filtered.slice(0, 5)
      return this.saveSettings()
    },

    removeRecentDevice(fingerprint: string) {
      const list = this.settings.panel.recentDevices ?? []
      this.settings.panel.recentDevices = list.filter((d) => d.fingerprint !== fingerprint)
      return this.saveSettings()
    },

    async resetSettings() {
      const previousSettings = deepClone(this.settings)
      this.settings = deepClone(defaultSettings)
      const success = await this.saveSettings()
      if (success) {
        applyLocale(this.settings.ui.language ?? "zh-CN")
        return true
      }

      this.settings = previousSettings
      localStorage.setItem(DARK_MODE_KEY, String(this.settings.ui.darkMode))
      return false
    },
  },
})
