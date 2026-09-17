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

  it("accepts and trims a Linux device address", () => {
    expect(
      customDeviceAddressSchema.parse({
        type: "Linux",
        address: " /run/user/1000/wayland-1 ",
      }),
    ).toEqual({ type: "Linux", address: "/run/user/1000/wayland-1" })
  })

  it("rejects an empty Linux device address", () => {
    expect(customDeviceAddressSchema.safeParse({ type: "Linux", address: "   " }).success).toBe(
      false,
    )
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

  it("accepts a scanned Linux device address", () => {
    expect(runtimeDeviceAddressSchema.parse({ type: "Linux", address: " wayland-1 " })).toEqual({
      type: "Linux",
      address: "wayland-1",
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
