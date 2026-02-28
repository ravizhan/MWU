import { defineStore } from "pinia"
import { getSettings, updateSettings } from "../script/api"
import type { SettingsModel } from "../types/settings"

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
  },
  runtime: {
    timeout: 300,
    reminderInterval: 30,
    autoRetry: true,
    maxRetryCount: 3,
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
  },
}

const DARK_MODE_KEY = "darkMode"

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
  state: () => ({
    settings: {
      ...deepClone(defaultSettings),
      ui: { darkMode: getCachedDarkMode() },
    } as SettingsModel,
    loading: false,
    initialized: false,
    systemPrefersDark:
      typeof window !== "undefined" && window.matchMedia
        ? window.matchMedia("(prefers-color-scheme: dark)").matches
        : false,
  }),

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
      try {
        const data = await getSettings()
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
            },
          }
          // 确保本地缓存与服务器设置同步
          localStorage.setItem(DARK_MODE_KEY, String(this.settings.ui.darkMode))
        }
        this.initialized = true
      } catch (error) {
        console.error("Failed to fetch settings:", error)
      } finally {
        this.loading = false
      }
    },

    async saveSettings(newSettings?: SettingsModel) {
      this.loading = true
      try {
        const payload = newSettings || this.settings
        const success = await updateSettings(payload)
        if (success) {
          this.settings = deepClone(payload)
          // 保存成功后更新本地缓存
          localStorage.setItem(DARK_MODE_KEY, String(this.settings.ui.darkMode))
        }
        return success
      } catch (error) {
        console.error("Failed to save settings:", error)
        return false
      } finally {
        this.loading = false
      }
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
      return this.saveSettings(updatedSettings)
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
