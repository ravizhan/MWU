import type { TaskOptionValue } from "@/types/schedulerModel"

// 更新设置
export interface UpdateSettings {
  autoUpdate: boolean
  updateChannel: "stable" | "beta"
  proxy: string
  mirrorchyanCdk: string
}

// 外部通知设置
export interface NotificationSettings {
  systemNotification: boolean
  browserNotification: boolean
  externalNotification: boolean
  webhook: string
  contentType: "application/json" | "application/x-www-form-urlencoded"
  headers: string
  body: string
  username: string
  password: string
  method: "POST" | "GET"
  notifyOnComplete: boolean
  notifyOnError: boolean
}

// 界面设置
export interface UISettings {
  darkMode: boolean | "auto"
  language: "zh-CN" | "en-US"
}

// 运行设置
export interface RuntimeSettings {
  timeout: number
  reminderInterval: number
  autoRetry: boolean
  maxRetryCount: number
  retryInterval: number
}

// 关于我们（包含联系方式）
export interface AboutInfo {
  version: string
  author: string
  github: string
  license: string
  description: string
  contact: string
  issueUrl: string
}

// 面板持久化设备信息
export interface PanelLastConnectedDevice {
  type: "Adb" | "Win32" | "Gamepad" | "PlayCover" | "MacOS" | "Linux"
  controller_name: string
  fingerprint: string
  adb_path: string
  address: string
  class_name: string
  window_name: string
  hWnd: number
  gamepad_type: number
  uuid: string
}

// 自定义设备（后端持久化，前端透传保留）
export interface CustomDevice {
  controller_name: string
  type: string
  address: string
}

// 面板持久化设置
export interface PanelSettings {
  lastResource: string
  lastConnectedDevice: PanelLastConnectedDevice | null
  recentDevices: PanelLastConnectedDevice[] | null
  customDevices?: CustomDevice[]
}

// 完整设置模型
export interface SettingsModel {
  update: UpdateSettings
  notification: NotificationSettings
  ui: UISettings
  runtime: RuntimeSettings
  about: AboutInfo
  panel: PanelSettings
  globalOptionValues: Record<string, TaskOptionValue>
}
