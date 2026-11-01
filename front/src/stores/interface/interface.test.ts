import { beforeEach, describe, expect, it } from "vitest"
import { createPinia, setActivePinia } from "pinia"

import { pretaskKey, useInterfaceStore } from "@/stores/interface/interface"
import type { Pretask } from "@/types/interfaceModel"

const matchingPretask: Pretask = {
  exec: "prepare.exe",
  controller: ["adb"],
  resource: ["resource-a"],
}

const controllerMismatchPretask: Pretask = {
  exec: "prepare.exe",
  controller: ["other-controller"],
  resource: ["resource-a"],
}

const resourceMismatchPretask: Pretask = {
  exec: "prepare.exe",
  controller: ["adb"],
  resource: ["other-resource"],
}

const undefinedContextPretask: Pretask = {
  exec: "prepare.exe",
  controller: ["adb"],
  resource: ["resource-a"],
}

describe("useInterfaceStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it("keys unnamed pretasks by argv in the backend's format", () => {
    // 与 tests/unit/test_interface_loader.py 的 Pretask.key 期望值逐字一致
    expect(pretaskKey({ exec: "run", args: ["a b"] })).toBe('["run","a b"]')
    expect(pretaskKey({ exec: "run", args: ["a", "b"] })).toBe('["run","a","b"]')
    expect(pretaskKey({ exec: "python" })).toBe('["python"]')
  })

  describe("isPretaskCompatible", () => {
    it("returns true when controller and resource match", () => {
      const store = useInterfaceStore()

      expect(store.isPretaskCompatible(matchingPretask, "adb", "resource-a")).toBe(true)
    })

    it("returns false when the controller does not match", () => {
      const store = useInterfaceStore()

      expect(store.isPretaskCompatible(controllerMismatchPretask, "adb", "resource-a")).toBe(false)
    })

    it("returns false when the resource does not match", () => {
      const store = useInterfaceStore()

      expect(store.isPretaskCompatible(resourceMismatchPretask, "adb", "resource-a")).toBe(false)
    })

    it("returns true when the context is undefined", () => {
      const store = useInterfaceStore()

      expect(store.isPretaskCompatible(undefinedContextPretask, undefined, undefined)).toBe(true)
    })
  })
})
