import { defineStore } from "pinia"
import { watch } from "vue"
import i18n from "@/app/i18n"
import { customDeviceAddressSchema, playCoverAddressSchema } from "@/validation/device"
import { tryCatch } from "@/utils/tryCatch"
import {
  getDeviceState,
  getDevices,
  getResource,
  postCustomDevice,
  postDevices,
  postResource,
  startTask,
  stopTask,
  type ConnectableDevice,
  type DeviceControllerCapability,
  type PlayCoverDevice,
  type PostDeviceResult,
  type PostResourceResult,
} from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useIndexStore } from "@/stores/panel/session"
import { useInterfaceStore } from "@/stores/interface/interface"
import { useSettingsStore } from "@/stores/settings/settings"
import { useTaskConfigStore } from "@/stores/task-config/taskConfig"
import type { ManualStartPayload, StartConflict } from "@/types/schedulerModel"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"
import { resolveInterfaceText } from "@/utils/interface/content"
import {
  buildDeviceFingerprint,
  buildDeviceLabel,
  findDeviceByIdentityOrFingerprint,
  getDeviceIdentity,
  getPlayCoverDefaultAddress,
  getStoredDeviceFingerprint,
  getStoredDeviceIdentity,
  isAdbDevice,
  isGamepadDevice,
  isWin32Device,
  storedDeviceMatchesController,
} from "@/utils/panel/device"

let watcherStopHandles: (() => void)[] = []

/** Upper bound for waiting on the backend to release its run slot after stop. */
const STOP_WAIT_TIMEOUT_MS = 30_000

/** Cadence and deadline for retrying a start that loses the race with slot release. */
const START_RETRY_INTERVAL_MS = 500
const START_RETRY_DEADLINE_MS = 60_000

/** One in-flight stop-then-restart sequence, shared by concurrent callers. */
let restartInFlight: Promise<boolean> | null = null
/** Cancels the pending wait/retry when the owning view unmounts. */
let restartAbort: AbortController | null = null

/** Result of a single start request, kept free of dialog state. */
type StartOutcome =
  | { kind: "started" }
  | { kind: "conflict"; conflict: StartConflict }
  | { kind: "failed" }

