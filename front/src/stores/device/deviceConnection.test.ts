import { describe, expect, it, beforeEach, afterEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import { nextTick } from "vue"

vi.mock("@/services/api", () => ({
  getDeviceState: vi.fn<() => void>(),
  getDevices: vi.fn<() => void>(),
  getResource: vi.fn<() => void>(),
  postDevices: vi.fn<() => void>(),
  postCustomDevice: vi.fn<() => void>(),
  postResource: vi.fn<() => void>(),
  startTask: vi.fn<() => void>(),
  stopTask: vi.fn<() => void>(),
  getSettings: vi.fn<() => void>(),
  updateSettings: vi.fn<() => void>(),
  getTaskConfig: vi.fn<() => void>(),
  saveTaskConfig: vi.fn<() => void>(),
  getInterface: vi.fn<() => void>(),
  rescanScanSelectOption: vi.fn<() => void>(),
}))

vi.mock("@/services/feedback/message", () => ({
  showGlobalMessage: vi.fn<() => void>(),
}))

vi.mock("@/app/i18n", () => ({
  default: { global: { t: (key: string) => key } },
}))

import { useDeviceConnectionStore } from "@/stores/device/deviceConnection"
import { useIndexStore } from "@/stores/panel/session"
import { useInterfaceStore } from "@/stores/interface/interface"
import { useSettingsStore } from "@/stores/settings/settings"
import { useTaskConfigStore } from "@/stores/task-config/taskConfig"
import * as api from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import type {
  ConnectableDevice,
  DeviceControllerCapability,
  DeviceRuntimeState,
  DeviceSearchData,
  ResourceInfo,
} from "@/services/api"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"

const disconnectedState: DeviceRuntimeState = {
  connected: false,
  configuration_locked: false,
  controller_name: null,
  resource_name: null,
}

const lockedAdbState: DeviceRuntimeState = {
  connected: true,
  configuration_locked: true,
  controller_name: "adb",
  resource_name: "res1",
}

const adbCapability: DeviceControllerCapability = {
  name: "adb",
  type: "Adb",
  label: "Adb",
  display_label: "ADB",
  enabled: true,
  reason: "",
  search_mode: "select",
  default_address: "",
}

const playCoverCapability: DeviceControllerCapability = {
  name: "playcover",
  type: "PlayCover",
  label: "PlayCover",
  display_label: "PlayCover",
  enabled: true,
  reason: "",
  search_mode: "input",
  default_address: "127.0.0.1:1717",
}

const adbDevice: ConnectableDevice = {
  type: "Adb",
  name: "adb-device",
  adb_path: "/usr/bin/adb",
  address: "127.0.0.1:5555",
  screencap_methods: 0,
  input_methods: 0,
  config: {},
}

const customAdbDevice: ConnectableDevice = {
  type: "Adb",
  name: "",
  adb_path: "",
  address: "192.168.1.10:5555",
  screencap_methods: 0,
  input_methods: 0,
  config: {},
}

const scannedCustomAdbDevice: ConnectableDevice = {
  type: "Adb",
  name: "phone",
  adb_path: "/usr/bin/adb",
  address: "192.168.1.10:5555",
  screencap_methods: 1,
  input_methods: 1,
  config: {},
}

const savedAdbDevice: PanelLastConnectedDevice = {
  type: "Adb",
  controller_name: "adb",
  fingerprint: "adb|/usr/bin/adb|127.0.0.1:5555",
  adb_path: "/usr/bin/adb",
  address: "127.0.0.1:5555",
  class_name: "",
  window_name: "",
  hWnd: 0,
  gamepad_type: 0,
  uuid: "",
}

describe("useDeviceConnectionStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
    vi.mocked(api.getDeviceState).mockResolvedValue(disconnectedState)
    vi.mocked(api.getDevices).mockResolvedValue({
      controllers: [],
      selected_controller: null,
      devices: [],
    })
    vi.mocked(api.getResource).mockResolvedValue([])
    vi.mocked(api.updateSettings).mockResolvedValue(true)
  })

  afterEach(() => {
    const store = useDeviceConnectionStore()
    store.cleanup()
  })

  it("has correct initial state", () => {
    const store = useDeviceConnectionStore()
    expect(store.selectedController).toBeNull()
    expect(store.availableDevices).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.isDeviceResourceLocked).toBe(false)
  })

  describe("applyDeviceRuntimeState", () => {
    it("sets locked state and names when connected and locked", () => {
      const store = useDeviceConnectionStore()
      store.applyDeviceRuntimeState(lockedAdbState)
      expect(store.isDeviceResourceLocked).toBe(true)
      expect(store.connectedControllerName).toBe("adb")
      expect(store.connectedResourceName).toBe("res1")
    })

    it("hydrates selected controller from runtime state when locked", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.applyDeviceRuntimeState({
        connected: true,
        configuration_locked: true,
        controller_name: "adb",
        resource_name: null,
      })
      expect(store.selectedController).toBe("ADB")
    })

    it("hydrates resource from runtime state when locked", () => {
      const store = useDeviceConnectionStore()
      store.applyDeviceRuntimeState({
        connected: true,
        configuration_locked: true,
        controller_name: null,
        resource_name: "res1",
      })
      expect(store.resource).toBe("res1")
    })

    it("overwrites local selection with backend authority when locked", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability, playCoverCapability]
      store.selectedController = "PlayCover"
      store.resource = "local-res"
      store.applyDeviceRuntimeState({
        connected: true,
        configuration_locked: true,
        controller_name: "adb",
        resource_name: "res1",
      })
      expect(store.selectedController).toBe("ADB")
      expect(store.resource).toBe("res1")
    })

    it("does not lock when not connected even if configuration_locked is true", () => {
      const store = useDeviceConnectionStore()
      store.applyDeviceRuntimeState({
        connected: false,
        configuration_locked: true,
        controller_name: "adb",
        resource_name: "res1",
      })
      expect(store.isDeviceResourceLocked).toBe(false)
    })
  })

  describe("StartTask", () => {
    it("submits directly when the backend runtime is disconnected", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = "res1"
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      configStore.configLoaded = true
      configStore.taskList = [{ id: "Task 1", name: "Task 1", order: 0, checked: true }]
      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.startTask).mockResolvedValue({ accepted: true, runId: "run-1" })
      const result = await store.StartTask()
      expect(result).toBe(true)
      expect(api.getDeviceState).not.toHaveBeenCalled()
      expect(api.postDevices).not.toHaveBeenCalled()
      expect(api.postResource).not.toHaveBeenCalled()
      expect(api.startTask).toHaveBeenCalled()
    })

    it("surfaces an unknown task response without setting running state", async () => {
      const store = useDeviceConnectionStore()
      const indexStore = useIndexStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = "res1"
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      configStore.configLoaded = true
      configStore.taskList = [{ id: "Unknown Task", name: "Unknown Task", order: 0, checked: true }]
      interfaceStore.interface = { task: [] }
      vi.mocked(api.startTask).mockResolvedValue({
        accepted: false,
        error: "任务名称不在当前 interface 中",
      })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(indexStore.TaskRunning).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "任务名称不在当前 interface 中")
    })

    it("returns false when no compatible tasks", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      configStore.configLoaded = true
      configStore.taskList = [{ id: "Task 1", name: "Task 1", order: 0, checked: true }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1", controller: ["win32"] }],
      }
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.noCompatibleTask")
    })

    it("returns false when no tasks selected", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      configStore.configLoaded = true
      configStore.taskList = [{ id: "Task 1", name: "Task 1", order: 0, checked: false }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.selectTask")
    })

    it("returns true on full success", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      const payload = {
        task_identity: "name" as const,
        task_list: ["Task 1"],
        task_options: {},
        preTasks: [],
      }
      const expectedPayload = {
        ...payload,
        controller_name: "adb",
        device: {
          controller_name: "adb",
          device_type: "Adb",
          device_address: "127.0.0.1:5555",
        },
        resource_name: "res1",
      }
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      configStore.configLoaded = true
      configStore.taskList = [{ id: "Task 1", name: "Task 1", order: 0, checked: true }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue(payload)
      vi.mocked(api.startTask).mockResolvedValue({ accepted: true, runId: "run-1" })
      const result = await store.StartTask()
      expect(result).toBe(true)
      expect(api.startTask).toHaveBeenCalledWith(expectedPayload)
    })

    it("sets startConflict and returns false on conflict without toast", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      const payload = {
        task_identity: "name" as const,
        task_list: ["Task 1"],
        task_options: {},
        preTasks: [],
      }
      const conflict = {
        code: "busy_manual" as const,
        message: "busy",
        active_run_id: "run-9",
        active_task_name: "Other Task",
        active_origin: "manual" as const,
      }
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      configStore.configLoaded = true
      configStore.taskList = [{ id: "Task 1", name: "Task 1", order: 0, checked: true }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue(payload)
      vi.mocked(api.startTask).mockResolvedValue({ accepted: false, conflict })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(store.startConflict).toEqual(conflict)
      expect(showGlobalMessage).not.toHaveBeenCalled()
    })

    describe("stopActiveAndRestart", () => {
      function primeRunningStore() {
        const store = useDeviceConnectionStore()
        const indexStore = useIndexStore()
        const configStore = useTaskConfigStore()
        const interfaceStore = useInterfaceStore()
        store.controllerCapabilities = [adbCapability]
        store.selectedController = "ADB"
        store.resource = "res1"
        store.startConflict = {
          code: "busy_manual",
          message: "busy",
          active_run_id: "run-9",
          active_task_name: "Other Task",
          active_origin: "manual",
        }
        configStore.configLoaded = true
        store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
        store.availableDevices = [adbDevice]
        configStore.taskList = [{ id: "Task 1", name: "Task 1", order: 0, checked: true }]
        interfaceStore.interface = {
          task: [{ name: "Task 1", entry: "task1" }],
        }
        vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
        vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue({
          task_identity: "name" as const,
          task_list: ["Task 1"],
          task_options: {},
          preTasks: [],
        })
        indexStore.setTaskRunning(true)
        return { store, indexStore }
      }

      it("restarts only after SSE clears TaskRunning", async () => {
        const { store, indexStore } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)
        vi.mocked(api.startTask).mockResolvedValue({ accepted: true, runId: "run-2" })

        const pending = store.stopActiveAndRestart()
        await nextTick()
        expect(api.stopTask).toHaveBeenCalled()
        expect(store.startConflict).toBeNull()
        // 槽位未释放前不得重试启动
        expect(api.startTask).not.toHaveBeenCalled()

        indexStore.setTaskRunning(false)
        await expect(pending).resolves.toBe(true)
        expect(api.startTask).toHaveBeenCalledTimes(1)
      })

      it("retries when busy_manual conflict arrives after terminal event (slot not yet released)", async () => {
        vi.useFakeTimers()
        const { store, indexStore } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)
        // 复现：终端事件先于 active_run 清槽 → 首次重启拿到 busy_manual，清槽后重试成功
        vi.mocked(api.startTask)
          .mockResolvedValueOnce({
            accepted: false,
            conflict: {
              code: "busy_manual",
              message: "busy",
              active_run_id: "run-9",
              active_task_name: "Other Task",
              active_origin: "manual",
            },
          })
          .mockResolvedValueOnce({ accepted: true, runId: "run-2" })

        const pending = store.stopActiveAndRestart()
        await vi.advanceTimersByTimeAsync(0)
        indexStore.setTaskRunning(false)
        await vi.advanceTimersByTimeAsync(500)
        const result = await pending
        vi.useRealTimers()

        expect(result).toBe(true)
        expect(api.startTask).toHaveBeenCalledTimes(2)
        expect(store.startConflict).toBeNull()
        expect(indexStore.TaskRunning).toBe(true)
      })

      it("does not retry on busy_scheduled conflict", async () => {
        const { store, indexStore } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)
        const scheduledConflict = {
          code: "busy_scheduled" as const,
          message: "busy",
          active_run_id: "run-10",
          active_task_name: "Scheduled Task",
          active_origin: "in_app" as const,
        }
        vi.mocked(api.startTask).mockResolvedValue({
          accepted: false,
          conflict: scheduledConflict,
        })

        indexStore.setTaskRunning(false)
        await expect(store.stopActiveAndRestart()).resolves.toBe(false)
        expect(api.startTask).toHaveBeenCalledTimes(1)
        expect(store.startConflict).toEqual(scheduledConflict)
      })

      it("stops retrying when busy_manual persists past deadline", async () => {
        vi.useFakeTimers()
        const { store, indexStore } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)
        vi.mocked(api.startTask).mockResolvedValue({
          accepted: false,
          conflict: {
            code: "busy_manual",
            message: "busy",
            active_run_id: "run-9",
            active_task_name: "Other Task",
            active_origin: "manual",
          },
        })

        const pending = store.stopActiveAndRestart()
        await vi.advanceTimersByTimeAsync(0)
        indexStore.setTaskRunning(false)
        await vi.advanceTimersByTimeAsync(61_000)
        const result = await pending
        vi.useRealTimers()

        expect(result).toBe(false)
        expect(store.startConflict?.code).toBe("busy_manual")
        const calls = vi.mocked(api.startTask).mock.calls.length
        expect(calls).toBeGreaterThan(1)
        expect(calls).toBeLessThanOrEqual(121)
      })

      it("stops retrying and clears stale conflict when a later attempt fails without conflict", async () => {
        vi.useFakeTimers()
        const { store, indexStore } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)
        // 复现 greptile 场景：首次重启拿到 busy_manual，下一次因普通错误失败（无 conflict）。
        // 过期冲突不得驱动重试——应立即停止并清除 startConflict。
        vi.mocked(api.startTask)
          .mockResolvedValueOnce({
            accepted: false,
            conflict: {
              code: "busy_manual",
              message: "busy",
              active_run_id: "run-9",
              active_task_name: "Other Task",
              active_origin: "manual",
            },
          })
          .mockResolvedValueOnce({ accepted: false, error: "任务启动失败" })

        const pending = store.stopActiveAndRestart()
        await vi.advanceTimersByTimeAsync(0)
        indexStore.setTaskRunning(false)
        await vi.advanceTimersByTimeAsync(61_000)
        const result = await pending
        vi.useRealTimers()

        expect(result).toBe(false)
        // 修复前：旧 busy_manual 滞留 → 重试跑满 60s（约 121 次）；修复后：第二次失败即停
        expect(api.startTask).toHaveBeenCalledTimes(2)
        expect(store.startConflict).toBeNull()
      })

      it("fails with actionable toast when cleanup exceeds timeout", async () => {
        vi.useFakeTimers()
        const { store } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)

        const pending = store.stopActiveAndRestart()
        await vi.advanceTimersByTimeAsync(30_000)
        const result = await pending
        vi.useRealTimers()

        expect(result).toBe(false)
        expect(api.startTask).not.toHaveBeenCalled()
        expect(showGlobalMessage).toHaveBeenCalledWith(
          "error",
          "settings.scheduler.conflict.stopTimeout",
        )
      })

      it("returns false when stop request fails", async () => {
        const { store } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(false)

        await expect(store.stopActiveAndRestart()).resolves.toBe(false)
        expect(api.startTask).not.toHaveBeenCalled()
        expect(showGlobalMessage).not.toHaveBeenCalled()
      })

      it("coalesces re-entrant calls onto a single stop/restart operation", async () => {
        vi.useFakeTimers()
        const { store, indexStore } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)
        vi.mocked(api.startTask).mockResolvedValue({ accepted: true, runId: "run-2" })

        const first = store.stopActiveAndRestart()
        const second = store.stopActiveAndRestart()
        await vi.advanceTimersByTimeAsync(0)
        indexStore.setTaskRunning(false)

        const results = await Promise.all([first, second])
        vi.useRealTimers()

        expect(results).toEqual([true, true])
        // 重入调用不得另起一套 stop/start 序列
        expect(api.stopTask).toHaveBeenCalledTimes(1)
        expect(api.startTask).toHaveBeenCalledTimes(1)
      })

      it("never fires a start attempt at or past the 60s retry deadline", async () => {
        vi.useFakeTimers()
        const startedAt = Date.now()
        const { store, indexStore } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)
        const callTimes: number[] = []
        vi.mocked(api.startTask).mockImplementation(() => {
          callTimes.push(Date.now())
          return Promise.resolve({
            accepted: false,
            conflict: {
              code: "busy_manual",
              message: "busy",
              active_run_id: "run-9",
              active_task_name: "Other Task",
              active_origin: "manual",
            },
          })
        })

        const pending = store.stopActiveAndRestart()
        await vi.advanceTimersByTimeAsync(0)
        indexStore.setTaskRunning(false)
        await vi.advanceTimersByTimeAsync(61_000)
        const result = await pending
        vi.useRealTimers()

        const deadline = startedAt + 60_000
        expect(result).toBe(false)
        expect(callTimes.length).toBeGreaterThan(1)
        // 睡后重新检查 deadline：任何启动尝试都必须发生在 60s 上限之前
        expect(callTimes.every((t) => t < deadline)).toBe(true)
      })
    })
  })

  describe("fetchDevices", () => {
    it("ignores stale response when a newer request completes first", async () => {
      const store = useDeviceConnectionStore()
      let resolve1: (value: DeviceSearchData) => void
      let resolve2: (value: DeviceSearchData) => void
      const p1 = new Promise<DeviceSearchData>((r) => {
        resolve1 = r
      })
      const p2 = new Promise<DeviceSearchData>((r) => {
        resolve2 = r
      })
      vi.mocked(api.getDevices)
        .mockImplementationOnce(() => p1)
        .mockImplementationOnce(() => p2)
      const promise1 = store.fetchDevices()
      const promise2 = store.fetchDevices()
      resolve2!({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [adbDevice],
      })
      await promise2
      resolve1!({
        controllers: [],
        selected_controller: null,
        devices: [],
      })
      await promise1
      expect(store.controllerCapabilities).toEqual([adbCapability])
      expect(store.availableDevices).toEqual([adbDevice])
      expect(store.loading).toBe(false)
    })

    it("re-hydrates locked selection after capabilities load", async () => {
      const store = useDeviceConnectionStore()
      store.isDeviceResourceLocked = true
      store.connectedControllerName = "adb"
      store.connectedResourceName = "res1"
      store.selectedController = "PlayCover"
      store.resource = "stale"
      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability, playCoverCapability],
        selected_controller: "playcover",
        devices: [],
      })
      await store.fetchDevices()
      expect(store.selectedController).toBe("ADB")
      expect(store.resource).toBe("res1")
    })
  })

  describe("openDevices", () => {
    it("refreshes devices for the selected non-PlayCover controller", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [adbDevice],
      })
      store.openDevices()
      await vi.waitFor(() => {
        expect(store.availableDevices).toEqual([adbDevice])
      })
      expect(api.getDevices).toHaveBeenCalledWith("adb")
    })

    it("is a no-op when locked", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.isDeviceResourceLocked = true
      store.openDevices()
      expect(api.getDevices).not.toHaveBeenCalled()
    })

    it("is a no-op for PlayCover", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [playCoverCapability]
      store.selectedController = "PlayCover"
      store.openDevices()
      expect(api.getDevices).not.toHaveBeenCalled()
    })
  })

  describe("createCustomDevice", () => {
    it("saves trimmed address, refreshes, and selects richer scanned device", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      vi.mocked(api.postCustomDevice).mockResolvedValue({
        success: true,
        message: "ok",
        data: customAdbDevice,
      })
      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [scannedCustomAdbDevice],
      })

      await store.createCustomDevice("  192.168.1.10:5555  ")

      expect(api.postCustomDevice).toHaveBeenCalledWith({
        controller_name: "adb",
        type: "Adb",
        address: "192.168.1.10:5555",
      })
      expect(api.getDevices).toHaveBeenCalledWith("adb")
      expect(store.availableDevices).toEqual([scannedCustomAdbDevice])
      expect(store.selectedDeviceKey).toBe("adb|/usr/bin/adb|192.168.1.10:5555")
    })

    it("reports error and does not append client fallback when refresh omits device", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      vi.mocked(api.postCustomDevice).mockResolvedValue({
        success: true,
        message: "ok",
        data: customAdbDevice,
      })
      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [adbDevice],
      })

      await store.createCustomDevice("192.168.1.10:5555")

      expect(store.availableDevices).toEqual([adbDevice])
      expect(store.availableDevices).not.toContainEqual(customAdbDevice)
      expect(showGlobalMessage).toHaveBeenCalledWith(
        "error",
        "自定义设备已保存，但刷新列表后未找到该设备",
      )
    })

    it("preserves previous selection and shows error when save fails", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      vi.mocked(api.postCustomDevice).mockResolvedValue({
        success: false,
        message: "save failed",
      })

      await store.createCustomDevice("192.168.1.10:5555")

      expect(showGlobalMessage).toHaveBeenCalledWith("error", "save failed")
      expect(api.getDevices).not.toHaveBeenCalled()
      expect(store.selectedDeviceKey).toBe("adb|/usr/bin/adb|127.0.0.1:5555")
    })

    it("does not reselect when controller changes after POST", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability, playCoverCapability]
      store.selectedController = "ADB"
      let resolvePost: (value: {
        success: boolean
        message: string
        data?: ConnectableDevice
      }) => void
      const postPromise = new Promise<{
        success: boolean
        message: string
        data?: ConnectableDevice
      }>((r) => {
        resolvePost = r
      })
      vi.mocked(api.postCustomDevice).mockImplementationOnce(() => postPromise)

      const createPromise = store.createCustomDevice("192.168.1.10:5555")
      store.selectedController = "PlayCover"
      resolvePost!({ success: true, message: "ok", data: customAdbDevice })
      await createPromise

      expect(api.getDevices).not.toHaveBeenCalled()
      expect(store.selectedController).toBe("PlayCover")
    })

    it("does not reselect when a newer fetchDevices wins race after create", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"

      let resolvePost: (value: {
        success: boolean
        message: string
        data?: ConnectableDevice
      }) => void
      const postPromise = new Promise<{
        success: boolean
        message: string
        data?: ConnectableDevice
      }>((r) => {
        resolvePost = r
      })
      vi.mocked(api.postCustomDevice).mockImplementationOnce(() => postPromise)

      let resolveCreateFetch: (value: DeviceSearchData) => void
      let resolveNewerFetch: (value: DeviceSearchData) => void
      const createFetch = new Promise<DeviceSearchData>((r) => {
        resolveCreateFetch = r
      })
      const newerFetch = new Promise<DeviceSearchData>((r) => {
        resolveNewerFetch = r
      })
      vi.mocked(api.getDevices)
        .mockImplementationOnce(() => createFetch)
        .mockImplementationOnce(() => newerFetch)

      const createPromise = store.createCustomDevice("192.168.1.10:5555")
      resolvePost!({ success: true, message: "ok", data: customAdbDevice })
      // Let createCustomDevice enter its fetchDevices
      await Promise.resolve()
      await Promise.resolve()

      const newerPromise = store.fetchDevices("adb")
      resolveNewerFetch!({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [adbDevice],
      })
      await newerPromise
      resolveCreateFetch!({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [scannedCustomAdbDevice],
      })
      await createPromise

      // Newer fetch wins; create must not reselect stale custom device
      expect(store.availableDevices).toEqual([adbDevice])
      expect(store.selectedDeviceKey).not.toBe("adb|/usr/bin/adb|192.168.1.10:5555")
    })

    it("ignores empty address and locked state", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"

      await store.createCustomDevice("   ")
      expect(api.postCustomDevice).not.toHaveBeenCalled()

      store.isDeviceResourceLocked = true
      await store.createCustomDevice("192.168.1.10:5555")
      expect(api.postCustomDevice).not.toHaveBeenCalled()
    })

    it("does not call the API for an invalid address", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"

      await store.createCustomDevice("not-an-ip")

      expect(api.postCustomDevice).not.toHaveBeenCalled()
    })

    it("sends the canonical address for a valid address", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      vi.mocked(api.postCustomDevice).mockResolvedValue({
        success: false,
        message: "save failed",
      })

      await store.createCustomDevice("  192.168.001.001:05555  ")

      expect(api.postCustomDevice).toHaveBeenCalledWith({
        controller_name: "adb",
        type: "Adb",
        address: "192.168.1.1:5555",
      })
    })
  })

  describe("selectedDevice rebind", () => {
    it("rebinds by identity when fingerprint changes after refresh", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.availableDevices = [customAdbDevice]
      store.selectedDeviceKey = "adb||192.168.1.10:5555"

      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [scannedCustomAdbDevice],
      })
      await store.fetchDevices("adb")

      expect(store.selectedDeviceKey).toBe("adb|/usr/bin/adb|192.168.1.10:5555")
      expect(store.selectedDevice).toEqual(scannedCustomAdbDevice)
    })

    it("clears selection when refreshed list removes the device", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.availableDevices = [adbDevice]
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"

      vi.mocked(api.getDevices).mockResolvedValue({
        controllers: [adbCapability],
        selected_controller: "adb",
        devices: [customAdbDevice],
      })
      await store.fetchDevices("adb")

      expect(store.selectedDeviceKey).toBeNull()
      expect(store.selectedDevice).toBeNull()
    })

    it("never treats fingerprint keys as addresses", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.availableDevices = [adbDevice]
      // Stale fingerprint not in list — must not synthesize device from key
      store.selectedDeviceKey = "adb|/missing/path|127.0.0.1:5555"
      expect(store.selectedDevice).toBeNull()
    })
  })

  describe("deviceOptions", () => {
    it("maps availableDevices only without recent/discovered groups", () => {
      const store = useDeviceConnectionStore()
      store.availableDevices = [adbDevice, customAdbDevice]
      expect(store.deviceOptions).toEqual([
        { label: "adb-device(127.0.0.1:5555)", value: "adb|/usr/bin/adb|127.0.0.1:5555" },
        { label: "192.168.1.10:5555", value: "adb||192.168.1.10:5555" },
      ])
    })

    it("returns disabled placeholder when empty", () => {
      const store = useDeviceConnectionStore()
      expect(store.deviceOptions).toEqual([
        { label: "panel.noDevice", value: "none-device", disabled: true },
      ])
    })
  })

  describe("getResourceList", () => {
    it("ignores stale response when a newer request completes first", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      let resolve1: (value: ResourceInfo[]) => void
      let resolve2: (value: ResourceInfo[]) => void
      const p1 = new Promise<ResourceInfo[]>((r) => {
        resolve1 = r
      })
      const p2 = new Promise<ResourceInfo[]>((r) => {
        resolve2 = r
      })
      vi.mocked(api.getResource)
        .mockImplementationOnce(() => p1)
        .mockImplementationOnce(() => p2)
      const promise1 = store.getResourceList()
      const promise2 = store.getResourceList()
      resolve2!([{ name: "res2" }])
      await promise2
      resolve1!([{ name: "res1" }])
      await promise1
      expect(store.resourcesList).toEqual([{ label: "res2", value: "res2" }])
      expect(store.loading).toBe(false)
    })
  })

  describe("connectDevices", () => {
    it("fails when device resource is locked", async () => {
      const store = useDeviceConnectionStore()
      store.isDeviceResourceLocked = true
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("设备与资源已锁定，无法切换")
    })

    it("fails when no controller selected", async () => {
      const store = useDeviceConnectionStore()
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.selectDeviceType")
    })

    it("fails when selected controller is disabled", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [{ ...adbCapability, enabled: false }]
      store.selectedController = "ADB"
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.selectDeviceType")
    })

    it("PlayCover fails on empty address", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [playCoverCapability]
      store.selectedController = "PlayCover"
      store.playCoverAddress = "  "
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.playcoverAddress")
    })

    it("PlayCover fails on invalid address format", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [playCoverCapability]
      store.selectedController = "PlayCover"
      store.playCoverAddress = "bad-address"
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.invalidPlaycoverAddress")
    })

    it("fails when no device selected for non-PlayCover controller", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = null
      const result = await store.connectDevices()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.selectDevice")
    })

    it("succeeds and persists device on valid selection", async () => {
      const store = useDeviceConnectionStore()
      const settingsStore = useSettingsStore()
      const indexStore = useIndexStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = "res1"
      vi.mocked(api.getDeviceState).mockResolvedValue({
        connected: true,
        configuration_locked: true,
        controller_name: "adb",
        resource_name: "res1",
      })
      vi.mocked(api.postDevices).mockResolvedValue({ success: true, message: "ok" })
      vi.mocked(api.getResource).mockResolvedValue([{ name: "res1" }])
      const result = await store.connectDevices()
      expect(result.success).toBe(true)
      expect(api.postDevices).toHaveBeenCalledWith({
        controller_name: "adb",
        device: adbDevice,
        resource_name: "res1",
      })
      expect(indexStore.Connected).toBe(true)
      expect(settingsStore.settings.panel.lastConnectedDevice).not.toBeNull()
      expect(store.resourcesList).toEqual([{ label: "res1", value: "res1" }])
    })
  })

  describe("buildPlayCoverDevice", () => {
    it("returns an error without making API calls for an invalid address", () => {
      const store = useDeviceConnectionStore()
      store.playCoverAddress = "bad-address"

      expect(store.buildPlayCoverDevice()).toEqual({
        error: "panel.invalidPlaycoverAddress",
      })
      expect(api.postDevices).not.toHaveBeenCalled()
      expect(api.postCustomDevice).not.toHaveBeenCalled()
      expect(api.getDevices).not.toHaveBeenCalled()
    })

    it("returns a device with a canonical address", () => {
      const store = useDeviceConnectionStore()
      store.playCoverAddress = " 127.000.000.001:01717 "

      expect(store.buildPlayCoverDevice()).toEqual({
        device: { type: "PlayCover", address: "127.0.0.1:1717" },
      })
    })
  })

  describe("postResourceSelection", () => {
    it("fails when locked", async () => {
      const store = useDeviceConnectionStore()
      store.isDeviceResourceLocked = true
      const result = await store.postResourceSelection()
      expect(result.success).toBe(false)
    })

    it("fails when not connected", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      const result = await store.postResourceSelection()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.connectFirstHint")
    })

    it("fails when no resource selected", async () => {
      const store = useDeviceConnectionStore()
      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      indexStore.Connected = true
      settingsStore.settings.panel.lastConnectedDevice = savedAdbDevice
      const result = await store.postResourceSelection()
      expect(result.success).toBe(false)
      expect(result.message).toBe("panel.selectResource")
    })

    it("succeeds when connected and resource selected", async () => {
      const store = useDeviceConnectionStore()
      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      store.resource = "res1"
      indexStore.Connected = true
      settingsStore.settings.panel.lastConnectedDevice = savedAdbDevice
      vi.mocked(api.postResource).mockResolvedValue({ success: true, message: "ok" })
      const result = await store.postResourceSelection()
      expect(result.success).toBe(true)
      expect(api.postResource).toHaveBeenCalledWith("res1")
    })
  })

  describe("init and cleanup", () => {
    it("init sets up timer and watchers, double init is no-op", async () => {
      const store = useDeviceConnectionStore()
      const settingsStore = useSettingsStore()
      const indexStore = useIndexStore()
      const configStore = useTaskConfigStore()
      settingsStore.initialized = true
      const setIntervalSpy = vi.spyOn(window, "setInterval")
      store.init()
      expect(store.initialized).toBe(true)
      expect(store.deviceStatePollTimer).not.toBeNull()
      expect(setIntervalSpy).toHaveBeenCalledTimes(1)
      store.init()
      expect(setIntervalSpy).toHaveBeenCalledTimes(1)
      configStore.taskList = [{ id: "task1", name: "Task 1", order: 0 }]
      await nextTick()
      expect(indexStore.SelectedTaskID).toBe("task1")
      setIntervalSpy.mockRestore()
    })

    it("schedules task config saves only after config loading", async () => {
      const store = useDeviceConnectionStore()
      const settingsStore = useSettingsStore()
      const configStore = useTaskConfigStore()
      settingsStore.initialized = true
      configStore.configLoaded = true
      const saveSpy = vi.spyOn(configStore, "debouncedSave").mockImplementation(() => {})

      store.init()
      configStore.taskList = [{ id: "task1", name: "Task 1", order: 0, checked: true }]
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(1)

      configStore.options = { task1: { mode: "safe" } }
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(2)

      configStore.preTasks = [{ id: "pre1", command: "echo hi", enabled: true, timeout: 30 }]
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(3)

      configStore.selectedPresetName = "preset1"
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(4)

      configStore.configLoaded = false
      configStore.options = { task1: { mode: "fast" } }
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(4)
    })

    it("cleanup stops timers and all six watchers", async () => {
      const store = useDeviceConnectionStore()
      const settingsStore = useSettingsStore()
      const indexStore = useIndexStore()
      const configStore = useTaskConfigStore()
      settingsStore.initialized = true
      configStore.configLoaded = true
      configStore.taskList = [{ id: "initial", name: "Initial", order: 0, checked: true }]
      indexStore.Connected = true
      store.isDeviceResourceLocked = true
      const saveSpy = vi.spyOn(configStore, "debouncedSave").mockImplementation(() => {})

      store.init()
      expect(store.deviceStatePollTimer).not.toBeNull()
      store.cleanup()
      saveSpy.mockClear()
      indexStore.SelectTask("sentinel")

      configStore.taskList = [
        { id: "first", name: "First", order: 0, checked: true },
        { id: "second", name: "Second", order: 1, checked: false },
      ]
      configStore.options = { first: { mode: "safe" } }
      configStore.preTasks = [{ id: "pre1", command: "echo hi", enabled: true, timeout: 30 }]
      configStore.selectedPresetName = "preset1"
      indexStore.Connected = false
      await nextTick()

      expect(store.deviceStatePollTimer).toBeNull()
      expect(store.initialized).toBe(false)
      expect(saveSpy).not.toHaveBeenCalled()
      expect(indexStore.SelectedTaskID).toBe("sentinel")
      expect(store.isDeviceResourceLocked).toBe(true)
    })
  })

  describe("getters", () => {
    it("controllerOptions maps capabilities", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [
        adbCapability,
        { ...adbCapability, display_label: "ADB 2", enabled: false },
      ]
      expect(store.controllerOptions).toEqual([
        { label: "ADB", value: "ADB", disabled: false },
        { label: "ADB 2", value: "ADB 2", disabled: true },
      ])
    })

    it("selectedControllerCapability finds by display_label", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      expect(store.selectedControllerCapability).toEqual(adbCapability)
    })

    it("selectedControllerDisabled returns true for disabled capability", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [{ ...adbCapability, enabled: false }]
      store.selectedController = "ADB"
      expect(store.selectedControllerDisabled).toBe(true)
    })

    it("selectedControllerName returns capability name or null", () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      expect(store.selectedControllerName).toBe("adb")
      store.selectedController = null
      expect(store.selectedControllerName).toBeNull()
    })
  })
})
