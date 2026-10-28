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
    it("returns false when device connection fails", async () => {
      const store = useDeviceConnectionStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.selectedDeviceKey = "adb|/usr/bin/adb|127.0.0.1:5555"
      store.availableDevices = [adbDevice]
      vi.mocked(api.getDeviceState).mockResolvedValue(disconnectedState)
      vi.mocked(api.postDevices).mockResolvedValue({
        success: false,
        message: "connect failed",
      })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith(
        "error",
        expect.stringContaining("connect failed"),
      )
    })

    it("returns false when resource selection fails", async () => {
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
      vi.mocked(api.getDeviceState).mockResolvedValue({
        connected: true,
        configuration_locked: false,
        controller_name: null,
        resource_name: null,
      })
      vi.mocked(api.postDevices).mockResolvedValue({ success: true, message: "ok" })
      vi.mocked(api.postResource).mockResolvedValue({
        success: false,
        message: "resource failed",
      })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith(
        "error",
        expect.stringContaining("resource failed"),
      )
    })

    it("returns false when no compatible tasks", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      configStore.configLoaded = true
      configStore.taskList = [{ uid: "task-1-instance", id: "Task 1", name: "Task 1" }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1", controller: ["win32"] }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      vi.spyOn(store, "connectDevices").mockResolvedValue({ success: true, message: "ok" })
      vi.spyOn(store, "postResourceSelection").mockResolvedValue({
        success: true,
        message: "ok",
      })
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
      configStore.configLoaded = true
      configStore.taskList = []

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      vi.spyOn(store, "connectDevices").mockResolvedValue({ success: true, message: "ok" })
      vi.spyOn(store, "postResourceSelection").mockResolvedValue({
        success: true,
        message: "ok",
      })
      const result = await store.StartTask()
      expect(result).toBe(false)
      expect(showGlobalMessage).toHaveBeenCalledWith("error", "panel.selectTask")
    })

    it("returns true on full success", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      const payload = { task_list: ["Task 1"], task_options: {}, preTasks: [] }
      const expectedPayload = {
        ...payload,
        controller_name: "adb",
        device: { controller_name: "adb", device_type: "Adb", device_address: "" },
        resource_name: "res1",
      }
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      configStore.configLoaded = true
      configStore.taskList = [{ uid: "task-1-instance", id: "Task 1", name: "Task 1" }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
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
      const payload = { task_list: ["Task 1"], task_options: {}, preTasks: [] }
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
      configStore.configLoaded = true
      configStore.taskList = [{ uid: "task-1-instance", id: "Task 1", name: "Task 1" }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
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
        configStore.taskList = [{ uid: "task-1-instance", id: "Task 1", name: "Task 1" }]
        interfaceStore.interface = {
          task: [{ name: "Task 1", entry: "task1" }],
        }
        vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
        vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue({
          task_list: ["Task 1"],
          task_options: {},
          preTasks: [],
        })
        indexStore.setTaskRunning(true)
        return { store, indexStore }
      }

      it("restarts after TaskRunning clears", async () => {
        const { store, indexStore } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)
        vi.mocked(api.startTask).mockResolvedValue({ accepted: true, runId: "run-2" })

        const pending = store.stopActiveAndRestart()
        await nextTick()
        expect(api.stopTask).toHaveBeenCalled()
        expect(store.startConflict).toBeNull()
        // 槽位未释放前不得启动
        expect(api.startTask).not.toHaveBeenCalled()

        indexStore.setTaskRunning(false)
        await expect(pending).resolves.toBe(true)
        expect(api.startTask).toHaveBeenCalledTimes(1)
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

      it("retries a busy_manual conflict after a refresh", async () => {
        vi.useFakeTimers()
        const { store, indexStore } = primeRunningStore()
        // Refreshed page: no local run flag, backend slot not released yet.
        indexStore.setTaskRunning(false)
        vi.mocked(api.stopTask).mockResolvedValue(true)
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
        await vi.advanceTimersByTimeAsync(500)
        await expect(pending).resolves.toBe(true)
        vi.useRealTimers()

        expect(api.startTask).toHaveBeenCalledTimes(2)
        expect(store.startConflict).toBeNull()
      })

      it("stops waiting when the view unmounts", async () => {
        vi.useFakeTimers()
        const { store } = primeRunningStore()
        vi.mocked(api.stopTask).mockResolvedValue(true)

        const pending = store.stopActiveAndRestart()
        await vi.advanceTimersByTimeAsync(0)
        store.cleanup()
        await expect(pending).resolves.toBe(false)
        vi.useRealTimers()

        expect(api.startTask).not.toHaveBeenCalled()
      })

      it("shares one stop sequence between concurrent calls", async () => {
        const { store, indexStore } = primeRunningStore()
        indexStore.setTaskRunning(false)
        vi.mocked(api.stopTask).mockResolvedValue(true)
        vi.mocked(api.startTask).mockResolvedValue({ accepted: true, runId: "run-2" })

        const first = store.stopActiveAndRestart()
        const second = store.stopActiveAndRestart()
        await expect(Promise.all([first, second])).resolves.toEqual([true, true])
        expect(api.stopTask).toHaveBeenCalledTimes(1)
        expect(api.startTask).toHaveBeenCalledTimes(1)
      })

      it("reports a timeout when the run slot is never released", async () => {
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
    })

    it("skips connect and resource when already connected", async () => {
      const store = useDeviceConnectionStore()
      const configStore = useTaskConfigStore()
      const interfaceStore = useInterfaceStore()
      const payload = { task_list: ["Task 1"], task_options: {}, preTasks: [] }
      store.controllerCapabilities = [adbCapability]
      store.selectedController = "ADB"
      store.resource = "res1"
      configStore.configLoaded = true
      configStore.taskList = [{ uid: "task-1-instance", id: "Task 1", name: "Task 1" }]

      interfaceStore.interface = {
        task: [{ name: "Task 1", entry: "task1" }],
      }
      vi.mocked(api.getDeviceState).mockResolvedValue(lockedAdbState)
      vi.spyOn(configStore, "buildExecutionPayload").mockReturnValue(payload)
      const expectedPayload = {
        ...payload,
        controller_name: "adb",
        device: { controller_name: "adb", device_type: "Adb", device_address: "" },
        resource_name: "res1",
      }
      const connectSpy = vi.spyOn(store, "connectDevices").mockResolvedValue({
        success: true,
        message: "ok",
      })
      const resourceSpy = vi.spyOn(store, "postResourceSelection").mockResolvedValue({
        success: true,
        message: "ok",
      })
      vi.mocked(api.startTask).mockResolvedValue({ accepted: true, runId: "run-1" })
      const result = await store.StartTask()
      expect(result).toBe(true)
      expect(connectSpy).not.toHaveBeenCalled()
      expect(resourceSpy).not.toHaveBeenCalled()
      expect(api.startTask).toHaveBeenCalledWith(expectedPayload)
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
      expect(showGlobalMessage).toHaveBeenCalledWith("error", expect.any(String))
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
      configStore.taskList = [{ uid: "task-1-instance", id: "Task 1", name: "Task 1" }]
      await nextTick()
      expect(indexStore.SelectedTaskID).toBe("Task 1")
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
      configStore.taskList = [{ uid: "task-1-instance", id: "Task 1", name: "Task 1" }]
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(1)

      configStore.options = { "Task 1": { mode: "safe" } }
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(2)

      configStore.preTasks = [{ id: "pre1", command: "echo hi", enabled: true, timeout: 30 }]
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(3)

      configStore.selectedPresetName = "preset1"
      await nextTick()
      expect(saveSpy).toHaveBeenCalledTimes(4)

      configStore.configLoaded = false
      configStore.options = { "Task 1": { mode: "fast" } }
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
      configStore.taskList = [{ uid: "initial-instance", id: "Initial", name: "Initial" }]
      indexStore.Connected = true
      store.isDeviceResourceLocked = true
      const saveSpy = vi.spyOn(configStore, "debouncedSave").mockImplementation(() => {})

      store.init()
      expect(store.deviceStatePollTimer).not.toBeNull()
      store.cleanup()
      saveSpy.mockClear()
      indexStore.SelectTask("sentinel")

      configStore.taskList = [
        { uid: "first-instance", id: "First", name: "First" },
        { uid: "second-instance", id: "Second", name: "Second" },
      ]
      configStore.options = { First: { mode: "safe" } }
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
})
