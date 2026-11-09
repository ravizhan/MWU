import type { TaskOptionValue } from "@/types/schedulerModel"

// 更新设置
export interface UpdateSettings {
  autoUpdate: boolean
  updateChannel: "stable" | "beta"
  proxy: string
  mirrorchyanCdk: string
}

export type NotificationChannelType =
  | "dingtalk"
  | "feishu"
  | "wecom"
  | "serverchan"
  | "onebot"
  | "smtp"
  | "telegram"
  | "bark"
  | "wxpusher"
  | "pushplus"
  | "webhook"

// 外部通知渠道；params 全部为字符串，字段集合由 type 决定并由后端校验
export interface NotificationChannel {
  id: string
  type: NotificationChannelType
  enabled: boolean
  params: Record<string, string>
}

// 通知触发时机开关，与后端 NotificationTrigger 一致
export type NotificationTrigger =
  | "notifyOnStart"
  | "notifyOnComplete"
  | "notifyOnError"
  | "notifyOnTaskSuccess"
  | "notifyOnTaskFailure"
  | "notifyOnPretaskFailed"
  | "notifyOnConnectFailed"
  | "notifyOnScheduledSkip"

// 通知设置
export interface NotificationSettings extends Record<NotificationTrigger, boolean> {
  systemNotification: boolean
  browserNotification: boolean
  externalNotification: boolean
  channels: NotificationChannel[]
  attachScreenshot: boolean
}

// 界面设置
export interface UISettings {
  darkMode: boolean | "auto"
  // null：后端尚未保存过语言
  language: "zh-CN" | "en-US" | null
}

// 运行设置
export interface RuntimeSettings {
  autoRetry: boolean
  maxRetryCount: number
  retryInterval: number
}

// 遥测设置
export interface TelemetrySettings {
  helpImproveSoftware: boolean
}

// 面板持久化设备信息
export interface PanelLastConnectedDevice {
  type: "Adb" | "Win32" | "Gamepad" | "PlayCover" | "Linux"
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
  panel: PanelSettings
  telemetry: TelemetrySettings
  globalOptionValues: Record<string, TaskOptionValue>
  /** PI 前置任务勾选状态，key 见 pretaskKey；缺省视为启用 */
  pretaskEnabled: Record<string, boolean>
}
