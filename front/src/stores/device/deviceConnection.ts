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

/** In-flight stopActiveAndRestart promise; concurrent calls coalesce onto this one operation. */
let activeRestartPromise: Promise<boolean> | null = null
/** Cleanup handles (release watcher / retry timers) for the currently in-flight restart op. */
let activeRestartCleanup: (() => void)[] = []

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
    showElevationPrompt: boolean
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
    showElevationPrompt: false,
    _fetchDevicesRequestId: 0,
    _fetchResourcesRequestId: 0,
  }),

  // ---------------------------------------------------------------------------
  // Getters: derived selection & connection state
  // ---------------------------------------------------------------------------
  getters: {
    controllerOptions(state) {
      return state.controllerCapabilities.map((item) => ({
        label: item.display_label,
        value: item.display_label,
        disabled: !item.enabled,
      }))
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

    resetDeviceLoading(requestId: number) {
      if (requestId === this._fetchDevicesRequestId) {
        this.loading = false
      }
    },

    async fetchDevices(controllerName?: string, restoreStored = false) {
      const requestId = ++this._fetchDevicesRequestId
      this.loading = true

      const [data] = await tryCatch(() => getDevices(controllerName))
      if (!data || requestId !== this._fetchDevicesRequestId) {
        this.resetDeviceLoading(requestId)
        return false
      }

      const selectedCapability = this.applyControllerData(data)
      if (!selectedCapability) {
        this.availableDevices = []
        this.selectedDeviceKey = null
        this.resetDeviceLoading(requestId)
        return true
      }

      this.applyDeviceData(selectedCapability, data, restoreStored)

      // After capabilities load, re-apply locked runtime selection as authority
      if (this.isDeviceResourceLocked && this.connectedControllerName) {
        this.hydrateLockedSelection(this.connectedControllerName, this.connectedResourceName)
      }

      this.resetDeviceLoading(requestId)
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
    isStillOnController(controllerName: string, displayLabel: string): boolean {
      return (
        this.selectedControllerCapability?.name === controllerName ||
        this.selectedController === displayLabel
      )
    },

    handleCustomDeviceSaveFailure(previousKey: string | null, message?: string) {
      // Preserve previous selection on save failure
      this.selectedDeviceKey = previousKey
      showGlobalMessage("error", message || "保存自定义设备失败")
    },

    async selectPersistedCustomDevice(
      persisted: ConnectableDevice,
      controllerName: string,
      displayLabel: string,
    ) {
      const applied = await this.fetchDevices(controllerName)
      // Stale GET discarded by request-id — do not reselect on old controller
      if (!applied) {
        return
      }
      if (!this.isStillOnController(controllerName, displayLabel)) {
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
      const displayLabel = capability.display_label
      const previousKey = this.selectedDeviceKey

      const [result] = await tryCatch(() =>
        postCustomDevice({
          controller_name: controllerName,
          type: capability.type,
          address,
        }),
      )

      // Still on the same controller after POST? (user may have switched meanwhile)
      if (!this.isStillOnController(controllerName, displayLabel)) {
        return
      }

      if (!result?.success || !result.data) {
        this.handleCustomDeviceSaveFailure(previousKey, result?.message)
        return
      }

      await this.selectPersistedCustomDevice(result.data, controllerName, displayLabel)
    },

    buildPlayCoverDevice(): { device: ConnectableDevice } | { error: string } {
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
      // 新契约：/api/device 平面请求携带必需 resource_name（准备并连接）
      if (!this.resource) {
        return { success: false, message: t("panel.selectResource") }
      }

      const indexStore = useIndexStore()
      const settingsStore = useSettingsStore()

      const result = await postDevices({
        controller_name: selectedCapability.name,
        device: currentDevice,
        resource_name: this.resource,
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

    resetResourceLoading(requestId: number) {
      if (requestId === this._fetchResourcesRequestId) {
        this.loading = false
      }
    },

    async getResourceList() {
      if (this.isDeviceResourceLocked || !this.selectedControllerCapability) {
        return
      }

      const requestId = ++this._fetchResourcesRequestId
      const settingsStore = useSettingsStore()
      this.resourcesList = []
      this.loading = true

      const capability = this.selectedControllerCapability
      if (!capability) {
        this.resetResourceLoading(requestId)
        return
      }

      const [resourceData] = await tryCatch(() => getResource(capability.type))
      if (!resourceData || requestId !== this._fetchResourcesRequestId) {
        this.resetResourceLoading(requestId)
        return
      }

      this.resourcesList = resourceData.map((item) => ({ label: item.name, value: item.name }))
      const savedResource = settingsStore.settings.panel.lastResource
      if (savedResource && resourceData.some((item) => item.name === savedResource)) {
        this.resource = savedResource
      }
      this.resetResourceLoading(requestId)
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
      const t = i18n.global.t
      const indexStore = useIndexStore()
      const interfaceStore = useInterfaceStore()
      const configStore = useTaskConfigStore()

      const selectedCapability = this.selectedControllerCapability
      if (!selectedCapability || this.selectedControllerDisabled) {
        showGlobalMessage("error", t("panel.selectDeviceType"))
        return false
      }

      let selectedDevice: ConnectableDevice | null = null
      if (selectedCapability.type === "PlayCover") {
        const playCoverResult = this.buildPlayCoverDevice()
        if ("error" in playCoverResult) {
          showGlobalMessage("error", "设备连接失败: " + playCoverResult.error)
          return false
        }
        selectedDevice = playCoverResult.device
      } else {
        selectedDevice = this.selectedDevice
        if (!selectedDevice) {
          showGlobalMessage("error", t("panel.selectDevice"))
          return false
        }
      }

      if (!this.resource) {
        showGlobalMessage("error", t("panel.selectResource"))
        return false
      }

      const isTaskCompatibleInCurrentContext = (taskId: string) =>
        interfaceStore.isTaskCompatibleByName(taskId, selectedCapability.name, this.resource)

      const selectedTaskIds = configStore.selectedTaskIds
      const allCompatibleTaskIds = configStore.taskList
        .map((task) => task.id)
        .filter((taskId) => isTaskCompatibleInCurrentContext(taskId))

      const compatibleTaskIds = selectedTaskIds.filter((taskId) =>
        isTaskCompatibleInCurrentContext(taskId),
      )

      if (compatibleTaskIds.length === 0) {
        if (allCompatibleTaskIds.length === 0) {
          showGlobalMessage("error", t("panel.noCompatibleTask"))
          return false
        }
        showGlobalMessage("error", t("panel.selectTask"))
        return false
      }

      const base = configStore.buildExecutionPayload(compatibleTaskIds)
      const controllerName = selectedCapability.name
      const deviceType = selectedCapability.type
      const deviceAddress = buildDeviceAddress(selectedDevice)

      const payload: ManualStartPayload = {
        ...base,
        task_identity: "name",
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
        // 清掉重试路径留下的过期冲突，避免 StartConflictDialog 在运行中弹出
        this.startConflict = null
        return true
      }
      if (result.conflict) {
        // No toast here — StartConflictDialog renders from startConflict
        this.startConflict = result.conflict ?? null
        return false
      }
      if (result.error) {
        showGlobalMessage("error", result.error)
        // 管理员权限不足：展示“以管理员权限重启”确认入口
        if (result.error.includes("permission_required")) {
          this.showElevationPrompt = true
        }
      }
      // 非冲突失败同样清掉过期冲突：否则 stopActiveAndRestart 的重试条件
      // 会拿着旧的 busy_manual 继续空转，对话框也停留在已失效的冲突状态。
      this.startConflict = null
      return false
    },

    clearStartConflict() {
      this.startConflict = null
    },

    async stopActiveAndRestart(): Promise<boolean> {
      // 并发保护：双击等重入调用 coalesce 到同一操作上，避免出现两套 stop/等待/重试循环。
      if (activeRestartPromise) {
        return activeRestartPromise
      }

      const runRestart = async (): Promise<boolean> => {
        const attempt = async (): Promise<boolean> => {
          const stopped = await stopTask()
          if (!stopped) {
            return false
          }
          this.clearStartConflict()
          // 等待后端工作线程结束：SSE task.completed/failed 由 dispatcher 置 TaskRunning=false。
          // 注意：后端终端事件在 run_process 的 finally 之前发出（task_service.py），即事件
          // 先于 active_run 清槽（execution.py 的 _complete_run 收尾），因此 TaskRunning=false
          // 不代表准入槽位已释放，下方必须对 busy_manual 冲突做有限重试。
          const indexStore = useIndexStore()
          const released = await new Promise<boolean>((resolve) => {
            if (!indexStore.TaskRunning) {
              resolve(true)
              return
            }
            const timer = window.setTimeout(() => {
              releaseWatch?.()
              resolve(false)
            }, 30_000)
            let releaseWatch: (() => void) | null = null
            releaseWatch = watch(
              () => indexStore.TaskRunning,
              (running) => {
                if (!running) {
                  window.clearTimeout(timer)
                  releaseWatch?.()
                  resolve(true)
                }
              },
            )
            // 注册到 store 清理机制：导航/卸载时取消挂起的等待与定时器，并中止本次操作。
            activeRestartCleanup.push(() => {
              window.clearTimeout(timer)
              releaseWatch?.()
              resolve(false)
            })
          })
          if (!released) {
            const t = i18n.global.t
            showGlobalMessage("error", t("settings.scheduler.conflict.stopTimeout"))
            return false
          }
          // active_run 清槽晚于终端事件（落库在 asyncio.to_thread 中），轮询重试直至准入成功；
          // 仅对 busy_manual 重试——busy_scheduled/update_in_progress 是真实占用，立即返回冲突。
          // 上限 60s：后端收尾含 sqlite 落库，正常在数百毫秒内完成。
          const deadline = Date.now() + 60_000
          let restarted = await this.StartTask()
          while (!restarted && this.startConflict?.code === "busy_manual") {
            // 睡前的 deadline 检查：已到上限即不再重试。
            if (Date.now() >= deadline) {
              break
            }
            const slept = await new Promise<boolean>((resolve) => {
              const timer = window.setTimeout(() => resolve(true), 500)
              activeRestartCleanup.push(() => {
                window.clearTimeout(timer)
                resolve(false)
              })
            })
            // 睡后再次检查 deadline，确保不会在超时之后仍发起启动尝试。
            if (!slept || Date.now() >= deadline) {
              break
            }
            restarted = await this.StartTask()
          }
          return restarted
        }
        const [result] = await tryCatch(attempt)
        // 统一清理：无论成功/失败/异常，释放挂起的清理器与重入守卫。
        activeRestartCleanup.forEach((fn) => fn())
        activeRestartCleanup = []
        activeRestartPromise = null
        return result ?? false
      }

      activeRestartPromise = runRestart()
      return activeRestartPromise
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
      if (this.deviceStatePollTimer !== null) {
        window.clearInterval(this.deviceStatePollTimer)
        this.deviceStatePollTimer = null
      }

      watcherStopHandles.forEach((stop) => stop())
      watcherStopHandles = []

      // 取消进行中的 stopActiveAndRestart（释放等待 watcher、重试定时器），避免卸载后继续空转。
      activeRestartCleanup.forEach((fn) => fn())
      activeRestartCleanup = []
      activeRestartPromise = null

      this.initialized = false
    },
  },
})

// --- Helper functions used by the store ---

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
  if (device.type === "MacOS") {
    return String(device.window_id)
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
  if (deviceInfo.type === "MacOS") {
    return {
      type: "MacOS",
      controller_name: controllerName,
      fingerprint: buildDeviceFingerprint(deviceInfo),
      adb_path: "",
      address: String(deviceInfo.window_id),
      class_name: "",
      window_name: deviceInfo.window_name,
      hWnd: 0,
      gamepad_type: 0,
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
