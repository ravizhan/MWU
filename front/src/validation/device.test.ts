import { describe, expect, it } from "vitest"

import {
  customDeviceAddressSchema,
  hostPortSchema,
  playCoverAddressSchema,
  runtimeDeviceAddressSchema,
} from "./device"

describe("hostPortSchema", () => {
  it("accepts valid IPv4:port", () => {
    expect(hostPortSchema.parse("192.168.1.1:5555")).toBe("192.168.1.1:5555")
  })

  it("trims whitespace", () => {
    expect(hostPortSchema.parse(" 10.0.0.1:5555 ")).toBe("10.0.0.1:5555")
  })

  it("canonicalizes zero-padded IPv4 and port", () => {
    expect(hostPortSchema.parse("192.168.001.001:05555")).toBe("192.168.1.1:5555")
  })

  it("accepts a valid hostname", () => {
    expect(hostPortSchema.parse("example.com:5555")).toBe("example.com:5555")
  })

  it("rejects empty", () => {
    expect(hostPortSchema.safeParse("").success).toBe(false)
  })

  it("rejects IPv6", () => {
    expect(hostPortSchema.safeParse("::1:5555").success).toBe(false)
  })

  it("rejects URL", () => {
    expect(hostPortSchema.safeParse("http://192.168.1.1:5555").success).toBe(false)
  })

  it("rejects missing port", () => {
    expect(hostPortSchema.safeParse("192.168.1.1").success).toBe(false)
  })

  it("rejects port 0", () => {
    expect(hostPortSchema.safeParse("192.168.1.1:0").success).toBe(false)
  })

  it("rejects port 65536", () => {
    expect(hostPortSchema.safeParse("192.168.1.1:65536").success).toBe(false)
  })
})

describe("customDeviceAddressSchema", () => {
  it("accepts Adb with IPv4", () => {
    const r = customDeviceAddressSchema.safeParse({ type: "Adb", address: "10.0.0.1:5555" })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.address).toBe("10.0.0.1:5555")
  })

  it("accepts Adb with hostname", () => {
    const result = customDeviceAddressSchema.parse({
      type: "Adb",
      address: "android-host.local:5555",
    })
    expect(result.address).toBe("android-host.local:5555")
  })

  it("rejects Adb with serial", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "Adb", address: "emulator-5554" }).success,
    ).toBe(false)
  })

  it("accepts PlayCover with IPv4", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "PlayCover", address: "127.0.0.1:1717" }).success,
    ).toBe(true)
  })

  it("accepts PlayCover with hostname", () => {
    expect(
      customDeviceAddressSchema.parse({ type: "PlayCover", address: "mac.local:1717" }),
    ).toEqual({ type: "PlayCover", address: "mac.local:1717" })
  })

  it("accepts Win32 with positive integer", () => {
    expect(customDeviceAddressSchema.parse({ type: "Win32", address: "0012345" })).toEqual({
      type: "Win32",
      address: "12345",
    })
  })

  it("rejects Win32 with zero", () => {
    expect(customDeviceAddressSchema.safeParse({ type: "Win32", address: "0" }).success).toBe(false)
  })

  it("accepts Gamepad with hWnd|0", () => {
    expect(customDeviceAddressSchema.parse({ type: "Gamepad", address: "0012345|0" })).toEqual({
      type: "Gamepad",
      address: "12345|0",
    })
  })

  it("accepts Gamepad with hWnd|1", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "Gamepad", address: "12345|1" }).success,
    ).toBe(true)
  })

  it("rejects Gamepad with invalid type", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "Gamepad", address: "12345|2" }).success,
    ).toBe(false)
  })

  it("accepts and canonicalizes a MacOS CGWindowID", () => {
    expect(customDeviceAddressSchema.parse({ type: "MacOS", address: " 0042 " })).toEqual({
      type: "MacOS",
      address: "42",
    })
  })

  it("rejects a non-positive MacOS CGWindowID", () => {
    expect(customDeviceAddressSchema.safeParse({ type: "MacOS", address: "0" }).success).toBe(false)
  })

  it("accepts and canonicalizes a Linux Wlr address", () => {
    expect(
      customDeviceAddressSchema.parse({
        type: "Linux",
        address: '{ "wlr_socket_path": " /run/user/1000/wayland-1 ", "kind": "wlr" }',
      }),
    ).toEqual({
      type: "Linux",
      address: '{"kind": "wlr", "wlr_socket_path": "/run/user/1000/wayland-1"}',
    })
  })

  it("accepts a Linux portal address without a runtime socket", () => {
    expect(
      customDeviceAddressSchema.parse({ type: "Linux", address: '{"kind":"portal"}' }),
    ).toEqual({ type: "Linux", address: '{"kind": "portal"}' })
  })

  it("adds the default UInput path when dimensions are provided", () => {
    expect(
      customDeviceAddressSchema.parse({
        type: "Linux",
        address:
          '{"kind":"gamescope","display_no":0,"uinput_screen_width":1920,"uinput_screen_height":1080}',
      }),
    ).toEqual({
      type: "Linux",
      address:
        '{"display_no": 0, "kind": "gamescope", "uinput_path": "/dev/uinput", "uinput_screen_height": 1080, "uinput_screen_width": 1920}',
    })
  })

  it("rejects Linux addresses with missing kind-specific fields", () => {
    expect(
      customDeviceAddressSchema.safeParse({ type: "Linux", address: '{"kind":"wlr"}' }).success,
    ).toBe(false)
    expect(
      customDeviceAddressSchema.safeParse({ type: "Linux", address: '{"kind":"gamescope"}' })
        .success,
    ).toBe(false)
    expect(
      customDeviceAddressSchema.safeParse({
        type: "Linux",
        address: '{"kind":"portal","uinput_screen_width":1920}',
      }).success,
    ).toBe(false)
  })

  it("rejects unknown Linux address fields", () => {
    expect(
      customDeviceAddressSchema.safeParse({
        type: "Linux",
        address: '{"kind":"portal","runtime_fd":3}',
      }).success,
    ).toBe(false)
  })
})

