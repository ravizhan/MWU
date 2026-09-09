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
  GamepadDevice,
  LinuxDevice,
  MacOSDevice,
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

const macOSDevice: MacOSDevice = {
  type: "MacOS",
  window_id: 42,
  window_name: "MacOS window",
}

const linuxDevice: LinuxDevice = {
  type: "Linux",
  name: "Wayland compositor",
  address: '{"kind":"wlr","wlr_socket_path":"/run/user/1000/wayland-1"}',
}

describe("isAdbDevice", () => {
  it("returns true for Adb device", () => {
    expect(isAdbDevice(adbDevice)).toBe(true)
  })

  it("returns false for non-Adb device", () => {
    expect(isAdbDevice(win32Device)).toBe(false)
  })

  it("returns false for null", () => {
    expect(isAdbDevice(null)).toBe(false)
  })

  it("returns false for non-object", () => {
    expect(isAdbDevice("adb")).toBe(false)
  })
})

describe("isWin32Device", () => {
  it("returns true for Win32 device", () => {
    expect(isWin32Device(win32Device)).toBe(true)
  })

  it("returns false for non-Win32 device", () => {
    expect(isWin32Device(adbDevice)).toBe(false)
  })

  it("returns false for null", () => {
    expect(isWin32Device(null)).toBe(false)
  })

  it("returns false for non-object", () => {
    expect(isWin32Device(12345)).toBe(false)
  })
})

describe("isGamepadDevice", () => {
  it("returns true for Gamepad device", () => {
    expect(isGamepadDevice(gamepadDevice)).toBe(true)
  })

  it("returns false for non-Gamepad device", () => {
    expect(isGamepadDevice(win32Device)).toBe(false)
  })

  it("returns false for null", () => {
    expect(isGamepadDevice(null)).toBe(false)
  })

  it("returns false for non-object", () => {
    expect(isGamepadDevice(true)).toBe(false)
  })
})

describe("getDeviceIdentity", () => {
  it("returns address for Adb device", () => {
    expect(getDeviceIdentity(adbDevice)).toBe("127.0.0.1:5555")
  })

  it("returns hWnd string for Win32 device", () => {
    expect(getDeviceIdentity(win32Device)).toBe("12345")
  })

  it("returns hWnd|gamepad_type for Gamepad device", () => {
    expect(getDeviceIdentity(gamepadDevice)).toBe("67890|1")
  })

  it("returns address for PlayCover device", () => {
    expect(getDeviceIdentity(playCoverDevice)).toBe("127.0.0.1:1717")
  })

  it("returns CGWindowID for MacOS device", () => {
    expect(getDeviceIdentity(macOSDevice)).toBe("42")
  })

  it("returns address for Linux device", () => {
    expect(getDeviceIdentity(linuxDevice)).toBe(linuxDevice.address)
  })
})

describe("getStoredDeviceIdentity", () => {
  it("returns address for Adb stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Adb",
      address: "127.0.0.1:5555",
    } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(stored)).toBe("127.0.0.1:5555")
  })

  it("returns hWnd string for Win32 stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Win32",
      hWnd: 12345,
    } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(stored)).toBe("12345")
  })

  it("returns hWnd|gamepad_type for Gamepad stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Gamepad",
      hWnd: 67890,
      gamepad_type: 1,
    } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(stored)).toBe("67890|1")
  })

  it("returns address for PlayCover stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "PlayCover",
      address: "127.0.0.1:1717",
    } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(stored)).toBe("127.0.0.1:1717")
  })

  it("returns address for MacOS stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "MacOS",
      address: "42",
    } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(stored)).toBe("42")
  })

  it("returns address for Linux stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Linux",
      address: linuxDevice.address,
    } as PanelLastConnectedDevice
    expect(getStoredDeviceIdentity(stored)).toBe(linuxDevice.address)
  })
})

describe("storedDeviceMatchesController", () => {
  it("matches by controller_name when present", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Adb",
      controller_name: "adb",
    } as PanelLastConnectedDevice
    expect(storedDeviceMatchesController(stored, { name: "adb" })).toBe(true)
    expect(storedDeviceMatchesController(stored, { name: "other" })).toBe(false)
  })

  it("does not match by type when controller_name is empty", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Win32",
      controller_name: "",
    } as PanelLastConnectedDevice
    expect(storedDeviceMatchesController(stored, { name: "win32" })).toBe(false)
    expect(storedDeviceMatchesController(stored, { name: "adb" })).toBe(false)
  })
})

describe("findDeviceByIdentityOrFingerprint", () => {
  it("prefers identity match when fingerprint differs", () => {
    const custom: AdbDevice = { ...adbDevice, name: "", adb_path: "" }
    const scanned: AdbDevice = { ...adbDevice, name: "phone", adb_path: "/usr/bin/adb" }
    expect(findDeviceByIdentityOrFingerprint([scanned], custom)).toEqual(scanned)
  })

  it("falls back to fingerprint when identity differs", () => {
    const other: AdbDevice = { ...adbDevice, address: "10.0.0.1:5555" }
    expect(findDeviceByIdentityOrFingerprint([adbDevice], adbDevice)).toEqual(adbDevice)
    expect(findDeviceByIdentityOrFingerprint([other], adbDevice)).toBeUndefined()
  })

  it("returns undefined when neither matches", () => {
    const other: AdbDevice = { ...adbDevice, address: "10.0.0.1:5555", adb_path: "/other/adb" }
    expect(findDeviceByIdentityOrFingerprint([other], adbDevice)).toBeUndefined()
  })
})

