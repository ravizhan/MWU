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

/**
 * Match a device by fingerprint or by semantic identity.
 * Fingerprints are `type|...` strings; identities are addresses/handles
 * (Gamepad identities also contain "|", so callers must pick the field explicitly).
 */
export function matchDevice(
  devices: ConnectableDevice[],
  key: string | null | undefined,
  order: "fingerprint" | "identity",
): ConnectableDevice | undefined {
  if (!key) {
    return undefined
  }
  return devices.find((item) =>
    order === "fingerprint"
      ? buildDeviceFingerprint(item) === key
      : getDeviceIdentity(item) === key,
  )
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

/**
 * Expand a persisted snapshot into the ConnectableDevice shape so identity and
 * fingerprint derivation stay shared with scanned devices. Only the fields read
 * by getDeviceIdentity/buildDeviceFingerprint carry meaning; the rest are
 * placeholders. MacOS stores its CGWindowID in `address`, which canonicalizes to
 * the same `macos|<window_id>` fingerprint the scan path produces.
 */
function storedToDevice(stored: PanelLastConnectedDevice): ConnectableDevice {
  if (stored.type === "Adb") {
    return {
      type: "Adb",
      name: stored.window_name,
      adb_path: stored.adb_path,
      address: stored.address,
      screencap_methods: 0,
      input_methods: 0,
      config: {},
    }
  }
  if (stored.type === "Win32") {
    return {
      type: "Win32",
      hWnd: stored.hWnd,
      class_name: stored.class_name,
      window_name: stored.window_name,
      screencap_methods: 0,
      input_methods: 0,
    }
  }
  if (stored.type === "Gamepad") {
    return {
      type: "Gamepad",
      hWnd: stored.hWnd,
      class_name: stored.class_name,
      window_name: stored.window_name,
      screencap_methods: 0,
      gamepad_type: stored.gamepad_type,
    }
  }
  if (stored.type === "MacOS") {
    return {
      type: "MacOS",
      window_id: Number(stored.address),
      window_name: stored.window_name,
    }
  }
  if (stored.type === "Linux") {
    return { type: "Linux", name: stored.window_name, address: stored.address }
  }
  return {
    type: "PlayCover",
    name: stored.window_name,
    address: stored.address,
    uuid: stored.uuid,
  }
}

/** Stable identity for a persisted last-connected snapshot (same semantics as getDeviceIdentity). */
export function getStoredDeviceIdentity(stored: PanelLastConnectedDevice): string {
  return getDeviceIdentity(storedToDevice(stored))
}

export function getStoredDeviceFingerprint(stored: PanelLastConnectedDevice): string {
  if (stored.fingerprint) {
    return stored.fingerprint
  }
  return buildDeviceFingerprint(storedToDevice(stored))
}
