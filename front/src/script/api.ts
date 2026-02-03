import type { InterfaceModel } from "../types/interface"
import type {
  ScheduledTaskCreate,
  ScheduledTaskUpdate,
  SchedulerApiResponse,
} from "../types/scheduler"

interface ApiResponse {
  status: string
  message: string
}

export interface AdbDevice {
  name: string
  adb_path: string
  address: string
  screencap_methods: string
  input_methods: string
  config: Record<string, any>
}

export interface Win32Device {
  hwnd: number
  class_name: string
  window_name: string
}

interface Devices {
  adb: AdbDevice[]
  win32: Win32Device[]
}

interface DeviceResponse {
  status: string
  devices: Devices
}

interface ResourceResponse {
  status: string
  resource: string[]
}

export function startTask(task_list: string[], options: Record<string, string>): void {
  fetch("/api/start", {
    method: "POST",
    body: JSON.stringify({ tasks: task_list, options: options }),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("任务开始")
      } else {
        // @ts-ignore
        window.$message.error(data.message)
      }
    })
}

export function stopTask(): void {
  fetch("/api/stop", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("正在中止任务，请稍后")
      } else {
        // @ts-ignore
        window.$message.error(data.message)
      }
    })
}

export function getDevices(): Promise<Devices> {
  return fetch("/api/device", { method: "GET" })
    .then((res) => res.json())
    .then((data: DeviceResponse) => data.devices)
}

export function postDevices(device: AdbDevice | Win32Device): Promise<boolean> {
  return fetch("/api/device", {
    method: "POST",
    body: JSON.stringify(device),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("设备连接成功")
        return true
      } else {
        // @ts-ignore
        window.$message.error("设备连接失败，请检查终端日志")
        return false
      }
    })
}

export function getInterface(): Promise<InterfaceModel> {
  return fetch("/api/interface", { method: "GET" }).then((res) => res.json())
}

export function getResource(): Promise<string[]> {
  return fetch("/api/resource", { method: "GET" })
    .then((res) => res.json())
    .then((data: ResourceResponse) => data.resource)
}

export function postResource(name: string): void {
  fetch("/api/resource?name=" + name, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("资源添加成功")
      } else {
        // @ts-ignore
        window.$message.error(data.message)
      }
    })
}

import type { SettingsModel } from "../types/settings"

interface SettingsResponse {
  status: string
  settings: SettingsModel
}

export function getSettings(): Promise<SettingsModel> {
  return fetch("/api/settings", { method: "GET" })
    .then((res) => res.json())
    .then((data: SettingsResponse) => data.settings)
}

export function updateSettings(settings: SettingsModel): Promise<boolean> {
  return fetch("/api/settings", {
    method: "POST",
    body: JSON.stringify(settings),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        // @ts-ignore
        window.$message.success("设置已保存")
        return true
      } else {
        // @ts-ignore
        window.$message.error(data.message || "保存失败")
        return false
      }
    })
    .catch((error) => {
      console.error("Failed to update settings:", error)
      // @ts-ignore
      window.$message.error("网络错误，请稍后重试")
      return false
    })
}

export interface UpdateInfo {
  latest_version: string
  current_version: string
  is_update_available: boolean
  release_notes: string
  download_url: string
  file_hash: string
  file_name: string
}

export interface UpdateCheckResponse {
  status: string
  update_info?: UpdateInfo
  message?: string
}

export interface UpdateStatusResponse {
  status: "idle" | "downloading" | "updating" | "success" | "failed"
  message: string
}

export function checkUpdateApi(): Promise<UpdateCheckResponse> {
  return fetch("/api/update/check", { method: "GET" }).then((res) => res.json())
}

export function performUpdateApi(): Promise<ApiResponse> {
  return fetch("/api/update", { method: "GET" }).then((res) => res.json())
}

export function getUpdateStatusApi(): Promise<UpdateStatusResponse> {
  return fetch("/api/update/status", { method: "GET" }).then((res) => res.json())
}

// Legacy compatibility function
export function checkUpdate(): Promise<{
  hasUpdate: boolean
  version?: string
  changelog?: string
  downloadUrl?: string
}> {
  return checkUpdateApi()
    .then((data) => {
      if (data.status === "success" && data.update_info) {
        return {
          hasUpdate: data.update_info.is_update_available || false,
          version: data.update_info.latest_version,
          changelog: data.update_info.release_notes,
          downloadUrl: data.update_info.download_url,
        }
      }
      return { hasUpdate: false }
    })
    .catch((error) => {
      console.error("Failed to check update:", error)
      return { hasUpdate: false }
    })
}

export interface UserConfig {
  taskOrder?: string[]
  taskChecked?: Record<string, boolean>
  taskOptions?: Record<string, string>
}

interface UserConfigResponse {
  status: string
  config: UserConfig
  message?: string
}

export function getUserConfig(): Promise<UserConfig> {
  return fetch("/api/user-config", { method: "GET" })
    .then((res) => res.json())
    .then((data: UserConfigResponse) => {
      if (data.status === "success") {
        return data.config || {}
      } else {
        console.error("Failed to load user config:", data.message)
        return {}
      }
    })
    .catch((error) => {
      console.error("Failed to load user config:", error)
      return {}
    })
}

export function saveUserConfig(config: UserConfig): Promise<boolean> {
  return fetch("/api/user-config", {
    method: "POST",
    body: JSON.stringify(config),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return true
      } else {
        console.error("Failed to save user config:", data.message)
        return false
      }
    })
    .catch((error) => {
      console.error("Failed to save user config:", error)
      return false
    })
}

export function resetUserConfig(): Promise<boolean> {
  return fetch("/api/user-config", {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return true
      } else {
        console.error("Failed to reset user config:", data.message)
        return false
      }
    })
    .catch((error) => {
      console.error("Failed to reset user config:", error)
      return false
    })
}

export function testNotificationApi(): Promise<ApiResponse> {
  return fetch("/api/test-notification", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function getSchedulerTasks(): Promise<SchedulerApiResponse> {
  return fetch("/api/scheduler/tasks", { method: "GET" }).then((res) => res.json())
}

export function createSchedulerTask(task: ScheduledTaskCreate): Promise<SchedulerApiResponse> {
  return fetch("/api/scheduler/tasks", {
    method: "POST",
    body: JSON.stringify(task),
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function updateSchedulerTask(
  taskId: string,
  taskUpdate: ScheduledTaskUpdate,
): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/tasks/${taskId}`, {
    method: "PUT",
    body: JSON.stringify(taskUpdate),
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function deleteSchedulerTask(taskId: string): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/tasks/${taskId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function pauseSchedulerTask(taskId: string): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/tasks/${taskId}/pause`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function resumeSchedulerTask(taskId: string): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/tasks/${taskId}/resume`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  }).then((res) => res.json())
}

export function getSchedulerExecutions(limit: number = 50): Promise<SchedulerApiResponse> {
  return fetch(`/api/scheduler/executions?limit=${limit}`, { method: "GET" }).then((res) =>
    res.json(),
  )
}
