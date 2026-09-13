import type { ApiResponse } from "@/services/api/core/types"

export type DeviceControllerType = "Adb" | "Win32" | "Gamepad" | "PlayCover" | "MacOS" | "Linux"

/** Narrow a wire string to a known device controller type. */
export function isDeviceControllerType(type: string): type is DeviceControllerType {
  return (
    type === "Adb" ||
    type === "Win32" ||
    type === "Gamepad" ||
    type === "PlayCover" ||
    type === "MacOS" ||
    type === "Linux"
  )
}

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

/**
 * Backend response envelope: the payload key is `data` for device endpoints and
 * `state` for the runtime-state endpoint.
 */
type Envelope<T, K extends string = "data"> = ApiResponse & Record<K, T>

export function getDevices(controllerName?: string): Promise<DeviceSearchData> {
  const query = controllerName ? `?controller=${encodeURIComponent(controllerName)}` : ""
  return fetch(`/api/device${query}`, { method: "GET" })
    .then((res) => res.json())
    .then((body: Envelope<DeviceSearchData>) => body.data)
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
    .then((body: Envelope<ConnectableDevice | undefined>) => {
      if (body.status === "success" && body.data) {
        return { success: true, message: body.message || "自定义设备已保存", data: body.data }
      }
      return { success: false, message: body.message || "保存自定义设备失败" }
    })
    .catch((error) => {
      console.error("Failed to save custom device:", error)
      return { success: false, message: "网络错误，请稍后重试" }
    })
}

export function getDeviceState(): Promise<DeviceRuntimeState> {
  return fetch("/api/device/state", { method: "GET" })
    .then((res) => res.json())
    .then((body: Envelope<DeviceRuntimeState, "state">) => {
      if (body.status !== "success") {
        throw new Error(body.message || "获取设备状态失败")
      }
      return body.state
    })
}
