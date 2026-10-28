import { describe, expect, it, beforeEach, afterEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"

vi.mock("@/services/api", () => ({
  getTaskConfig: vi.fn<() => void>(),
  saveTaskConfig: vi.fn<() => void>(),
  resetTaskConfig: vi.fn<() => void>(),
}))

vi.mock("@/services/feedback/message", () => ({
  showGlobalMessage: vi.fn<() => void>(),
}))

vi.mock("@/app/i18n", () => ({
  default: { global: { t: (key: string) => key } },
}))

import { useTaskConfigStore } from "@/stores/task-config/taskConfig"
import { useInterfaceStore } from "@/stores/interface/interface"
import * as api from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { CUSTOM_PRESET_NAME } from "@/types/taskConfigModel"
import type { InterfaceModel } from "@/types/interfaceModel"

function buildTestInterface(): InterfaceModel {
  return {
    interface_version: 2,
    name: "test-interface",
    controller: [],
    resource: [],
    task: [
      {
        name: "Task A",
        entry: "task-a",
        option: ["difficulty", "params"],
      },
      {
        name: "Task B",
        entry: "task-b",
        option: ["mode"],
      },
      {
        name: "Task C",
        entry: "task-c",
        option: [],
      },
    ],
    option: {
      difficulty: {
        type: "select",
        cases: [{ name: "easy" }, { name: "normal" }, { name: "hard" }],
        default_case: "normal",
      },
      params: {
        type: "input",
        inputs: [
          { name: "host", default: "localhost" },
          { name: "port", default: "" },
        ],
      },
      mode: {
        type: "checkbox",
        cases: [{ name: "auto" }, { name: "manual" }],
        default_case: ["auto"],
      },
    },
    preset: [
      {
        name: "preset1",
        task: [
          {
            name: "Task A",
            enabled: true,
            option: { difficulty: "hard", params: { host: "preset-host" } },
          },
          { name: "Task B", enabled: false },
        ],
      },
      {
        name: "preset2",
        task: [
          { name: "Task B", enabled: true, option: { mode: ["manual"] } },
          { name: "Task B", enabled: true, option: { mode: ["manual"] } },
        ],
      },
    ],
  }
}

function setupInterface() {
  const interfaceStore = useInterfaceStore()
  interfaceStore.interface = buildTestInterface()
  return interfaceStore
}

function initTaskConfigStore() {
  const store = useTaskConfigStore()
  store.presetSnapshots = store.seedPresetSnapshots()
  store.hydrateSnapshot(store.presetSnapshots[CUSTOM_PRESET_NAME])
  return store
}

describe("useTaskConfigStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    let uuidCounter = 0
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn<() => string>(() => `mock-uuid-${++uuidCounter}`),
    })
    vi.clearAllMocks()
    setupInterface()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("has correct initial state", () => {
    const store = useTaskConfigStore()
    expect(store.options).toEqual({})
    expect(store.taskList).toEqual([])
    expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
    expect(store.presetSnapshots).toEqual({})
    expect(store.configLoaded).toBe(false)
    expect(store.saveTimer).toBeNull()
    expect(store.preTasks).toEqual([])
  })

  it("derives task IDs in queue order and keeps duplicate instances", () => {
    const store = initTaskConfigStore()
    store.taskList = store.buildQueueFromIds(["Task A", "Task A", "Task C"])

    expect(store.selectedTaskIds).toEqual(["Task A", "Task A", "Task C"])
  })

  describe("selectPreset", () => {
    it("hydrates only enabled preset tasks in declaration order", () => {
      const store = initTaskConfigStore()
      const result = store.selectPreset("preset1")

      expect(result).toBe(true)
      expect(store.selectedPresetName).toBe("preset1")
      expect(store.taskList.map((task) => task.id)).toEqual(["Task A"])
      expect(store.taskList[0]?.uid).toBeTruthy()
      expect(store.options["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "preset-host", port: "" },
      })
    })

    it("hydrates repeated preset entries as distinct queue instances", () => {
      const store = initTaskConfigStore()
      const result = store.selectPreset("preset2")

      expect(result).toBe(true)
      expect(store.taskList.map((task) => task.id)).toEqual(["Task B", "Task B"])
      expect(new Set(store.taskList.map((task) => task.uid)).size).toBe(2)
      expect(store.options["Task B"]).toEqual({ mode: ["manual"] })
    })

    it("returns false and leaves state unchanged for unknown presets", () => {
      const store = initTaskConfigStore()
      const previousState = store.serializeCurrentSnapshot()
      const result = store.selectPreset("nonexistent")

      expect(result).toBe(false)
      expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
      expect(store.serializeCurrentSnapshot()).toEqual(previousState)
    })

    it("returns true without changes when selecting the already-active preset", () => {
      const store = initTaskConfigStore()
      const previousState = store.serializeCurrentSnapshot()
      const result = store.selectPreset(CUSTOM_PRESET_NAME)

      expect(result).toBe(true)
      expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
      expect(store.serializeCurrentSnapshot()).toEqual(previousState)
    })

    it("syncs current state to the previous preset before switching to custom", () => {
      const store = initTaskConfigStore()
      store.selectPreset("preset1")

      store.taskList = store.buildQueueFromIds(["Task A", "Task B"])
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "easy" }
      store.preTasks.push({ id: "pt1", command: "echo preset1", enabled: true, timeout: 30 })

      store.selectPreset(CUSTOM_PRESET_NAME)

      const preset1Snapshot = store.presetSnapshots["preset1"]
      expect(preset1Snapshot.tasks).toEqual(["Task A", "Task B"])
      expect(preset1Snapshot.taskOptions["Task A"]).toMatchObject({ difficulty: "easy" })
      expect(preset1Snapshot.preTasks).toHaveLength(1)
      expect(preset1Snapshot.preTasks[0]?.command).toBe("echo preset1")
    })

    it("syncs current state before switching between two real presets", () => {
      const store = initTaskConfigStore()
      store.selectPreset("preset1")

      store.taskList = store.buildQueueFromIds(["Task B", "Task C"])
      store.options["Task B"] = { ...store.options["Task B"], mode: ["auto", "manual"] }

      const result = store.selectPreset("preset2")

      expect(result).toBe(true)
      const preset1Snapshot = store.presetSnapshots["preset1"]
      expect(preset1Snapshot.tasks).toEqual(["Task B", "Task C"])
      expect(preset1Snapshot.taskOptions["Task B"]).toMatchObject({ mode: ["auto", "manual"] })

      expect(store.selectedPresetName).toBe("preset2")
      expect(store.taskList.map((task) => task.id)).toEqual(["Task B", "Task B"])
      expect(store.options["Task B"]).toEqual({ mode: ["manual"] })
    })
  })

  describe("serializeCurrentSnapshot", () => {
    it("serializes ordered duplicate task IDs, merged options and copied preTasks", () => {
      const store = initTaskConfigStore()
      store.taskList = store.buildQueueFromIds(["Task C", "Task A", "Task A", "Task B"])
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo hello", enabled: true, timeout: 30 }]

      const snapshot = store.serializeCurrentSnapshot()

      expect(snapshot.tasks).toEqual(["Task C", "Task A", "Task A", "Task B"])
      expect(snapshot.taskOptions["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "localhost", port: "" },
      })
      expect(snapshot.preTasks).toEqual(store.preTasks)
      expect(snapshot.preTasks).not.toBe(store.preTasks)

      store.taskList = []
      store.hydrateSnapshot(snapshot)
      expect(store.taskList.map((task) => task.id)).toEqual([
        "Task C",
        "Task A",
        "Task A",
        "Task B",
      ])
      expect(new Set(store.taskList.map((task) => task.uid)).size).toBe(4)
    })
  })

  describe("hydrateSnapshot", () => {
    it("restores ordered duplicate instances, options and preTasks", () => {
      const store = initTaskConfigStore()
      const snapshot = {
        tasks: ["Task C", "Task A", "Task A", "invalid-task"],
        taskOptions: {
          "Task A": { difficulty: "hard", params: { host: "remote", port: "8080" } },
        },
        preTasks: [{ id: "pt1", command: "echo hydrate", enabled: true, timeout: 30 }],
      }

      store.hydrateSnapshot(snapshot)

      expect(store.taskList.map((task) => task.id)).toEqual(["Task C", "Task A", "Task A"])
      expect(new Set(store.taskList.map((task) => task.uid)).size).toBe(3)
      expect(store.options["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "remote", port: "8080" },
      })
      expect(store.preTasks).toEqual(snapshot.preTasks)
      expect(store.preTasks).not.toBe(snapshot.preTasks)
    })
  })

  describe("buildExecutionPayload", () => {
    it("returns normalized duplicate task IDs, merged options and copied preTasks", () => {
      const store = initTaskConfigStore()
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo run", enabled: true, timeout: 30 }]

      const payload = store.buildExecutionPayload(["Task A", "invalid-task", "Task B", "Task A"])

      expect(payload.task_list).toEqual(["Task A", "Task B", "Task A"])
      expect(payload.task_options).toEqual({
        "Task A": {
          difficulty: "hard",
          params: { host: "localhost", port: "" },
        },
        "Task B": { mode: ["auto"] },
      })
      expect(payload.preTasks).toEqual(store.preTasks)
      expect(payload.preTasks).not.toBe(store.preTasks)
    })
  })

  describe("buildOptionsForTasks", () => {
    it("merges defaults, current values and overrides with overrides winning", () => {
      const store = initTaskConfigStore()
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "easy" }

      const result = store.buildOptionsForTasks(["Task A"], {
        "Task A": { difficulty: "hard", params: { host: "override-host" } },
      })

      expect(result["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "override-host" },
      })
    })

    it("ignores option keys that are not present in defaults", () => {
      const store = initTaskConfigStore()
      const result = store.buildOptionsForTasks(["Task A"], {
        "Task A": { unknownKey: "ignored" },
      })

      expect(result["Task A"]).not.toHaveProperty("unknownKey")
    })
  })

  describe("debouncedSave", () => {
    it("calls saveConfig after a 500ms delay", async () => {
      vi.useFakeTimers()
      const store = initTaskConfigStore()
      const saveSpy = vi.spyOn(store, "saveConfig").mockResolvedValue(undefined)

      store.debouncedSave()
      expect(saveSpy).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(500)
      expect(saveSpy).toHaveBeenCalledTimes(1)

      vi.useRealTimers()
    })

    it("cancels the previous timer when called again within 500ms", async () => {
      vi.useFakeTimers()
      const store = initTaskConfigStore()
      const saveSpy = vi.spyOn(store, "saveConfig").mockResolvedValue(undefined)

      store.debouncedSave()
      await vi.advanceTimersByTimeAsync(250)
      store.debouncedSave()
      await vi.advanceTimersByTimeAsync(250)

      expect(saveSpy).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(250)
      expect(saveSpy).toHaveBeenCalledTimes(1)

      vi.useRealTimers()
    })
  })

  describe("loadConfig", () => {
    it("trusts the server-normalized config and hydrates the selected preset", async () => {
      const store = useTaskConfigStore()
      vi.mocked(api.getTaskConfig).mockResolvedValue({
        selectedPreset: "preset2",
        presets: {
          preset2: {
            tasks: ["Task B"],
            taskOptions: { "Task B": { mode: ["manual"] } },
            preTasks: [],
          },
        },
      })

      await store.loadConfig()

      expect(api.getTaskConfig).toHaveBeenCalledTimes(1)
      expect(store.selectedPresetName).toBe("preset2")
      expect(store.configLoaded).toBe(true)
      expect(store.taskList.map((task) => task.id)).toEqual(["Task B"])
      expect(store.options["Task B"]).toEqual({ mode: ["manual"] })
    })

    it("keeps autosave disabled and reports the failure when loading fails", async () => {
      const store = useTaskConfigStore()
      vi.mocked(api.getTaskConfig).mockRejectedValue(new Error("boom"))

      await store.loadConfig()

      expect(store.configLoaded).toBe(false)
      expect(store.presetSnapshots).toEqual({})
      expect(store.taskList).toEqual([])
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.taskConfigLoadFailed")
    })
  })

  describe("resetConfig", () => {
    it("resets to the first interface preset with empty preTasks", async () => {
      const store = initTaskConfigStore()
      store.selectPreset("preset2")
      store.preTasks = [{ id: "pt1", command: "echo old", enabled: true, timeout: 30 }]
      vi.mocked(api.resetTaskConfig).mockResolvedValue(true)

      await store.resetConfig()

      expect(api.resetTaskConfig).toHaveBeenCalledTimes(1)
      expect(store.selectedPresetName).toBe("preset1")
      expect(store.preTasks).toEqual([])
      expect(store.taskList.map((task) => task.id)).toEqual(["Task A"])
      expect(store.options["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "preset-host", port: "" },
      })
    })
  })

  describe("syncCurrentPresetSnapshot", () => {
    it("updates the snapshot for the currently selected preset", () => {
      const store = initTaskConfigStore()
      store.taskList = store.buildQueueFromIds(["Task A"])
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo sync", enabled: true, timeout: 30 }]

      store.syncCurrentPresetSnapshot()

      const snapshot = store.presetSnapshots[CUSTOM_PRESET_NAME]
      expect(snapshot.tasks).toEqual(["Task A"])
      expect(snapshot.taskOptions["Task A"]).toMatchObject({ difficulty: "hard" })
      expect(snapshot.preTasks).toEqual(store.preTasks)
    })
  })
})
