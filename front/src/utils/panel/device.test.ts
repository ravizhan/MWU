import { describe, expect, it } from "vitest"
import {
  isAdbDevice,
  isWin32Device,
  isGamepadDevice,
  buildDeviceLabel,
  buildDeviceFingerprint,
  findDeviceByIdentityOrFingerprint,
  getDeviceIdentity,
  getPlayCoverDefaultAddress,
  getStoredDeviceFingerprint,
  getStoredDeviceIdentity,
  storedDeviceMatchesController,
} from "@/utils/panel/device"
import type {
  AdbDevice,
  ConnectableDevice,
  DeviceControllerCapability,
  GamepadDevice,
  LinuxDevice,
  PlayCoverDevice,
  Win32Device,
} from "@/services/api"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"

const adbDevice: AdbDevice = {
  type: "Adb",
  name: "adb-device",
  adb_path: "/usr/bin/adb",
  address: "127.0.0.1:5555",
  screencap_methods: 0,
  input_methods: 0,
  config: {},
}

const win32Device: Win32Device = {
  type: "Win32",
  hWnd: 12345,
  class_name: "class-win32",
  window_name: "window-win32",
  screencap_methods: 0,
  input_methods: 0,
}

const gamepadDevice: GamepadDevice = {
  type: "Gamepad",
  hWnd: 67890,
  class_name: "class-gamepad",
  window_name: "window-gamepad",
  screencap_methods: 0,
  gamepad_type: 1,
}

const playCoverDevice: PlayCoverDevice = {
  type: "PlayCover",
  name: "playcover-device",
  address: "127.0.0.1:1717",
  uuid: "uuid-001",
}

const linuxDevice: LinuxDevice = {
  type: "Linux",
  name: "Wayland compositor",
  address: "/run/user/1000/wayland-1",
}

function makeStored(overrides: Partial<PanelLastConnectedDevice>): PanelLastConnectedDevice {
  return {
    type: "Adb",
    controller_name: "",
    fingerprint: "",
    adb_path: "",
    address: "",
    class_name: "",
    window_name: "",
    hWnd: 0,
    gamepad_type: 0,
    uuid: "",
    ...overrides,
  }
}

describe("device type guards", () => {
  it("identify each device type", () => {
    expect(isAdbDevice(adbDevice)).toBe(true)
    expect(isWin32Device(win32Device)).toBe(true)
    expect(isGamepadDevice(gamepadDevice)).toBe(true)
  })

  it("reject other types and non-device values", () => {
    expect(isAdbDevice(win32Device)).toBe(false)
    expect(isWin32Device(adbDevice)).toBe(false)
    expect(isGamepadDevice(win32Device)).toBe(false)
    expect(isAdbDevice(null)).toBe(false)
    expect(isWin32Device(12345)).toBe(false)
    expect(isGamepadDevice("gamepad")).toBe(false)
  })
})

describe("getDeviceIdentity", () => {
  const cases: Array<[string, ConnectableDevice, string]> = [
    ["Adb address", adbDevice, "127.0.0.1:5555"],
    ["Win32 hWnd", win32Device, "12345"],
    ["Gamepad hWnd|type", gamepadDevice, "67890|1"],
    ["PlayCover address", playCoverDevice, "127.0.0.1:1717"],
    ["Linux socket path", linuxDevice, "/run/user/1000/wayland-1"],
  ]

  it.each(cases)("uses the %s", (_label, device, expected) => {
    expect(getDeviceIdentity(device)).toBe(expected)
  })
})

describe("getStoredDeviceIdentity", () => {
  const cases: Array<[string, PanelLastConnectedDevice, string]> = [
    ["Adb", makeStored({ type: "Adb", address: "127.0.0.1:5555" }), "127.0.0.1:5555"],
    ["Win32", makeStored({ type: "Win32", hWnd: 12345 }), "12345"],
    ["Gamepad", makeStored({ type: "Gamepad", hWnd: 67890, gamepad_type: 1 }), "67890|1"],
    ["PlayCover", makeStored({ type: "PlayCover", address: "127.0.0.1:1717" }), "127.0.0.1:1717"],
  ]

  it.each(cases)("uses the %s identity", (_type, stored, expected) => {
    expect(getStoredDeviceIdentity(stored)).toBe(expected)
  })
})

