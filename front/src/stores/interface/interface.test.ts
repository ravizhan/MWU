import { beforeEach, describe, expect, it } from "vitest"
import { createPinia, setActivePinia } from "pinia"

import { useInterfaceStore } from "@/stores/interface/interface"
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

  function setupInterface() {
    const store = useInterfaceStore()
    store.interface = {
      task: [
        {
          name: "task-one",
          entry: "shared-entry",
          option: ["difficulty"],
        },
        {
          name: "task-two",
          entry: "shared-entry",
          controller: ["adb"],
          option: ["mode"],
        },
      ],
      option: {
        difficulty: {
          type: "select",
          cases: [{ name: "easy" }],
        },
        mode: {
          type: "select",
          cases: [{ name: "safe" }],
        },
      },
    }
    return store
  }

  describe("task identity", () => {
    it("uses task names as task list ids", () => {
      const store = setupInterface()

      expect(store.getTaskList.map((item) => item.id)).toEqual(["task-one", "task-two"])
    })

    it("finds tasks by name", () => {
      const store = setupInterface()

      expect(store.getTaskByName("task-two")?.entry).toBe("shared-entry")
      expect(store.getTaskByName("missing")).toBeNull()
    })

    it("checks compatibility by task name", () => {
      const store = setupInterface()

      expect(store.isTaskCompatibleByName("task-two", "adb")).toBe(true)
      expect(store.isTaskCompatibleByName("task-two", "win32")).toBe(false)
    })

    it("gets options by task name", () => {
      const store = setupInterface()

      expect(Object.keys(store.getOptionList("task-two"))).toEqual(["mode"])
    })
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
