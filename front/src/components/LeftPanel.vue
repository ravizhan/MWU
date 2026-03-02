<template>
  <n-card content-style="padding: 0;margin: 5px" hoverable>
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" :tab="t('panel.device')">
        <n-flex class="pb-[12px]" :wrap="false">
          <n-select
            v-model:value="selectedController"
            :placeholder="t('panel.selectDeviceType')"
            :options="controllerOptions"
            :loading="loading"
            @update:value="handleControllerChange"
            class="max-w-35%"
          />
          <n-input
            v-if="selectedController === 'PlayCover'"
            v-model:value="playCoverAddress"
            :placeholder="t('panel.playcoverAddress')"
            class="max-w-45%"
          />
          <n-select
            v-else
            v-model:value="selectedDeviceKey"
            :placeholder="t('panel.selectDevice')"
            :options="deviceOptions"
            :loading="loading"
            :disabled="!selectedController || selectedControllerDisabled"
            @click="refreshDevices"
            class="max-w-45%"
          />
          <n-button strong secondary type="info" @click="connectDevices">{{
            t("panel.connect")
          }}</n-button>
        </n-flex>
      </n-tab-pane>
      <n-tab-pane name="resource" :tab="t('panel.resource')">
        <n-flex class="pb-[12px]">
          <n-select
            v-model:value="resource"
            :placeholder="t('panel.selectResource')"
            :options="resources_list"
            :loading="loading"
            remote
            @click="getResourceList"
            class="max-w-80%"
          />
          <n-button strong secondary type="info" @click="post_resource">{{
            t("panel.confirm")
          }}</n-button>
        </n-flex>
      </n-tab-pane>
    </n-tabs>
  </n-card>
  <div class="col-name">{{ t("panel.taskList") }}</div>
  <n-card hoverable>
    <TaskSelectList
      :tasks="configStore.taskList"
      :selected-tasks="selectedTaskIds"
      :scrollable="scroll_show"
      @update:tasks="handleTasksUpdate"
      @update:selected-tasks="handleSelectedTasksUpdate"
      @config="handleConfigTask"
    />
    <n-flex class="form-btn" justify="center">
      <n-button strong secondary type="info" size="large" @click="StartTask">{{
        t("panel.start")
      }}</n-button>
      <n-button strong secondary type="info" size="large" @click="stopTask">{{
        t("panel.stop")
      }}</n-button>
    </n-flex>
    <n-flex class="form-btn" justify="center">
      <n-button quaternary type="warning" size="small" @click="resetConfig">{{
        t("panel.resetConfig")
      }}</n-button>
    </n-flex>
  </n-card>