describe("buildDeviceLabel", () => {
  it("returns name(address) for Adb device", () => {
    expect(buildDeviceLabel(adbDevice)).toBe("adb-device(127.0.0.1:5555)")
  })

  it("returns address only when Adb name is empty", () => {
    const device: AdbDevice = { ...adbDevice, name: "" }
    expect(buildDeviceLabel(device)).toBe("127.0.0.1:5555")
  })

  it("returns address only when Adb name is whitespace", () => {
    const device: AdbDevice = { ...adbDevice, name: "   " }
    expect(buildDeviceLabel(device)).toBe("127.0.0.1:5555")
  })

  it("returns window_name(class_name) for Win32 device", () => {
    expect(buildDeviceLabel(win32Device)).toBe("window-win32(class-win32)")
  })

  it("returns class_name when Win32 window_name is empty", () => {
    const device: Win32Device = { ...win32Device, window_name: "" }
    expect(buildDeviceLabel(device)).toBe("class-win32")
  })

  it("returns window_name(class_name) for Gamepad device", () => {
    expect(buildDeviceLabel(gamepadDevice)).toBe("window-gamepad(class-gamepad)")
  })

  it("returns name(address) for PlayCover device with name", () => {
    expect(buildDeviceLabel(playCoverDevice)).toBe("playcover-device(127.0.0.1:1717)")
  })

  it("returns address for PlayCover device without name", () => {
    const device: PlayCoverDevice = { type: "PlayCover", address: "127.0.0.1:1717" }
    expect(buildDeviceLabel(device)).toBe("127.0.0.1:1717")
  })
})

describe("buildDeviceFingerprint", () => {
  it("builds adb|adb_path|address for Adb device", () => {
    expect(buildDeviceFingerprint(adbDevice)).toBe("adb|/usr/bin/adb|127.0.0.1:5555")
  })

  it("builds win32|hWnd for Win32 device", () => {
    expect(buildDeviceFingerprint(win32Device)).toBe("win32|12345")
  })

  it("builds gamepad|hWnd|gamepad_type for Gamepad device", () => {
    expect(buildDeviceFingerprint(gamepadDevice)).toBe("gamepad|67890|1")
  })

  it("builds playcover|address|uuid for PlayCover device", () => {
    expect(buildDeviceFingerprint(playCoverDevice)).toBe("playcover|127.0.0.1:1717|uuid-001")
  })

  it("handles PlayCover device without uuid", () => {
    const device: PlayCoverDevice = { type: "PlayCover", address: "127.0.0.1:1717" }
    expect(buildDeviceFingerprint(device)).toBe("playcover|127.0.0.1:1717|")
  })

  it("builds macos|window-id for MacOS device", () => {
    expect(buildDeviceFingerprint(macOSDevice)).toBe("macos|42")
  })

  it("builds linux|address for Linux device", () => {
    expect(buildDeviceFingerprint(linuxDevice)).toBe(`linux|${linuxDevice.address}`)
  })
})

describe("getPlayCoverDefaultAddress", () => {
  it("returns default_address when PlayCover capability exists", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const capabilities = [
      { type: "Adb", default_address: "adb-addr" },
      { type: "PlayCover", default_address: "playcover-addr" },
    ] as never[]
    expect(getPlayCoverDefaultAddress(capabilities)).toBe("playcover-addr")
  })

  it("returns fallback when PlayCover capability is absent", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const capabilities = [{ type: "Adb", default_address: "adb-addr" }] as never[]
    expect(getPlayCoverDefaultAddress(capabilities)).toBe("127.0.0.1:1717")
  })
})

describe("getStoredDeviceFingerprint", () => {
  it("returns fingerprint when present", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = { fingerprint: "fp-001" } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(stored)).toBe("fp-001")
  })

  it("builds fingerprint for Adb stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Adb",
      adb_path: "/usr/bin/adb",
      address: "127.0.0.1:5555",
    } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(stored)).toBe("adb|/usr/bin/adb|127.0.0.1:5555")
  })

  it("builds fingerprint for Win32 stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Win32",
      hWnd: 12345,
    } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(stored)).toBe("win32|12345")
  })

  it("builds fingerprint for Gamepad stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Gamepad",
      hWnd: 67890,
      gamepad_type: 1,
    } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(stored)).toBe("gamepad|67890|1")
  })

  it("builds fingerprint for PlayCover stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "PlayCover",
      address: "127.0.0.1:1717",
      uuid: "uuid-001",
    } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(stored)).toBe("playcover|127.0.0.1:1717|uuid-001")
  })

  it("builds fingerprint for MacOS stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "MacOS",
      address: "42",
    } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(stored)).toBe("macos|42")
  })

  it("builds fingerprint for Linux stored device", () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const stored = {
      type: "Linux",
      address: linuxDevice.address,
    } as PanelLastConnectedDevice
    expect(getStoredDeviceFingerprint(stored)).toBe(`linux|${linuxDevice.address}`)
  })
})
