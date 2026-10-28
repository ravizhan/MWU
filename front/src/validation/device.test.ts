import { describe, expect, it } from "vitest"

import { customDeviceAddressSchema, hostPortSchema, playCoverAddressSchema } from "./device"

describe("hostPortSchema", () => {
  it("accepts IPv4 and hostname addresses and trims input", () => {
    expect(hostPortSchema.parse("192.168.1.1:5555")).toBe("192.168.1.1:5555")
    expect(hostPortSchema.parse(" 10.0.0.1:5555 ")).toBe("10.0.0.1:5555")
    expect(hostPortSchema.parse("example.com:5555")).toBe("example.com:5555")
  })

  it("canonicalizes zero-padded IPv4 and port", () => {
    expect(hostPortSchema.parse("192.168.001.001:05555")).toBe("192.168.1.1:5555")
  })

  it.each([
    ["empty", ""],
    ["IPv6", "::1:5555"],
    ["URL", "http://192.168.1.1:5555"],
    ["missing port", "192.168.1.1"],
    ["port 0", "192.168.1.1:0"],
    ["port 65536", "192.168.1.1:65536"],
  ])("rejects %s", (_label, address) => {
    expect(hostPortSchema.safeParse(address).success).toBe(false)
  })
})

describe("customDeviceAddressSchema", () => {
  it.each([
    [
      "Adb IPv4",
      { type: "Adb", address: "10.0.0.1:5555" },
      { type: "Adb", address: "10.0.0.1:5555" },
    ],
    [
      "Adb hostname",
      { type: "Adb", address: "android-host.local:5555" },
      { type: "Adb", address: "android-host.local:5555" },
    ],
    [
      "PlayCover hostname",
      { type: "PlayCover", address: "mac.local:1717" },
      { type: "PlayCover", address: "mac.local:1717" },
    ],
    ["Win32", { type: "Win32", address: "0012345" }, { type: "Win32", address: "12345" }],
    ["Gamepad", { type: "Gamepad", address: "0012345|0" }, { type: "Gamepad", address: "12345|0" }],
    [
      "Linux",
      { type: "Linux", address: " /run/user/1000/wayland-1 " },
      { type: "Linux", address: "/run/user/1000/wayland-1" },
    ],
  ])("canonicalizes %s", (_label, input, expected) => {
    expect(customDeviceAddressSchema.parse(input)).toEqual(expected)
  })

  it.each([
    ["Adb serial", { type: "Adb", address: "emulator-5554" }],
    ["Win32 zero", { type: "Win32", address: "0" }],
    ["Gamepad type 2", { type: "Gamepad", address: "12345|2" }],
    ["empty Linux address", { type: "Linux", address: "   " }],
  ])("rejects %s", (_label, input) => {
    expect(customDeviceAddressSchema.safeParse(input).success).toBe(false)
  })
})

describe("playCoverAddressSchema", () => {
  it("accepts a valid host:port and rejects anything else", () => {
    expect(playCoverAddressSchema.parse("127.0.0.1:1717")).toBe("127.0.0.1:1717")
    expect(playCoverAddressSchema.safeParse("not-an-ip").success).toBe(false)
  })
})