export const useDeviceConnectionStore = defineStore("deviceConnection", {
  state: (): {
    selectedController: string | null
    selectedDeviceKey: string | null
    availableDevices: ConnectableDevice[]
    controllerCapabilities: DeviceControllerCapability[]
    playCoverAddress: string
    resource: string | null
    resourcesList: Array<{ label: string; value: string }>
    loading: boolean
    isDeviceResourceLocked: boolean
    connectedControllerName: string | null
    connectedResourceName: string | null
    deviceStatePollTimer: number | null
    initialized: boolean
    startConflict: StartConflict | null
    _fetchDevicesRequestId: number
    _fetchResourcesRequestId: number
  } => ({
    selectedController: null,
    selectedDeviceKey: null,
    availableDevices: [],
    controllerCapabilities: [],
    playCoverAddress: "",
    resource: null,
    resourcesList: [],
    loading: false,
    isDeviceResourceLocked: false,
    connectedControllerName: null,
    connectedResourceName: null,
    deviceStatePollTimer: null,
    initialized: false,
    startConflict: null,
    _fetchDevicesRequestId: 0,
    _fetchResourcesRequestId: 0,
  }),

  // ---------------------------------------------------------------------------
  // Getters: derived selection & connection state
  // ---------------------------------------------------------------------------
  getters: {
    controllerOptions(state) {
      return state.controllerCapabilities.map((item) => {
        const label = resolveInterfaceText(item.label, item.name)
        return {
          label: item.display_label === item.label ? label : `${label}(${item.name})`,
          value: item.display_label,
          disabled: !item.enabled,
        }
      })
    },

    selectedControllerCapability(state): DeviceControllerCapability | null {
      if (!state.selectedController) {
        return null
      }
      return (
        state.controllerCapabilities.find(
          (item) => item.display_label === state.selectedController,
        ) || null
      )
    },

    selectedControllerDisabled(): boolean {
      return this.selectedControllerCapability ? !this.selectedControllerCapability.enabled : false
    },

    selectedControllerName(): string | null {
      return this.selectedControllerCapability?.name || null
    },

    // Backend owns scan+custom merge; Home options are flat availableDevices only.
    // recentDevices remain in settings for scheduler/other consumers.
    deviceOptions(): Array<{ label: string; value: string; disabled?: boolean }> {
      const t = i18n.global.t
      if (this.availableDevices.length === 0) {
        return [{ label: t("panel.noDevice"), value: "none-device", disabled: true }]
      }
      return this.availableDevices.map((item) => ({
        label: buildDeviceLabel(item),
        value: buildDeviceFingerprint(item),
      }))
    },

    selectedDevice(): ConnectableDevice | null {
      if (!this.selectedDeviceKey) {
        return null
      }

      const byFingerprint = this.availableDevices.find(
        (item) => buildDeviceFingerprint(item) === this.selectedDeviceKey,
      )
      if (byFingerprint) {
        return byFingerprint
      }

      // Identity match only when selectedDeviceKey is a pure identity (not a fingerprint).
      // Fingerprints contain "|"; never treat them as addresses.
      if (!this.selectedDeviceKey.includes("|")) {
        const byIdentity = this.availableDevices.find(
          (item) => getDeviceIdentity(item) === this.selectedDeviceKey,
        )
        if (byIdentity) {
          return byIdentity
        }
      }

      return null
    },

    currentSelectionFingerprint(): string {
      if (this.selectedControllerCapability?.type === "PlayCover") {
        const address = this.playCoverAddress.trim()
        return address ? `playcover|${address}|` : ""
      }
      return this.selectedDevice ? buildDeviceFingerprint(this.selectedDevice) : ""
    },

    isCurrentSelectionConnected(): boolean {
      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()
      const savedDevice = settingsStore.settings.panel.lastConnectedDevice
      const selectedCapability = this.selectedControllerCapability

      if (!indexStore.Connected || !savedDevice || !selectedCapability) {
        return false
      }
      if (!storedDeviceMatchesController(savedDevice, selectedCapability)) {
        return false
      }
      return getStoredDeviceFingerprint(savedDevice) === this.currentSelectionFingerprint
    },
  },

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------
  actions: {
    // --- Device selection persistence & restore ---
    async persistLastConnectedDevice(deviceInfo: ConnectableDevice, controllerName: string) {
      const settingsStore = useSettingsStore()
      const storedDevice = buildStoredLastConnectedDevice(deviceInfo, controllerName)

      await settingsStore.updateSetting("panel", "lastConnectedDevice", storedDevice)
      return storedDevice
    },

    async persistLastResource(name: string) {
      const settingsStore = useSettingsStore()
      await settingsStore.updateSetting("panel", "lastResource", name)
    },

    restoreLastConnectedDevice() {
      const settingsStore = useSettingsStore()
      const savedDevice = settingsStore.settings.panel.lastConnectedDevice
      const selectedCapability = this.selectedControllerCapability

      if (!savedDevice || !selectedCapability) {
        return
      }
      if (!storedDeviceMatchesController(savedDevice, selectedCapability)) {
        return
      }

      if (selectedCapability.type === "PlayCover") {
        this.playCoverAddress =
          savedDevice.address || getPlayCoverDefaultAddress(this.controllerCapabilities)
        return
      }

      this.selectRestoredDevice(savedDevice)
    },

    /** Fingerprint match first; identity fallback when scan returns a richer device. */
    selectRestoredDevice(savedDevice: PanelLastConnectedDevice) {
      const targetFingerprint = getStoredDeviceFingerprint(savedDevice)
      const matchedDevice = this.availableDevices.find(
        (item) => buildDeviceFingerprint(item) === targetFingerprint,
      )
      if (matchedDevice) {
        this.selectedDeviceKey = buildDeviceFingerprint(matchedDevice)
        return
      }

      const targetIdentity = getStoredDeviceIdentity(savedDevice)
      const byIdentity = this.availableDevices.find(
        (item) => getDeviceIdentity(item) === targetIdentity,
      )
      this.selectedDeviceKey = byIdentity ? buildDeviceFingerprint(byIdentity) : null
    },

    /** When locked, backend controller_name/resource_name are authority. */
    hydrateLockedSelection(
      controllerName: string | null | undefined,
      resourceName: string | null | undefined,
    ) {
      if (!this.isDeviceResourceLocked) {
        return
      }
      if (controllerName) {
        const capability = this.controllerCapabilities.find((item) => item.name === controllerName)
        if (capability) {
          this.selectedController = capability.display_label
        }
      }
      if (resourceName != null) {
        this.resource = resourceName
      }
    },

    // --- Runtime state sync ---
    applyDeviceRuntimeState(state: Awaited<ReturnType<typeof getDeviceState>>) {
      const indexStore = useIndexStore()
      indexStore.setConnected(state.connected)
      this.isDeviceResourceLocked = state.connected ? state.configuration_locked : false
      this.connectedControllerName = state.controller_name
      this.connectedResourceName = state.resource_name

      // When locked, always apply backend controller/resource as authority
      this.hydrateLockedSelection(state.controller_name, state.resource_name)
    },

    async syncDeviceRuntimeState() {
      const [state] = await tryCatch(() => getDeviceState())
      if (state) {
        this.applyDeviceRuntimeState(state)
      }
    },

    // --- Device / resource fetching ---
    applyControllerData(data: Awaited<ReturnType<typeof getDevices>>) {
      this.controllerCapabilities = data.controllers
      const selectedCapability = data.controllers.find(
        (item) => item.name === data.selected_controller,
      )
      this.selectedController = selectedCapability?.display_label || null
      return selectedCapability
    },

    applyDeviceData(
      selectedCapability: DeviceControllerCapability,
      data: Awaited<ReturnType<typeof getDevices>>,
      restoreStored: boolean,
    ) {
      if (selectedCapability.type === "PlayCover") {
        this.availableDevices = []
        this.selectedDeviceKey = null
        if (restoreStored) {
          this.restoreLastConnectedDevice()
        }
        if (!this.playCoverAddress) {
          this.playCoverAddress = getPlayCoverDefaultAddress(data.controllers)
        }
        return
      }

      const previousKey = this.selectedDeviceKey
      const previousDevice = previousKey
        ? this.availableDevices.find((item) => buildDeviceFingerprint(item) === previousKey)
        : null
      const previousIdentity = previousDevice ? getDeviceIdentity(previousDevice) : null

      this.availableDevices = data.devices
      if (restoreStored) {
        this.restoreLastConnectedDevice()
        return
      }
      this.rebindSelectedDeviceKey(previousKey, previousIdentity)
    },

    /**
     * After availableDevices is replaced, keep selection if fingerprint still exists;
     * otherwise rebind by semantic identity; otherwise clear (never treat fingerprints as addresses).
     */
    rebindSelectedDeviceKey(previousKey: string | null, previousIdentity: string | null) {
      if (!previousKey) {
        this.selectedDeviceKey = null
        return
      }

      const byFingerprint = this.availableDevices.find(
        (item) => buildDeviceFingerprint(item) === previousKey,
      )
      if (byFingerprint) {
        this.selectedDeviceKey = buildDeviceFingerprint(byFingerprint)
        return
      }

      if (previousIdentity) {
        const byIdentity = this.availableDevices.find(
          (item) => getDeviceIdentity(item) === previousIdentity,
        )
        if (byIdentity) {
          this.selectedDeviceKey = buildDeviceFingerprint(byIdentity)
          return
        }
      }

      this.selectedDeviceKey = null
    },

    async fetchDevices(controllerName?: string, restoreStored = false) {
      const requestId = ++this._fetchDevicesRequestId
      this.loading = true

      const [data] = await tryCatch(() => getDevices(controllerName))
      // A newer request owns `loading`; only the latest one may clear it.
      if (requestId !== this._fetchDevicesRequestId) {
        return false
      }
      if (!data) {
        this.loading = false
        return false
      }

      const selectedCapability = this.applyControllerData(data)
      if (!selectedCapability) {
        this.availableDevices = []
        this.selectedDeviceKey = null
        this.loading = false
        return true
      }

      this.applyDeviceData(selectedCapability, data, restoreStored)

      // After capabilities load, re-apply locked runtime selection as authority
      if (this.isDeviceResourceLocked && this.connectedControllerName) {
        this.hydrateLockedSelection(this.connectedControllerName, this.connectedResourceName)
      }

      this.loading = false
      return true
    },

    handleControllerChange() {
      if (this.isDeviceResourceLocked) {
        return
      }
      this.selectedDeviceKey = null
      this.resource = null
      this.resourcesList = []

      const capability = this.controllerCapabilities.find(
        (item) => item.display_label === this.selectedController,
      )
      if (capability?.type === "PlayCover" && !this.playCoverAddress) {
        this.playCoverAddress = getPlayCoverDefaultAddress(this.controllerCapabilities)
      }

      void this.fetchDevices(capability?.name).then((ok) => {
        if (ok) return this.getResourceList()
      })
    },

    openDevices() {
      if (
        this.isDeviceResourceLocked ||
        !this.selectedControllerCapability ||
        this.selectedControllerCapability.type === "PlayCover"
      ) {
        return
      }
      void this.fetchDevices(this.selectedControllerCapability.name)
    },

    // --- Custom device creation ---
    isStillOnController(controllerName: string): boolean {
      return this.selectedControllerCapability?.name === controllerName
    },

    handleCustomDeviceSaveFailure(previousKey: string | null, message?: string) {
      // Preserve previous selection on save failure
      this.selectedDeviceKey = previousKey
      showGlobalMessage("error", message || "保存自定义设备失败")
    },

    async selectPersistedCustomDevice(persisted: ConnectableDevice, controllerName: string) {
      const applied = await this.fetchDevices(controllerName)
      // Stale GET discarded by request-id — do not reselect on old controller
      if (!applied) {
        return
      }
      if (!this.isStillOnController(controllerName)) {
        return
      }

      const matched = findDeviceByIdentityOrFingerprint(this.availableDevices, persisted)
      if (matched) {
        this.selectedDeviceKey = buildDeviceFingerprint(matched)
        return
      }

      // Do not append client-only fallback — backend list is source of truth
      showGlobalMessage("error", "自定义设备已保存，但刷新列表后未找到该设备")
    },

    async createCustomDevice(rawAddress: string) {
      if (this.isDeviceResourceLocked) {
        return
      }
      const capability = this.selectedControllerCapability
      if (!capability || capability.type === "PlayCover") {
        return
      }

      const parseResult = customDeviceAddressSchema.safeParse({
        type: capability.type,
        address: rawAddress,
      })
      if (!parseResult.success) {
        return
      }
      const address = parseResult.data.address

      const controllerName = capability.name
      const previousKey = this.selectedDeviceKey

      const [result] = await tryCatch(() =>
        postCustomDevice({
          controller_name: controllerName,
          type: capability.type,
          address,
        }),
      )

      // Still on the same controller after POST? (user may have switched meanwhile)
      if (!this.isStillOnController(controllerName)) {
        return
      }

      if (!result?.success || !result.data) {
        this.handleCustomDeviceSaveFailure(previousKey, result?.message)
        return
      }

      await this.selectPersistedCustomDevice(result.data, controllerName)
    },

    buildPlayCoverDevice(): { device: PlayCoverDevice } | { error: string } {
      const t = i18n.global.t
      const parseResult = playCoverAddressSchema.safeParse(this.playCoverAddress)
      if (!parseResult.success) {
        const msg = this.playCoverAddress.trim()
          ? t("panel.invalidPlaycoverAddress")
          : t("panel.playcoverAddress")
        return { error: msg }
      }
      return { device: { type: "PlayCover", address: parseResult.data } }
    },

    // --- Connection ---
    async connectDevices(): Promise<PostDeviceResult> {
      const t = i18n.global.t

      if (this.isDeviceResourceLocked) {
        return { success: false, message: "设备与资源已锁定，无法切换" }
      }

      const selectedCapability = this.selectedControllerCapability
      if (!selectedCapability || this.selectedControllerDisabled) {
        return { success: false, message: t("panel.selectDeviceType") }
      }

      let currentDevice: ConnectableDevice | null = null
      if (selectedCapability.type === "PlayCover") {
        const playCoverResult = this.buildPlayCoverDevice()
        if ("error" in playCoverResult) {
          return { success: false, message: playCoverResult.error }
        }
        currentDevice = playCoverResult.device
      }

      if (!currentDevice) {
        currentDevice = this.selectedDevice
      }

      if (!currentDevice) {
        return { success: false, message: t("panel.selectDevice") }
      }

      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()

      const result = await postDevices({
        controller_name: selectedCapability.name,
        device: currentDevice,
      })

      indexStore.setConnected(result.success)
      if (result.success) {
        const storedDevice = await this.persistLastConnectedDevice(
          currentDevice,
          selectedCapability.name,
        )
        if (storedDevice) {
          await settingsStore.addRecentDevice(storedDevice)
        }
        await this.getResourceList()
        await this.syncDeviceRuntimeState()
      }
      return result
    },

    async getResourceList() {
      const capability = this.selectedControllerCapability
      if (this.isDeviceResourceLocked || !capability) {
        return
      }

      const requestId = ++this._fetchResourcesRequestId
      const settingsStore = useSettingsStore()
      this.resourcesList = []
      this.loading = true

      const [resourceData] = await tryCatch(() => getResource(capability.type))
      if (requestId !== this._fetchResourcesRequestId) {
        return
      }
      if (!resourceData) {
        this.loading = false
        return
      }

      this.resourcesList = resourceData.map((item) => ({
        label: item.label || item.name,
        value: item.name,
      }))
      const savedResource = settingsStore.settings.panel.lastResource
      if (savedResource && resourceData.some((item) => item.name === savedResource)) {
        this.resource = savedResource
      }
      this.loading = false
    },

    async postResourceSelection(): Promise<PostResourceResult> {
      const t = i18n.global.t

      if (this.isDeviceResourceLocked) {
        return { success: false, message: "设备与资源已锁定，无法切换" }
      }
      if (!this.isCurrentSelectionConnected) {
        return { success: false, message: t("panel.connectFirstHint") }
      }
      if (!this.resource) {
        return { success: false, message: t("panel.selectResource") }
      }

      const result = await postResource(this.resource)
      if (result.success) {
        await this.persistLastResource(this.resource)
        await this.syncDeviceRuntimeState()
      }
      return result
    },

    // --- Task control ---
    async StartTask(): Promise<boolean> {
      const outcome = await this.requestTaskStart()
      if (outcome.kind === "conflict") {
        // No toast here — StartConflictDialog renders from startConflict
        this.startConflict = outcome.conflict
        return false
      }
      // 启动成功或非冲突失败都清掉过期冲突，避免对话框停留在已失效的状态。
      this.startConflict = null
      return outcome.kind === "started"
    },

    /**
     * Issue one start request without touching `startConflict`.
     * `stopActiveAndRestart` retries a busy_manual conflict through this action,
     * so a transient rejection must not flash StartConflictDialog.
     */
    async requestTaskStart(): Promise<StartOutcome> {
      const t = i18n.global.t
      const indexStore = useIndexStore()
      const interfaceStore = useInterfaceStore()
      const configStore = useTaskConfigStore()

      await this.syncDeviceRuntimeState()

      const alreadyConnected =
        indexStore.Connected &&
        this.isDeviceResourceLocked &&
        this.connectedControllerName === this.selectedControllerName &&
        this.connectedResourceName === this.resource

      if (!alreadyConnected) {
        const connectResult = await this.connectDevices()
        if (!connectResult.success) {
          showGlobalMessage("error", "设备连接失败: " + connectResult.message)
          return { kind: "failed" }
        }

        const resourceResult = await this.postResourceSelection()
        if (!resourceResult.success) {
          showGlobalMessage("error", "资源设置失败: " + resourceResult.message)
          return { kind: "failed" }
        }
      }

      const isTaskCompatibleInCurrentContext = (taskId: string) =>
        interfaceStore.isTaskCompatibleByName(taskId, this.selectedControllerName, this.resource)

      const selectedTaskIds = configStore.selectedTaskIds
      const allCompatibleTaskIds = interfaceStore.getTaskList
        .map((task) => task.id)
        .filter((taskId) => isTaskCompatibleInCurrentContext(taskId))

      const compatibleTaskIds = selectedTaskIds.filter((taskId) =>
        isTaskCompatibleInCurrentContext(taskId),
      )

      if (compatibleTaskIds.length === 0) {
        if (allCompatibleTaskIds.length === 0) {
          showGlobalMessage("error", t("panel.noCompatibleTask"))
          return { kind: "failed" }
        }
        showGlobalMessage("error", t("panel.selectTask"))
        return { kind: "failed" }
      }

      const base = configStore.buildExecutionPayload(compatibleTaskIds)
      const controllerName = this.selectedControllerName || ""
      const deviceType = this.selectedControllerCapability?.type || "Adb"
      let deviceAddress = buildDeviceAddress(this.selectedDevice)
      if (deviceType === "PlayCover") {
        const playCoverResult = this.buildPlayCoverDevice()
        if ("error" in playCoverResult) {
          showGlobalMessage("error", "设备连接失败: " + playCoverResult.error)
          return { kind: "failed" }
        }
        deviceAddress = playCoverResult.device.address
      }

      const payload: ManualStartPayload = {
        ...base,
        controller_name: controllerName,
        device: {
          controller_name: controllerName,
          device_type: deviceType,
          device_address: deviceAddress,
        },
        resource_name: this.resource || "",
      }

      const result = await startTask(payload)
      if (result.accepted) {
        indexStore.setTaskRunning(true)
        return { kind: "started" }
      }
      if (result.conflict) {
        return { kind: "conflict", conflict: result.conflict }
      }
      return { kind: "failed" }
    },

    clearStartConflict() {
      this.startConflict = null
    },

    /**
     * Stop the active run, then start the current selection again.
     * Concurrent callers share one in-flight sequence; `cleanup()` cancels it.
     */
    stopActiveAndRestart(): Promise<boolean> {
      if (restartInFlight) {
        return restartInFlight
      }
      const controller = new AbortController()
      restartAbort = controller
      const pending = this.runStopAndRestart(controller.signal).finally(() => {
        if (restartInFlight === pending) {
          restartInFlight = null
        }
        if (restartAbort === controller) {
          restartAbort = null
        }
      })
      restartInFlight = pending
      return pending
    },

    async runStopAndRestart(signal: AbortSignal): Promise<boolean> {
      const stopped = await stopTask()
      if (!stopped) {
        return false
      }
      this.clearStartConflict()

      // TaskRunning 先有界等待：正常情况下它由终端事件清除。
      const indexStore = useIndexStore()
      const released = await waitUntilTaskStopped(() => indexStore.TaskRunning, signal)
      if (signal.aborted) {
        return false
      }
      if (!released) {
        showGlobalMessage("error", i18n.global.t("settings.scheduler.conflict.stopTimeout"))
        return false
      }
      return this.startTaskWithRetry(signal)
    },

    /**
     * Retry while the backend still reports busy_manual: after a refresh TaskRunning
     * is already false while `active_run` is not cleared yet, and `/api/stop` returns
     * before that happens. Other conflicts and failures are surfaced immediately.
     */
    async startTaskWithRetry(signal: AbortSignal): Promise<boolean> {
      const deadline = Date.now() + START_RETRY_DEADLINE_MS
      let conflict: StartConflict | null = null

      while (!signal.aborted && Date.now() <= deadline) {
        const outcome = await this.requestTaskStart()
        if (signal.aborted) {
          return false
        }
        if (outcome.kind === "started") {
          this.startConflict = null
          return true
        }
        if (outcome.kind === "failed") {
          this.startConflict = null
          return false
        }
        if (outcome.conflict.code !== "busy_manual") {
          this.startConflict = outcome.conflict
          return false
        }
        conflict = outcome.conflict

        await sleepUntilAborted(START_RETRY_INTERVAL_MS, signal)
        if (signal.aborted) {
          return false
        }
      }

      if (signal.aborted) {
        return false
      }
      // 重试耗尽：只在这里暴露一次冲突，避免对话框在两次尝试之间闪烁。
      this.startConflict = conflict
      return false
    },

    // --- Config reset ---
    resetConfig() {
      const t = i18n.global.t
      const configStore = useTaskConfigStore()

      if (confirm(t("panel.resetConfigConfirm"))) {
        void configStore.resetConfig()
        showGlobalMessage("success", t("panel.configReset"))
      }
    },

    // --- Lifecycle ---
    init() {
      if (this.initialized) {
        return
      }
      this.initialized = true

      const indexStore = useIndexStore()
      const configStore = useTaskConfigStore()
      const settingsStore = useSettingsStore()

      const scheduleTaskConfigSave = () => {
        if (configStore.configLoaded) {
          configStore.debouncedSave()
        }
      }

      // Sync device state
      void this.syncDeviceRuntimeState()

      const fetchSavedDevice = () => {
        const savedDevice = settingsStore.settings.panel.lastConnectedDevice
        void this.fetchDevices(savedDevice?.controller_name, true).then((ok) => {
          if (ok) return this.getResourceList()
        })
      }

      // Fetch settings if not initialized
      const settingsPromise = settingsStore.initialized
        ? Promise.resolve()
        : settingsStore.fetchSettings()
      void settingsPromise.then(() => fetchSavedDevice())

      // Start device state poll timer
      this.deviceStatePollTimer = window.setInterval(() => {
        if (!indexStore.Connected && !this.isDeviceResourceLocked) {
          return
        }
        void this.syncDeviceRuntimeState()
      }, 3000)

      // Set up watchers
      const stop1 = watch(
        () => configStore.taskList.length,
        (length) => {
          if (length > 0) {
            indexStore.SelectTask(configStore.taskList[0].id)
          }
        },
        { immediate: true },
      )

      const stop2 = watch(() => configStore.taskList, scheduleTaskConfigSave, { deep: true })

      const stop3 = watch(() => configStore.options, scheduleTaskConfigSave, { deep: true })

      const stop4 = watch(() => configStore.preTasks, scheduleTaskConfigSave, { deep: true })

      const stop5 = watch(() => configStore.selectedPresetName, scheduleTaskConfigSave)

      const stop6 = watch(
        () => indexStore.Connected,
        (connected) => {
          if (!connected) {
            this.isDeviceResourceLocked = false
          }
        },
      )

      watcherStopHandles = [stop1, stop2, stop3, stop4, stop5, stop6]
    },

    cleanup() {
      restartAbort?.abort()
      restartAbort = null
      restartInFlight = null

      if (this.deviceStatePollTimer !== null) {
        window.clearInterval(this.deviceStatePollTimer)
        this.deviceStatePollTimer = null
      }

      watcherStopHandles.forEach((stop) => stop())
      watcherStopHandles = []

      this.initialized = false
    },
  },
})

