import { describe, expect, it, beforeEach, afterEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"

vi.mock("@/services/api", () => ({
  getTaskConfig: vi.fn<() => void>(),
  saveTaskConfig: vi.fn<() => void>(),
  resetTaskConfig: vi.fn<() => void>(),
}))

import { useTaskConfigStore } from "@/stores/task-config/taskConfig"
import { useInterfaceStore } from "@/stores/interface/interface"
import * as api from "@/services/api"
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
        entry: "shared-entry",
        option: ["difficulty", "params"],
      },
      {
        name: "Task B",
        entry: "shared-entry",
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
        task: [{ name: "Task B", enabled: true, option: { mode: ["manual"] } }],
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
  store.configLoaded = true
  return store
}

describe("useTaskConfigStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal("crypto", { randomUUID: vi.fn<() => string>(() => "mock-uuid") })
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
    expect(store.configLoadError).toBeNull()
    expect(store.saveTimer).toBeNull()
    expect(store.preTasks).toEqual([])
  })

  it("按任务列表顺序派生已勾选任务名称", () => {
    const store = useTaskConfigStore()
    store.taskList = [
      { id: "First", name: "First", order: 0, checked: true },
      { id: "Middle", name: "Middle", order: 1, checked: false },
      { id: "Last", name: "Last", order: 2, checked: true },
    ]

    expect(store.selectedTaskIds).toEqual(["First", "Last"])
  })

  describe("buildDefaultTaskList", () => {
    it("returns tasks from interface with checked=false", () => {
      const store = useTaskConfigStore()
      const list = store.buildDefaultTaskList()
      expect(list).toHaveLength(3)
      expect(list.map((t) => ({ id: t.id, name: t.name, checked: t.checked }))).toEqual([
        { id: "Task A", name: "Task A", checked: false },
        { id: "Task B", name: "Task B", checked: false },
        { id: "Task C", name: "Task C", checked: false },
      ])
    })
  })

  describe("selectPreset", () => {
    it("selects a preset, hydrates its snapshot and returns true", () => {
      const store = initTaskConfigStore()
      const result = store.selectPreset("preset1")

      expect(result).toBe(true)
      expect(store.selectedPresetName).toBe("preset1")
      expect(store.taskList.map((t) => t.id)).toEqual(["Task A", "Task B", "Task C"])
      expect(store.taskList.find((t) => t.id === "Task A")?.checked).toBe(true)
      expect(store.taskList.find((t) => t.id === "Task B")?.checked).toBe(false)
      expect(store.taskList.find((t) => t.id === "Task C")?.checked).toBe(false)
      expect(store.options["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "preset-host", port: "" },
      })
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

      store.taskList.find((t) => t.id === "Task B")!.checked = true
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "easy" }
      store.preTasks.push({ id: "pt1", command: "echo preset1", enabled: true, timeout: 30 })

      store.selectPreset(CUSTOM_PRESET_NAME)

      const preset1Snapshot = store.presetSnapshots["preset1"]
      expect(preset1Snapshot.taskChecked["Task B"]).toBe(true)
      expect(preset1Snapshot.taskOptions["Task A"]).toMatchObject({ difficulty: "easy" })
      expect(preset1Snapshot.preTasks).toHaveLength(1)
      expect(preset1Snapshot.preTasks[0].command).toBe("echo preset1")
    })

    it("syncs current state before switching between two real presets", () => {
      const store = initTaskConfigStore()
      store.selectPreset("preset1")

      store.taskList.find((t) => t.id === "Task C")!.checked = true
      store.options["Task B"] = { ...store.options["Task B"], mode: ["auto", "manual"] }

      const result = store.selectPreset("preset2")

      expect(result).toBe(true)
      const preset1Snapshot = store.presetSnapshots["preset1"]
      expect(preset1Snapshot.taskChecked["Task C"]).toBe(true)
      expect(preset1Snapshot.taskOptions["Task B"]).toMatchObject({ mode: ["auto", "manual"] })

      expect(store.selectedPresetName).toBe("preset2")
      expect(store.taskList.map((t) => t.id)).toEqual(["Task B", "Task A", "Task C"])
      expect(store.taskList.find((t) => t.id === "Task B")?.checked).toBe(true)
      expect(store.options["Task B"]).toEqual({ mode: ["manual"] })
    })
  })

  describe("serializeCurrentSnapshot", () => {
    it("serializes task order, checked state, merged options and a copy of preTasks", () => {
      const store = initTaskConfigStore()
      store.taskList = [store.taskList[2], store.taskList[0], store.taskList[1]]
      store.taskList[0].checked = true
      store.taskList[1].checked = true
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo hello", enabled: true, timeout: 30 }]

      const snapshot = store.serializeCurrentSnapshot()

      expect(snapshot.taskOrder).toEqual(["Task C", "Task A", "Task B"])
      expect(snapshot.taskChecked).toEqual({
        "Task C": true,
        "Task A": true,
        "Task B": false,
      })
      expect(snapshot.taskOptions["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "localhost", port: "" },
      })
      expect(snapshot.preTasks).toEqual(store.preTasks)
      expect(snapshot.preTasks).not.toBe(store.preTasks)
    })
  })

  describe("normalizeSnapshot", () => {
    it("returns a valid default snapshot when given undefined", () => {
      const store = initTaskConfigStore()
      const normalized = store.normalizeSnapshot(undefined)

      expect(normalized.taskOrder).toEqual(["Task A", "Task B", "Task C"])
      expect(normalized.taskChecked).toEqual({
        "Task A": false,
        "Task B": false,
        "Task C": false,
      })
      expect(normalized.taskOptions).toEqual({
        "Task A": {
          difficulty: "normal",
          params: { host: "localhost", port: "" },
        },
        "Task B": { mode: ["auto"] },
        "Task C": {},
      })
      expect(normalized.preTasks).toEqual([])
    })

    it("filters invalid preTasks and fills in missing defaults", () => {
      const store = initTaskConfigStore()
      const malformedPreTask = JSON.parse(
        '{"id":"has-id","command":"another","enabled":"yes","timeout":-1}',
      )
      const normalized = store.normalizeSnapshot({
        taskOrder: ["Task B"],
        taskChecked: { "Task B": true },
        taskOptions: { "Task B": { mode: ["manual"] } },
        preTasks: [
          { id: "", command: "", enabled: true, timeout: 30 },
          { id: "", command: "valid-command", enabled: false, timeout: 10 },
          malformedPreTask,
        ],
      })

      expect(normalized.preTasks).toHaveLength(2)
      expect(normalized.preTasks[0]).toEqual({
        id: "mock-uuid",
        command: "valid-command",
        enabled: false,
        timeout: 10,
      })
      expect(normalized.preTasks[1]).toEqual({
        id: "has-id",
        command: "another",
        enabled: true,
        timeout: 30,
      })
    })

    it("passes through valid preTasks as copies", () => {
      const store = initTaskConfigStore()
      const original = [{ id: "pt1", command: "echo ok", enabled: true, timeout: 30 }]
      const normalized = store.normalizeSnapshot({
        taskOrder: [],
        taskChecked: {},
        taskOptions: {},
        preTasks: original,
      })

      expect(normalized.preTasks).toEqual(original)
      expect(normalized.preTasks).not.toBe(original)
      expect(normalized.preTasks[0]).not.toBe(original[0])
    })
  })

  describe("hydrateSnapshot", () => {
    it("restores task list, options and preTasks from the snapshot", () => {
      const store = initTaskConfigStore()
      const snapshot = {
        taskOrder: ["Task C", "Task A", "Task B"],
        taskChecked: { "Task C": true, "Task A": true, "Task B": false },
        taskOptions: {
          "Task A": { difficulty: "hard", params: { host: "remote", port: "8080" } },
          "Task B": { mode: ["manual"] },
        },
        preTasks: [{ id: "pt1", command: "echo hydrate", enabled: true, timeout: 30 }],
      }

      store.hydrateSnapshot(snapshot)

      expect(store.taskList.map((t) => ({ id: t.id, checked: t.checked }))).toEqual([
        { id: "Task C", checked: true },
        { id: "Task A", checked: true },
        { id: "Task B", checked: false },
      ])
      expect(store.options["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "remote", port: "8080" },
      })
      expect(store.options["Task B"]).toEqual({ mode: ["manual"] })
      expect(store.preTasks).toEqual(snapshot.preTasks)
      expect(store.preTasks).not.toBe(snapshot.preTasks)
    })
  })

  describe("buildExecutionPayload", () => {
    it("returns normalized task list, merged options and a copy of preTasks", () => {
      const store = initTaskConfigStore()
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo run", enabled: true, timeout: 30 }]

      const payload = store.buildExecutionPayload(["Task A", "invalid-task", "Task B", "Task A"])

      expect(payload.task_identity).toBe("name")
      expect(payload.task_list).toEqual(["Task A", "Task B"])
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

  describe("buildOptionsFromPersisted", () => {
    it("merges defaults with persisted values, persisted wins when valid", () => {
      const store = initTaskConfigStore()
      const result = store.buildOptionsFromPersisted(["Task A"], {
        "Task A": { difficulty: "hard" },
      })

      expect(result["Task A"]).toEqual({
        difficulty: "hard",
        params: { host: "localhost", port: "" },
      })
    })

    it("filters unknown persisted keys", () => {
      const store = initTaskConfigStore()
      const result = store.buildOptionsFromPersisted(["Task A"], {
        "Task A": { difficulty: "hard", unknownKey: "ignored" },
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
    it("fetches config, seeds snapshots, hydrates selected preset and sets loaded", async () => {
      const store = useTaskConfigStore()
      vi.mocked(api.getTaskConfig).mockResolvedValue({
        ok: true,
        config: {
          taskIdentity: "name",
          selectedPreset: "preset2",
          presets: {
            preset2: {
              taskOrder: ["Task B"],
              taskChecked: { "Task B": true },
              taskOptions: { "Task B": { mode: ["manual"] } },
              preTasks: [],
            },
          },
        },
      })

      await store.loadConfig()

      expect(api.getTaskConfig).toHaveBeenCalledTimes(1)
      expect(store.selectedPresetName).toBe("preset2")
      expect(store.configLoaded).toBe(true)
      expect(store.configLoadError).toBeNull()
      expect(store.taskList.map((t) => t.id)).toEqual(["Task B", "Task A", "Task C"])
      expect(store.taskList.find((t) => t.id === "Task B")?.checked).toBe(true)
      expect(store.options["Task B"]).toEqual({ mode: ["manual"] })
    })

    it("keeps state unloaded and cancels auto-save when the API rejects an old config", async () => {
      vi.useFakeTimers()
      const store = initTaskConfigStore()
      const previousTaskList = store.taskList
      const previousPresetSnapshots = store.presetSnapshots
      store.debouncedSave()
      expect(store.saveTimer).not.toBeNull()

      vi.mocked(api.getTaskConfig).mockResolvedValue({
        ok: false,
        code: "task_config_format_unsupported",
        message: "taskIdentity is required",
      })

      await store.loadConfig()

      expect(store.configLoaded).toBe(false)
      expect(store.configLoadError).toEqual({
        code: "task_config_format_unsupported",
        message: "taskIdentity is required",
      })
      expect(store.taskList).toBe(previousTaskList)
      expect(store.presetSnapshots).toBe(previousPresetSnapshots)
      expect(store.saveTimer).toBeNull()

      await vi.advanceTimersByTimeAsync(500)
      expect(api.saveTaskConfig).not.toHaveBeenCalled()
      vi.useRealTimers()
    })
  })

  describe("resetConfig", () => {
    it("calls resetTaskConfig API and resets to custom preset with empty preTasks", async () => {
      const store = initTaskConfigStore()
      store.selectPreset("preset1")
      store.preTasks = [{ id: "pt1", command: "echo old", enabled: true, timeout: 30 }]
      vi.mocked(api.resetTaskConfig).mockResolvedValue(true)

      await store.resetConfig()

      expect(api.resetTaskConfig).toHaveBeenCalledTimes(1)
      expect(store.selectedPresetName).toBe(CUSTOM_PRESET_NAME)
      expect(store.configLoaded).toBe(true)
      expect(store.preTasks).toEqual([])
      expect(store.buildPersistedConfig().taskIdentity).toBe("name")
      expect(store.taskList.map((t) => t.id)).toEqual(["Task A", "Task B", "Task C"])
      expect(store.taskList.every((t) => !t.checked)).toBe(true)
    })
  })

  describe("syncCurrentPresetSnapshot", () => {
    it("updates the snapshot for the currently selected preset", () => {
      const store = initTaskConfigStore()
      store.taskList.find((t) => t.id === "Task A")!.checked = true
      store.options["Task A"] = { ...store.options["Task A"], difficulty: "hard" }
      store.preTasks = [{ id: "pt1", command: "echo sync", enabled: true, timeout: 30 }]

      store.syncCurrentPresetSnapshot()

      const snapshot = store.presetSnapshots[CUSTOM_PRESET_NAME]
      expect(snapshot.taskChecked["Task A"]).toBe(true)
      expect(snapshot.taskOptions["Task A"]).toMatchObject({ difficulty: "hard" })
      expect(snapshot.preTasks).toEqual(store.preTasks)
    })
  })
})