</template>
<script setup lang="ts">
import { watch, ref, computed, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import {
  type DeviceControllerCapability,
  type DeviceControllerType,
  getDevices,
  postDevices,
  startTask,
  stopTask,
  type AdbDevice,
  type ConnectableDevice,
  type GamepadDevice,
  type PlayCoverDevice,
  type Win32Device,
  getResource,
  postResource,
} from "../script/api"
import { useTaskConfigStore } from "../stores/taskConfig"
import { useIndexStore } from "../stores"
import { useSettingsStore } from "../stores/settings"
import type { PanelLastConnectedDevice } from "../types/settings"
import { useMessage, useDialog } from "naive-ui"
import TaskSelectList from "./TaskSelectList.vue"
import type { TaskListItem } from "../stores/interface"

const message = useMessage()
const dialog = useDialog()
const { t } = useI18n()
const configStore = useTaskConfigStore()
const indexStore = useIndexStore()
const settingsStore = useSettingsStore()

if (typeof window !== "undefined") {
  window.$message = message
}

const scroll_show = ref(window.innerWidth > 768)
const selectedController = ref<DeviceControllerType | null>(null)
const selectedDeviceKey = ref<string | null>(null)
const availableDevices = ref<ConnectableDevice[]>([])
const controllerCapabilities = ref<DeviceControllerCapability[]>([])
const playCoverAddress = ref("")
const resource = ref<string | null>(null)
const resources_list = ref<Array<{ label: string; value: string }>>([])
const loading = ref(false)

const selectedTaskIds = computed(() => {
  return configStore.taskList.filter((task) => task.checked).map((task) => task.id)
})

const controllerOptions = computed(() => {
  return controllerCapabilities.value.map((item) => ({
    label: item.label,
    value: item.type,
    disabled: !item.enabled,
  }))
})

const selectedControllerCapability = computed(() => {
  if (!selectedController.value) {
    return null
  }
  return controllerCapabilities.value.find((item) => item.type === selectedController.value) || null
})

const selectedControllerDisabled = computed(() => {
  return selectedControllerCapability.value ? !selectedControllerCapability.value.enabled : false
})

const deviceOptions = computed(() => {
  if (availableDevices.value.length === 0) {
    return [
      {
        label: t("panel.noDevice"),
        value: "none-device",
        disabled: true,
      },
    ]
  }
  return availableDevices.value.map((item) => ({
    label: buildDeviceLabel(item),
    value: buildDeviceFingerprint(item),
  }))
})

const selectedDevice = computed(() => {
  if (!selectedDeviceKey.value) {
    return null
  }
  return (
    availableDevices.value.find(
      (item) => buildDeviceFingerprint(item) === selectedDeviceKey.value,
    ) || null
  )
})

function handleTasksUpdate(tasks: TaskListItem[]) {
  configStore.taskList = tasks
}

function handleSelectedTasksUpdate(selectedIds: string[]) {
  configStore.taskList = configStore.taskList.map((task) => ({
    ...task,
    checked: selectedIds.includes(task.id),
  }))
}

function handleConfigTask(taskId: string) {
  indexStore.SelectTask(taskId)
}

function saveTaskConfig() {
  if (configStore.configLoaded) {
    configStore.debouncedSave()
  }
}

watch(
  () => configStore.taskList.length,
  (length) => {
    if (length > 0) {
      indexStore.SelectTask(configStore.taskList[0]!.id)
    }
  },
  { immediate: true },
)

watch(() => configStore.taskList, saveTaskConfig, { deep: true })
watch(() => configStore.options, saveTaskConfig, { deep: true })

function isAdbDevice(value: unknown): value is AdbDevice {
  if (!value || typeof value !== "object") return false
  const candidate = value as Partial<AdbDevice>
  return candidate.type === "Adb"
}

function isWin32Device(value: unknown): value is Win32Device {
  if (!value || typeof value !== "object") return false
  const candidate = value as Partial<Win32Device>
  return candidate.type === "Win32"
}

function isGamepadDevice(value: unknown): value is GamepadDevice {
  if (!value || typeof value !== "object") return false
  const candidate = value as Partial<GamepadDevice>
  return candidate.type === "Gamepad"
}

function buildDeviceLabel(deviceInfo: ConnectableDevice): string {
  if (isAdbDevice(deviceInfo)) {
    return `${deviceInfo.name} (${deviceInfo.address})`
  }
  if (isWin32Device(deviceInfo) || isGamepadDevice(deviceInfo)) {
    return `${deviceInfo.window_name} (${deviceInfo.class_name})`
  }
  return deviceInfo.address
}

function buildDeviceFingerprint(deviceInfo: ConnectableDevice): string {
  if (isAdbDevice(deviceInfo)) {
    return `adb|${deviceInfo.adb_path}|${deviceInfo.address}`
  }
  if (isWin32Device(deviceInfo)) {
    return `win32|${deviceInfo.hWnd}`
  }
  if (isGamepadDevice(deviceInfo)) {
    return `gamepad|${deviceInfo.hWnd}|${deviceInfo.gamepad_type}`
  }
  return `playcover|${deviceInfo.address}|${deviceInfo.uuid}`
}

function getPlayCoverDefaultAddress(capabilities: DeviceControllerCapability[]): string {
  const playCoverCapability = capabilities.find((item) => item.type === "PlayCover")
  return playCoverCapability?.default_address || "127.0.0.1:1717"
}

function getStoredDeviceFingerprint(stored: PanelLastConnectedDevice): string {
  if (stored.fingerprint) {
    return stored.fingerprint
  }
  const normalizedType = stored.type.toLowerCase()
  if (normalizedType === "adb") {
    return `adb|${stored.adb_path}|${stored.address}`
  }
  if (normalizedType === "win32") {
    return `win32|${stored.hWnd}`
  }
  if (normalizedType === "gamepad") {
    return `gamepad|${stored.hWnd}|${stored.gamepad_type}`
  }
  return `playcover|${stored.address}|${stored.uuid}`
}

async function persistLastConnectedDevice(deviceInfo: ConnectableDevice) {
  let storedDevice: PanelLastConnectedDevice

  if (isAdbDevice(deviceInfo)) {
    storedDevice = {
      type: "Adb",
      fingerprint: buildDeviceFingerprint(deviceInfo),
      adb_path: deviceInfo.adb_path,
      address: deviceInfo.address,
      class_name: "",
      window_name: "",
      hWnd: 0,
      gamepad_type: 0,
      uuid: "",
    }
  } else if (isWin32Device(deviceInfo)) {
    storedDevice = {
      type: "Win32",
      fingerprint: buildDeviceFingerprint(deviceInfo),
      adb_path: "",
      address: "",
      class_name: deviceInfo.class_name,
      window_name: deviceInfo.window_name,
      hWnd: deviceInfo.hWnd,
      gamepad_type: 0,
      uuid: "",
    }
  } else if (isGamepadDevice(deviceInfo)) {
    storedDevice = {
      type: "Gamepad",
      fingerprint: buildDeviceFingerprint(deviceInfo),
      adb_path: "",
      address: "",
      class_name: deviceInfo.class_name,
      window_name: deviceInfo.window_name,
      hWnd: deviceInfo.hWnd,
      gamepad_type: deviceInfo.gamepad_type,
      uuid: "",
    }
  } else {
    storedDevice = {
      type: "PlayCover",
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

  await settingsStore.updateSetting("panel", "lastConnectedDevice", storedDevice)
}

async function persistLastResource(name: string) {
  await settingsStore.updateSetting("panel", "lastResource", name)
}

function restoreLastConnectedDevice() {
  const savedDevice = settingsStore.settings.panel.lastConnectedDevice
  if (!savedDevice || !selectedController.value) {
    return
  }
  if (savedDevice.type !== selectedController.value) {
    return
  }

  if (savedDevice.type === "PlayCover") {
    playCoverAddress.value =
      savedDevice.address || getPlayCoverDefaultAddress(controllerCapabilities.value)
    return
  }

  const targetFingerprint = getStoredDeviceFingerprint(savedDevice)
  const matchedDevice = availableDevices.value.find((item) => {
    if (buildDeviceFingerprint(item) === targetFingerprint) {
      return true
    }
    if (isWin32Device(item)) {
      return `${item.class_name}|${item.window_name}` === targetFingerprint
    }
    return false
  })
  selectedDeviceKey.value = matchedDevice ? buildDeviceFingerprint(matchedDevice) : null
}

async function fetchDevices(controller?: DeviceControllerType, restoreStored = false) {
  loading.value = true
  try {
    const data = await getDevices(controller)
    controllerCapabilities.value = data.controllers
    selectedController.value = data.selected_type

    if (!data.selected_type) {
      availableDevices.value = []
      selectedDeviceKey.value = null
      return
    }

    if (data.selected_type === "PlayCover") {
      availableDevices.value = []
      selectedDeviceKey.value = null
      if (restoreStored) {
        restoreLastConnectedDevice()
      }
      if (!playCoverAddress.value) {
        playCoverAddress.value = getPlayCoverDefaultAddress(data.controllers)
      }
      return
    }

    availableDevices.value = data.devices
    if (restoreStored) {
      restoreLastConnectedDevice()
    }
  } finally {
    loading.value = false
  }
}

function handleControllerChange(value: DeviceControllerType) {
  selectedDeviceKey.value = null
  if (value === "PlayCover" && !playCoverAddress.value) {
    playCoverAddress.value = getPlayCoverDefaultAddress(controllerCapabilities.value)
  }
  void fetchDevices(value)
}

function refreshDevices() {
  if (!selectedController.value || selectedController.value === "PlayCover") {
    return
  }
  void fetchDevices(selectedController.value)
}

async function connectDevices() {
  if (!selectedController.value) {
    message.error(t("panel.selectDeviceType"))
    return
  }

  if (selectedControllerDisabled.value) {
    message.error(t("panel.selectDeviceType"))
    return
  }

  let currentDevice: ConnectableDevice | null = null
  if (selectedController.value === "PlayCover") {
    const address = playCoverAddress.value.trim()
    if (!address) {
      message.error(t("panel.playcoverAddress"))
      return
    }
    const regex = /^((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)\.?\b){4}:\d{1,5}$/
    if (!regex.test(address)) {
      message.error(t("panel.invalidPlaycoverAddress"))
    }
    currentDevice = {
      type: "PlayCover",
      address,
    }
  } else {
    currentDevice = selectedDevice.value
  }

  if (!currentDevice) {
    message.error(t("panel.selectDevice"))
    return
  }

  const success = await postDevices(currentDevice)
  indexStore.setConnected(success)
  if (success) {
    await persistLastConnectedDevice(currentDevice)
  }
}

async function getResourceList() {
  resources_list.value = []
  loading.value = true

  try {
    const resource_data = await getResource()
    for (const item of resource_data) {
      resources_list.value.push({
        label: item,
        value: item,
      })
    }

    const savedResource = settingsStore.settings.panel.lastResource
    if (savedResource && resource_data.includes(savedResource)) {
      resource.value = savedResource
    }
  } finally {
    loading.value = false
  }
}

async function post_resource() {
  if (!resource.value) {
    message.error(t("panel.selectResource"))
    return
  }

  const success = await postResource(resource.value)
  if (success) {
    await persistLastResource(resource.value)
  }
}

onMounted(async () => {
  if (!settingsStore.initialized) {
    await settingsStore.fetchSettings()
  }

  await Promise.all([
    fetchDevices(settingsStore.settings.panel.lastConnectedDevice?.type, true),
    getResourceList(),
  ])
})

function StartTask() {
  const payload = configStore.buildExecutionPayload(selectedTaskIds.value)
  if (payload.task_list.length === 0) {
    message.error(t("panel.selectTask"))
    return
  }
  startTask(payload)
}

function resetConfig() {
  dialog.warning({
    title: t("panel.resetConfig"),
    content: t("panel.resetConfigConfirm"),
    positiveText: t("common.confirm"),
    negativeText: t("common.cancel"),
    onPositiveClick: async () => {
      await configStore.resetConfig()
      message.success(t("panel.configReset"))
    },
  })
}
</script>
<style scoped>
.list-group-item i {
  cursor: pointer;
}
.form-btn {
  text-align: center;
  padding-top: 5%;
}
</style>