// --- Helper functions used by the store ---

/**
 * Wait (bounded) until the SSE terminal event clears TaskRunning.
 * A cleared flag is necessary but not sufficient: after a page refresh it already
 * reads false while the backend may still be releasing `active_run`, so callers
 * must also retry busy_manual. `signal` cancels the wait on view teardown.
 */
function waitUntilTaskStopped(isRunning: () => boolean, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) {
    return Promise.resolve(false)
  }
  if (!isRunning()) {
    return Promise.resolve(true)
  }
  return new Promise<boolean>((resolve) => {
    let stopWatching: (() => void) | null = null
    let timer: number | null = null
    let released = false
    const finish = () => {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
      signal.removeEventListener("abort", finish)
      stopWatching?.()
      resolve(released)
    }
    timer = window.setTimeout(finish, STOP_WAIT_TIMEOUT_MS)
    signal.addEventListener("abort", finish, { once: true })
    stopWatching = watch(isRunning, (running) => {
      if (!running) {
        released = true
        finish()
      }
    })
  })
}

/** Resolve after `ms`, or immediately once `signal` aborts. */
function sleepUntilAborted(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) {
    return Promise.resolve()
  }
  return new Promise<void>((resolve) => {
    let timer: number | null = null
    const finish = () => {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
      signal.removeEventListener("abort", finish)
      resolve()
    }
    timer = window.setTimeout(finish, ms)
    signal.addEventListener("abort", finish, { once: true })
  })
}