describe("runtimeDeviceAddressSchema", () => {
  it("accepts Adb with serial", () => {
    const r = runtimeDeviceAddressSchema.safeParse({ type: "Adb", address: "emulator-5554" })
    expect(r.success).toBe(true)
    if (r.success) expect(r.data.address).toBe("emulator-5554")
  })

  it("accepts Adb with IPv4", () => {
    expect(
      runtimeDeviceAddressSchema.safeParse({ type: "Adb", address: "192.168.1.1:5555" }).success,
    ).toBe(true)
  })

  it("rejects Adb with empty", () => {
    expect(runtimeDeviceAddressSchema.safeParse({ type: "Adb", address: "" }).success).toBe(false)
  })

  it("rejects PlayCover with serial", () => {
    expect(
      runtimeDeviceAddressSchema.safeParse({ type: "PlayCover", address: "emulator-5554" }).success,
    ).toBe(false)
  })

  it("accepts a scanned MacOS CGWindowID", () => {
    expect(runtimeDeviceAddressSchema.parse({ type: "MacOS", address: " 0042 " })).toEqual({
      type: "MacOS",
      address: "42",
    })
  })

  it("canonicalizes a scanned Linux address", () => {
    expect(
      runtimeDeviceAddressSchema.parse({
        type: "Linux",
        address: '{ "kind": "gamescope", "display_no": 0 }',
      }),
    ).toEqual({
      type: "Linux",
      address: '{"display_no": 0, "kind": "gamescope"}',
    })
  })

  it("accepts a lenient scanned Linux address before connection details are filled", () => {
    expect(runtimeDeviceAddressSchema.parse({ type: "Linux", address: '{"kind":"wlr"}' })).toEqual({
      type: "Linux",
      address: '{"kind": "wlr"}',
    })
  })
})

describe("playCoverAddressSchema", () => {
  it("accepts valid", () => {
    expect(playCoverAddressSchema.parse("127.0.0.1:1717")).toBe("127.0.0.1:1717")
  })

  it("rejects invalid", () => {
    expect(playCoverAddressSchema.safeParse("not-an-ip").success).toBe(false)
  })
})
