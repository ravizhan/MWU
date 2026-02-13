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
}

// 运行设置
export interface RuntimeSettings {
  timeout: number
  reminderInterval: number
  autoRetry: boolean
  maxRetryCount: number
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

// 完整设置模型
export interface SettingsModel {
  update: UpdateSettings
  notification: NotificationSettings
  ui: UISettings
  runtime: RuntimeSettings
  about: AboutInfo
}
