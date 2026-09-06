import type { ApiResponse } from "@/services/api/core/types"

export interface PostDeviceResult {
  success: boolean
  message: string
}

export type DeviceControllerType = "Adb" | "Win32" | "Gamepad" | "PlayCover" | "MacOS" | "Linux"

export interface AdbDevice {
  type: "Adb"
  name: string
  adb_path: string
  address: string
  screencap_methods: number | string
  input_methods: number | string
  config: Record<string, unknown>
}

export interface Win32Device {
  type: "Win32"
  hWnd: number
  class_name: string
  window_name: string
  screencap_methods: number
  input_methods: number
}

export interface GamepadDevice {
  type: "Gamepad"
  hWnd: number
  class_name: string
  window_name: string
  screencap_methods: number
  gamepad_type: number
}

export interface PlayCoverDevice {
  type: "PlayCover"
  name?: string
  address: string
  uuid?: string
}

export interface MacOSDevice {
  type: "MacOS"
  window_id: number
  window_name: string
}

export interface LinuxDevice {
  type: "Linux"
  name?: string
  address: string
}

export type ConnectableDevice =
  | AdbDevice
  | Win32Device
  | GamepadDevice
  | PlayCoverDevice
  | MacOSDevice
  | LinuxDevice

export interface ConnectDevicePayload {
  controller_name: string
  device: ConnectableDevice
  resource_name: string
}

export interface SaveCustomDevicePayload {
  controller_name: string
  type: DeviceControllerType
  address: string
}

export interface SaveCustomDeviceResult {
  success: boolean
  message: string
  data?: ConnectableDevice
}

export interface DeviceControllerCapability {
  name: string
  type: DeviceControllerType
  label: string
  display_label: string
  enabled: boolean
  reason: string
  search_mode: "select" | "input"
  default_address: string
}

export interface DeviceSearchData {
  controllers: DeviceControllerCapability[]
  selected_controller: string | null
  devices: ConnectableDevice[]
}

export interface DeviceRuntimeState {
  connected: boolean
  configuration_locked: boolean
  controller_name: string | null
  resource_name: string | null
}

interface DeviceResponse {
  status: string
  data: DeviceSearchData
}

interface DeviceStateResponse {
  status: string
  state: DeviceRuntimeState
}

interface CustomDeviceResponse extends ApiResponse {
  data?: ConnectableDevice
}

export function getDevices(controllerName?: string): Promise<DeviceSearchData> {
  const query = controllerName ? `?controller=${encodeURIComponent(controllerName)}` : ""
  return fetch(`/api/device${query}`, { method: "GET" })
    .then((res) => res.json())
    .then((data: DeviceResponse) => data.data)
}

export function postDevices(payload: ConnectDevicePayload): Promise<PostDeviceResult> {
  return fetch("/api/device", {
    method: "POST",
    body: JSON.stringify({
      device: { ...payload.device, controller_name: payload.controller_name },
      resource_name: payload.resource_name,
    }),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return { success: true, message: "设备连接成功" }
      }
      return { success: false, message: data.message || "设备连接失败，请检查终端日志" }
    })
    .catch((error) => {
      console.error("Failed to connect device:", error)
      return { success: false, message: "网络错误，请稍后重试" }
    })
}

export function postCustomDevice(
  payload: SaveCustomDevicePayload,
): Promise<SaveCustomDeviceResult> {
  return fetch("/api/device/custom", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: CustomDeviceResponse) => {
      if (data.status === "success" && data.data) {
        return { success: true, message: data.message || "自定义设备已保存", data: data.data }
      }
      return { success: false, message: data.message || "保存自定义设备失败" }
    })
    .catch((error) => {
      console.error("Failed to save custom device:", error)
      return { success: false, message: "网络错误，请稍后重试" }
    })
}

export function getDeviceState(): Promise<DeviceRuntimeState> {
  return fetch("/api/device/state", { method: "GET" })
    .then((res) => res.json())
    .then((data: DeviceStateResponse & ApiResponse) => {
      if (data.status !== "success") {
        throw new Error(data.message || "获取设备状态失败")
      }
      return data.state
    })
}
