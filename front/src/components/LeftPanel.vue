<template>
  <n-card content-style="padding: 0;margin: 5px" hoverable>
    <n-tabs type="segment" animated>
      <n-tab-pane name="device" :tab="t('panel.device')">
        <n-flex class="pb-[12px]">
          <n-tree-select
            v-model:value="device"
            :placeholder="t('panel.selectDevice')"
            :options="devices_tree"
            :loading="loading"
            :override-default-node-click-behavior="override"
            remote
            indent="6"
            @click="get_device"
            class="max-w-80%"
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
            @click="get_resource"
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
import type { TreeSelectOverrideNodeClickBehavior } from "naive-ui"
import { useMessage, useDialog } from "naive-ui"
import TaskSelectList from "./TaskSelectList.vue"
import type { TaskListItem } from "../stores/interface"

if (typeof window !== "undefined") {
  window.$message = useMessage()
}

const dialog = useDialog()
const { t } = useI18n()
const configStore = useTaskConfigStore()
const indexStore = useIndexStore()
const settingsStore = useSettingsStore()
const scroll_show = ref(window.innerWidth > 768)
const device = ref<ConnectableDevice | null>(null)
const resource = ref<string | null>(null)
const devices_tree = ref<object[]>([])
const resources_list = ref<object[]>([])
const loading = ref(false)
const override: TreeSelectOverrideNodeClickBehavior = ({ option }) => {
  if (option.children) {
    return "toggleExpand"
  }
  return "default"
}

// 计算选中的任务ID列表
const selectedTaskIds = computed(() => {
  return configStore.taskList.filter((task) => task.checked).map((task) => task.id)
})

// 处理任务列表更新（拖拽排序）
function handleTasksUpdate(tasks: TaskListItem[]) {
  configStore.taskList = tasks
}

// 处理选中状态更新
function handleSelectedTasksUpdate(selectedIds: string[]) {
  configStore.taskList = configStore.taskList.map((task) => ({
    ...task,
    checked: selectedIds.includes(task.id),
  }))
}

// 处理配置任务
function handleConfigTask(taskId: string) {
  indexStore.SelectTask(taskId)
}

watch(
  () => configStore.taskList,
  (newList) => {
    if (newList.length) {
      indexStore.SelectTask(newList[0]!.id)
    }
  },
  { immediate: true },
)

watch(
  () => configStore.taskList,
  () => {
    if (configStore.configLoaded) {
      configStore.debouncedSave()
    }
  },
  { deep: true },
)

watch(
  () => configStore.options,
  () => {
    if (configStore.configLoaded) {
      configStore.debouncedSave()
    }
  },
  { deep: true },
)

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
      window_name: deviceInfo.name,
      hWnd: 0,
      gamepad_type: 0,
      uuid: deviceInfo.uuid,
    }
  }

  await settingsStore.updateSetting("panel", "lastConnectedDevice", storedDevice)
}

async function persistLastResource(name: string) {
  await settingsStore.updateSetting("panel", "lastResource", name)
}

async function get_device() {
  devices_tree.value = [
    {
      label: "Adb",
      key: "Adb",
      children: [],
    },
    {
      label: "Win32",
      key: "Win32",
      children: [],
    },
    {
      label: "Gamepad",
      key: "Gamepad",
      children: [],
    },
    {
      label: "PlayCover",
      key: "PlayCover",
      children: [],
    },
  ]

  loading.value = true
  try {
    const devices_data = await getDevices()

    for (const dev of devices_data.adb) {
      ;(devices_tree.value[0] as any).children.push({
        label: dev.name + " (" + dev.address + ")",
        key: dev,
      })
    }

    for (const dev of devices_data.win32) {
      ;(devices_tree.value[1] as any).children.push({
        label: dev.window_name + " (" + dev.class_name + ")",
        key: dev,
      })
    }

    for (const dev of devices_data.gamepad) {
      ;(devices_tree.value[2] as any).children.push({
        label: dev.window_name + " (" + dev.class_name + ")",
        key: dev,
      })
    }

    for (const dev of devices_data.playcover) {
      ;(devices_tree.value[3] as any).children.push({
        label: dev.name + " (" + dev.address + ")",
        key: dev,
      })
    }

    const savedDevice = settingsStore.settings.panel.lastConnectedDevice
    if (savedDevice) {
      const targetFingerprint = getStoredDeviceFingerprint(savedDevice)
      const allDevices: ConnectableDevice[] = [
        ...devices_data.adb,
        ...devices_data.win32,
        ...devices_data.gamepad,
        ...devices_data.playcover,
      ]
      const matchedDevice = allDevices.find((dev) => {
        if (buildDeviceFingerprint(dev) === targetFingerprint) {
          return true
        }
        if (isWin32Device(dev)) {
          return `${dev.class_name}|${dev.window_name}` === targetFingerprint
        }
        return false
      })
      device.value = matchedDevice || null
    }

    const emptyGroupKeys = ["none-adb", "none-win32", "none-gamepad", "none-playcover"]
    for (let i = 0; i < devices_tree.value.length; i++) {
      if ((devices_tree.value[i] as any).children.length === 0) {
        ;(devices_tree.value[i] as any).children.push({
          label: t("panel.noDevice"),
          key: emptyGroupKeys[i],
          disabled: true,
        })
      }
    }
  } finally {
    loading.value = false
  }
}

async function connectDevices() {
  if (!device.value) {
    // @ts-ignore
    window.$message.error(t("panel.selectDevice"))
    return
  }

  const success = await postDevices(device.value)
  indexStore.setConnected(success)
  if (success) {
    await persistLastConnectedDevice(device.value)
  }
}

async function get_resource() {
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
    // @ts-ignore
    window.$message.error(t("panel.selectResource"))
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

  await Promise.all([get_device(), get_resource()])
})

function StartTask() {
  const selectedTaskIds = configStore.taskList.filter((task) => task.checked).map((task) => task.id)
  const payload = configStore.buildExecutionPayload(selectedTaskIds)
  if (payload.task_list.length === 0) {
    // @ts-ignore
    window.$message.error(t("panel.selectTask"))
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
      // @ts-ignore
      window.$message.success(t("panel.configReset"))
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