/** Backend device_address format per device type (mirrors maa_worker/device_service.py). */
function buildDeviceAddress(device: ConnectableDevice | null): string {
  if (!device) {
    return ""
  }
  if (isWin32Device(device)) {
    return String(device.hWnd)
  }
  if (isGamepadDevice(device)) {
    return `${device.hWnd}|${device.gamepad_type}`
  }
  return device.address
}

function buildStoredLastConnectedDevice(
  deviceInfo: ConnectableDevice,
  controllerName: string,
): PanelLastConnectedDevice {
  if (isAdbDevice(deviceInfo)) {
    return {
      type: "Adb",
      controller_name: controllerName,
      fingerprint: buildDeviceFingerprint(deviceInfo),
      adb_path: deviceInfo.adb_path,
      address: deviceInfo.address,
      class_name: "",
      window_name: "",
      hWnd: 0,
      gamepad_type: 0,
      uuid: "",
    }
  }
  if (isWin32Device(deviceInfo)) {
    return {
      type: "Win32",
      controller_name: controllerName,
      fingerprint: buildDeviceFingerprint(deviceInfo),
      adb_path: "",
      address: "",
      class_name: deviceInfo.class_name,
      window_name: deviceInfo.window_name,
      hWnd: deviceInfo.hWnd,
      gamepad_type: 0,
      uuid: "",
    }
  }
  if (isGamepadDevice(deviceInfo)) {
    return {
      type: "Gamepad",
      controller_name: controllerName,
      fingerprint: buildDeviceFingerprint(deviceInfo),
      adb_path: "",
      address: "",
      class_name: deviceInfo.class_name,
      window_name: deviceInfo.window_name,
      hWnd: deviceInfo.hWnd,
      gamepad_type: deviceInfo.gamepad_type,
      uuid: "",
    }
  }
  if (deviceInfo.type === "Linux") {
    return {
      type: "Linux",
      controller_name: controllerName,
      fingerprint: buildDeviceFingerprint(deviceInfo),
      adb_path: "",
      address: deviceInfo.address,
      class_name: "",
      window_name: deviceInfo.name || "",
      hWnd: 0,
      gamepad_type: 0,
      uuid: "",
    }
  }
  return {
    type: "PlayCover",
    controller_name: controllerName,
    fingerprint: buildDeviceFingerprint(deviceInfo),
    adb_path: "",
    address: deviceInfo.address,
    class_name: "",
    window_name: deviceInfo.name || "",
    hWnd: 0,
    gamepad_type: 0,
    uuid: deviceInfo.uuid || "",
  }
}
