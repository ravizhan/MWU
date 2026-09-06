import type {
  AdbDevice,
  ConnectableDevice,
  DeviceControllerCapability,
  GamepadDevice,
  Win32Device,
} from "@/services/api"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"

export function isAdbDevice(value: unknown): value is AdbDevice {
  return !!value && typeof value === "object" && "type" in value && value.type === "Adb"
}

export function isWin32Device(value: unknown): value is Win32Device {
  return !!value && typeof value === "object" && "type" in value && value.type === "Win32"
}

export function isGamepadDevice(value: unknown): value is GamepadDevice {
  return !!value && typeof value === "object" && "type" in value && value.type === "Gamepad"
}

/** Stable identity used for merge/dedup matching (address or window handle). */
export function getDeviceIdentity(deviceInfo: ConnectableDevice): string {
  if (isAdbDevice(deviceInfo)) {
    return deviceInfo.address
  }
  if (isWin32Device(deviceInfo)) {
    return String(deviceInfo.hWnd)
  }
  if (isGamepadDevice(deviceInfo)) {
    return `${deviceInfo.hWnd}|${deviceInfo.gamepad_type}`
  }
  if (deviceInfo.type === "MacOS") {
    return String(deviceInfo.window_id)
  }
  return deviceInfo.address
}

/** Stable identity for a persisted last-connected snapshot (same semantics as getDeviceIdentity). */
export function getStoredDeviceIdentity(stored: PanelLastConnectedDevice): string {
  if (
    stored.type === "Adb" ||
    stored.type === "PlayCover" ||
    stored.type === "MacOS" ||
    stored.type === "Linux"
  ) {
    return stored.address
  }
  if (stored.type === "Win32") {
    return String(stored.hWnd)
  }
  return `${stored.hWnd}|${stored.gamepad_type}`
}

export function storedDeviceMatchesController(
  stored: PanelLastConnectedDevice,
  capability: Pick<DeviceControllerCapability, "name">,
): boolean {
  return stored.controller_name === capability.name
}

/** Match by identity first, then fingerprint (scan may enrich a saved custom device). */
export function findDeviceByIdentityOrFingerprint(
  devices: ConnectableDevice[],
  target: ConnectableDevice,
): ConnectableDevice | undefined {
  const targetIdentity = getDeviceIdentity(target)
  const byIdentity = devices.find((item) => getDeviceIdentity(item) === targetIdentity)
  if (byIdentity) {
    return byIdentity
  }
  const targetFingerprint = buildDeviceFingerprint(target)
  return devices.find((item) => buildDeviceFingerprint(item) === targetFingerprint)
}

function formatNamedLabel(name: string | undefined | null, address: string): string {
  const trimmed = name?.trim()
  return trimmed ? `${trimmed}(${address})` : address
}

export function buildDeviceLabel(deviceInfo: ConnectableDevice): string {
  if (isAdbDevice(deviceInfo)) {
    return formatNamedLabel(deviceInfo.name, deviceInfo.address)
  }
  if (isWin32Device(deviceInfo) || isGamepadDevice(deviceInfo)) {
    const address = deviceInfo.class_name?.trim() || String(deviceInfo.hWnd)
    return formatNamedLabel(deviceInfo.window_name, address)
  }
  if (deviceInfo.type === "MacOS") {
    return formatNamedLabel(deviceInfo.window_name, String(deviceInfo.window_id))
  }
  return formatNamedLabel(deviceInfo.name, deviceInfo.address)
}

export function buildDeviceFingerprint(deviceInfo: ConnectableDevice): string {
  if (isAdbDevice(deviceInfo)) {
    return `adb|${deviceInfo.adb_path}|${deviceInfo.address}`
  }
  if (isWin32Device(deviceInfo)) {
    return `win32|${deviceInfo.hWnd}`
  }
  if (isGamepadDevice(deviceInfo)) {
    return `gamepad|${deviceInfo.hWnd}|${deviceInfo.gamepad_type}`
  }
  if (deviceInfo.type === "MacOS") {
    return `macos|${deviceInfo.window_id}`
  }
  if (deviceInfo.type === "Linux") {
    return `linux|${deviceInfo.address}`
  }
  return `playcover|${deviceInfo.address}|${deviceInfo.uuid || ""}`
}

export function getPlayCoverDefaultAddress(capabilities: DeviceControllerCapability[]): string {
  const playCoverCapability = capabilities.find((item) => item.type === "PlayCover")
  return playCoverCapability?.default_address || "127.0.0.1:1717"
}

export function getStoredDeviceFingerprint(stored: PanelLastConnectedDevice): string {
  if (stored.fingerprint) {
    return stored.fingerprint
  }
  const normalizedType = stored.type.toLowerCase()
  if (normalizedType === "adb") {
    return `adb|${stored.adb_path}|${stored.address}`
  }
  if (normalizedType === "win32") {
    return `win32|${stored.hWnd}`
  }
  if (normalizedType === "gamepad") {
    return `gamepad|${stored.hWnd}|${stored.gamepad_type}`
  }
  if (normalizedType === "macos") {
    return `macos|${stored.address}`
  }
  if (normalizedType === "linux") {
    return `linux|${stored.address}`
  }
  return `playcover|${stored.address}|${stored.uuid}`
}