describe("storedDeviceMatchesController", () => {
  it("matches only the stored controller name", () => {
    const stored = makeStored({ type: "Adb", controller_name: "adb" })
    expect(storedDeviceMatchesController(stored, { name: "adb" })).toBe(true)
    expect(storedDeviceMatchesController(stored, { name: "win32" })).toBe(false)
  })

  it("does not fall back to the device type when controller_name is empty", () => {
    const stored = makeStored({ type: "Win32" })
    expect(storedDeviceMatchesController(stored, { name: "win32" })).toBe(false)
  })
})

describe("findDeviceByIdentityOrFingerprint", () => {
  it("prefers identity match when fingerprint differs", () => {
    const custom: AdbDevice = { ...adbDevice, name: "", adb_path: "" }
    const scanned: AdbDevice = { ...adbDevice, name: "phone", adb_path: "/usr/bin/adb" }
    expect(findDeviceByIdentityOrFingerprint([scanned], custom)).toEqual(scanned)
  })

  it("returns undefined when neither identity nor fingerprint matches", () => {
    const other: AdbDevice = { ...adbDevice, address: "10.0.0.1:5555", adb_path: "/other/adb" }
    expect(findDeviceByIdentityOrFingerprint([other], adbDevice)).toBeUndefined()
  })
})

describe("buildDeviceLabel", () => {
  const cases: Array<[string, ConnectableDevice, string]> = [
    ["Adb with name", adbDevice, "adb-device(127.0.0.1:5555)"],
    ["Adb without name", { ...adbDevice, name: "   " }, "127.0.0.1:5555"],
    ["Win32", win32Device, "window-win32(class-win32)"],
    ["Win32 without window name", { ...win32Device, window_name: "" }, "class-win32"],
    ["Gamepad", gamepadDevice, "window-gamepad(class-gamepad)"],
    ["PlayCover with name", playCoverDevice, "playcover-device(127.0.0.1:1717)"],
    ["PlayCover without name", { type: "PlayCover", address: "127.0.0.1:1717" }, "127.0.0.1:1717"],
  ]

  it.each(cases)("labels %s", (_label, device, expected) => {
    expect(buildDeviceLabel(device)).toBe(expected)
  })
})

describe("buildDeviceFingerprint", () => {
  const cases: Array<[string, ConnectableDevice, string]> = [
    ["Adb", adbDevice, "adb|/usr/bin/adb|127.0.0.1:5555"],
    ["Win32", win32Device, "win32|12345"],
    ["Gamepad", gamepadDevice, "gamepad|67890|1"],
    ["PlayCover", playCoverDevice, "playcover|127.0.0.1:1717|uuid-001"],
    [
      "PlayCover without uuid",
      { type: "PlayCover", address: "127.0.0.1:1717" },
      "playcover|127.0.0.1:1717|",
    ],
    ["Linux", linuxDevice, "linux|/run/user/1000/wayland-1"],
  ]

  it.each(cases)("builds the %s fingerprint", (_label, device, expected) => {
    expect(buildDeviceFingerprint(device)).toBe(expected)
  })
})

describe("getPlayCoverDefaultAddress", () => {
  function capability(type: DeviceControllerCapability["type"], defaultAddress: string) {
    const capability: DeviceControllerCapability = {
      name: type.toLowerCase(),
      type,
      label: type,
      display_label: type,
      enabled: true,
      reason: "",
      search_mode: "select",
      default_address: defaultAddress,
    }
    return capability
  }

  it("uses the PlayCover capability address when present", () => {
    const capabilities = [capability("Adb", "adb-addr"), capability("PlayCover", "playcover-addr")]
    expect(getPlayCoverDefaultAddress(capabilities)).toBe("playcover-addr")
  })

  it("falls back when no PlayCover capability exists", () => {
    expect(getPlayCoverDefaultAddress([capability("Adb", "adb-addr")])).toBe("127.0.0.1:1717")
  })
})

describe("getStoredDeviceFingerprint", () => {
  it("prefers the stored fingerprint", () => {
    expect(getStoredDeviceFingerprint(makeStored({ fingerprint: "fp-001" }))).toBe("fp-001")
  })

  it("rebuilds the fingerprint when absent", () => {
    const stored = makeStored({ type: "Adb", adb_path: "/usr/bin/adb", address: "127.0.0.1:5555" })
    expect(getStoredDeviceFingerprint(stored)).toBe("adb|/usr/bin/adb|127.0.0.1:5555")
  })
})
