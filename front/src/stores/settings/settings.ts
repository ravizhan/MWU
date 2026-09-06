import { defineStore } from "pinia"
import { tryCatch } from "@/utils/tryCatch"
import { getSettings, updateSettings } from "@/services/api"
import type { TaskOptionValue } from "@/types/schedulerModel"
import type { PanelLastConnectedDevice, SettingsModel } from "@/types/settingsModel"

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
    reminderInterval: 30,
    autoRetry: true,
    maxRetryCount: 3,
    retryInterval: 5,
  },
  about: {
    version: "",
    author: "",
    github: "",
    license: "",
    description: "",
    contact: "",
    issueUrl: "",
  },
  panel: {
    lastResource: "",
    lastConnectedDevice: null,
    recentDevices: [],
    customDevices: [],
  },
  globalOptionValues: {},
}

const DARK_MODE_KEY = "darkMode"

let saveQueue: Promise<void> = Promise.resolve()

function enqueueSettingsSave(save: () => Promise<boolean>): Promise<boolean> {
  const result = saveQueue.then(save)
  saveQueue = result.then(
    () => undefined,
    () => undefined,
  )
  return result
}

function applySettingsPatch<K extends keyof SettingsModel, P extends keyof SettingsModel[K]>(
  settings: SettingsModel,
  category: K,
  key: P,
  value: SettingsModel[K][P],
) {
  settings[category][key] = value
}

function getCachedDarkMode(): "auto" | boolean {
  if (typeof window === "undefined" || typeof localStorage === "undefined") return "auto"
  const cached = localStorage.getItem(DARK_MODE_KEY)
  if (cached === "true") return true
  if (cached === "false") return false
  return "auto"
}

// Deep clone helper to prevent mutation of default settings
function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj))
}

export const useSettingsStore = defineStore("settings", {
  state: () => {
    const settings: SettingsModel = {
      ...deepClone(defaultSettings),
      ui: { darkMode: getCachedDarkMode(), language: "zh-CN" },
    }
    return {
      settings,
      persistedSettings: deepClone(settings),
      loading: false,
      pendingSaveCount: 0,
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
      const [data, err] = await tryCatch(() => getSettings())
      if (err) {
        console.error("Failed to fetch settings:", err)
        this.loading = false
        return
      }
      if (data) {
        this.settings = {
          update: { ...defaultSettings.update, ...data.update },
          notification: { ...defaultSettings.notification, ...data.notification },
          ui: { ...defaultSettings.ui, ...data.ui },
          runtime: { ...defaultSettings.runtime, ...data.runtime },
          about: { ...defaultSettings.about, ...data.about },
          panel: {
            ...defaultSettings.panel,
            ...data.panel,
            lastConnectedDevice: data.panel?.lastConnectedDevice ?? null,
            recentDevices: data.panel?.recentDevices ?? [],
            customDevices: data.panel?.customDevices ?? this.settings.panel.customDevices ?? [],
          },
          globalOptionValues: { ...data.globalOptionValues },
        }
        this.persistedSettings = deepClone(this.settings)
        // 确保本地缓存与服务器设置同步
        localStorage.setItem(DARK_MODE_KEY, String(this.settings.ui.darkMode))
      }
      this.initialized = true
      this.loading = false
    },

    async saveSettings(newSettings?: SettingsModel) {
      const payload = deepClone(newSettings || this.settings)
      this.pendingSaveCount += 1
      this.loading = true
      const [success, err] = await tryCatch(() =>
        enqueueSettingsSave(async () => {
          const saved = await updateSettings(payload)
          if (saved) {
            this.persistedSettings = deepClone(payload)
          }
          return saved
        }),
      )
      this.pendingSaveCount -= 1
      this.loading = this.pendingSaveCount > 0
      if (err) {
        console.error("Failed to save settings:", err)
        return false
      }
      if (success) {
        // 保存成功后更新本地缓存
        localStorage.setItem(DARK_MODE_KEY, String(this.settings.ui.darkMode))
      }
      return success
    },

    async saveSettingPatch<K extends keyof SettingsModel, P extends keyof SettingsModel[K]>(
      category: K,
      key: P,
      value: SettingsModel[K][P],
    ) {
      this.pendingSaveCount += 1
      this.loading = true
      const [success, err] = await tryCatch(() =>
        enqueueSettingsSave(async () => {
          const payload = deepClone(this.persistedSettings)
          applySettingsPatch(payload, category, key, deepClone(value))
          const saved = await updateSettings(payload)
          if (saved) {
            this.persistedSettings = payload
          }
          return saved
        }),
      )
      this.pendingSaveCount -= 1
      this.loading = this.pendingSaveCount > 0
      if (err) {
        console.error("Failed to save settings:", err)
        return false
      }
      return success
    },

    async updateSetting<K extends keyof SettingsModel, P extends keyof SettingsModel[K]>(
      category: K,
      key: P,
      value: SettingsModel[K][P],
    ) {
      const updatedSettings = {
        ...this.settings,
        [category]: {
          ...this.settings[category],
          [key]: value,
        },
      }

      // 乐观更新：立即更新状态和缓存
      this.settings = updatedSettings
      if (category === "ui" && key === "darkMode") {
        localStorage.setItem(DARK_MODE_KEY, String(value))
      }

      // 后台保存
      const success = await this.saveSettingPatch(category, key, value)
      if (!success) {
        if (Object.is(this.settings[category][key], value)) {
          applySettingsPatch(
            this.settings,
            category,
            key,
            deepClone(this.persistedSettings[category][key]),
          )
          if (category === "ui" && key === "darkMode") {
            localStorage.setItem(DARK_MODE_KEY, String(this.settings.ui.darkMode))
          }
        }
      }
      return success
    },

    async updateGlobalOptionValue(optionKey: string, value: TaskOptionValue) {
      this.settings = {
        ...this.settings,
        globalOptionValues: {
          ...this.settings.globalOptionValues,
          [optionKey]: value,
        },
      }

      const success = await this.saveSettingPatch("globalOptionValues", optionKey, value)
      if (success || !Object.is(this.settings.globalOptionValues[optionKey], value)) {
        return success
      }
      const persistedValue = this.persistedSettings.globalOptionValues[optionKey]
      if (persistedValue === undefined) {
        delete this.settings.globalOptionValues[optionKey]
        return false
      }
      this.settings.globalOptionValues[optionKey] = deepClone(persistedValue)
      return false
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
      const resetData: SettingsModel = {
        ...deepClone(defaultSettings),
        about: { ...this.settings.about }, // 保留关于信息
      }
      // 重置时也要更新缓存
      localStorage.setItem(DARK_MODE_KEY, "auto")
      this.settings = resetData
      return this.saveSettings(resetData)
    },
  },
})
