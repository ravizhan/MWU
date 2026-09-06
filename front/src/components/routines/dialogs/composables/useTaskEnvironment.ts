import { computed, ref, watch, type Ref } from "vue"
import { useI18n } from "vue-i18n"
import { useInterfaceStore, useSettingsStore } from "@/stores"
import { customDeviceAddressSchema } from "@/validation/device"
import { resolveInterfaceText } from "@/utils/interface/content"
import { getDevices, getResource, postCustomDevice } from "@/services/api"
import type { ConnectableDevice, DeviceControllerType, ResourceInfo } from "@/services/api"
import { buildDeviceLabel, getDeviceIdentity, getStoredDeviceIdentity } from "@/utils/panel/device"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"
import type { PanelLastConnectedDevice } from "@/types/settingsModel"
import type { SchedulerTaskFormData } from "./useSchedulerTaskForm"

export interface TaskEnvironment {
  availableDevices: Ref<ConnectableDevice[]>
  availableResources: Ref<ResourceInfo[]>
  loadingDevices: Ref<boolean>
  loadingResources: Ref<boolean>
  selectedControllerType: Ref<DeviceControllerType | null>
  isPlayCover: Ref<boolean>
  deviceControllerOptions: Ref<Array<{ label: string; value: string }>>
  deviceAddressOptions: Ref<Array<{ label: string; value: string }>>
  resourceOptions: Ref<Array<{ label: string; value: string }>>
  selectedDeviceAddress: Ref<string | null>
  handleDeviceAddressUpdate: (value: string | null) => void
}

function isDeviceControllerType(type: string): type is DeviceControllerType {
  return (
    type === "Adb" ||
    type === "Win32" ||
    type === "Gamepad" ||
    type === "PlayCover" ||
    type === "MacOS" ||
    type === "Linux"
  )
}

function buildStoredDeviceLabel(device: PanelLastConnectedDevice): string {
  if (device.type === "Adb") {
    return device.address
  }
  if (device.type === "Win32" || device.type === "Gamepad") {
    const name = device.window_name || device.class_name
    return name ? `${name} (${device.hWnd})` : String(device.hWnd)
  }
  if (device.type === "MacOS" || device.type === "Linux") {
    const name = device.window_name.trim()
    return name ? `${name} (${device.address})` : device.address
  }
  return device.address
}

export function useTaskEnvironment(
  formData: Ref<SchedulerTaskFormData>,
  suppressFormInit: Ref<boolean>,
): TaskEnvironment {
  const { t, locale } = useI18n()
  const interfaceStore = useInterfaceStore()
  const settingsStore = useSettingsStore()
  const interfaceModel = computed(() => interfaceStore.interface ?? null)

  const availableDevices = ref<ConnectableDevice[]>([])
  const availableResources = ref<ResourceInfo[]>([])
  const loadingDevices = ref(false)
  const loadingResources = ref(false)

  const selectedControllerType = computed<DeviceControllerType | null>(() => {
    const controller = interfaceModel.value?.controller?.find(
      (item) => item.name === formData.value.controller_name,
    )
    const type = controller?.type
    return type && isDeviceControllerType(type) ? type : null
  })

  const isPlayCover = computed(() => selectedControllerType.value === "PlayCover")

  const deviceControllerOptions = computed(() =>
    (interfaceModel.value?.controller || [])
      .filter((controller) => isDeviceControllerType(controller.type))
      .map((controller) => ({
        label: resolveInterfaceText(
          interfaceModel.value,
          locale.value,
          controller.label,
          controller.name,
        ),
        value: controller.name,
      })),
  )

  const deviceAddressOptions = computed(() => {
    if (!formData.value.controller_name) {
      return []
    }

    const options = new Map<string, { label: string; value: string }>()
    for (const device of availableDevices.value) {
      const value = getDeviceIdentity(device)
      options.set(value, { label: buildDeviceLabel(device), value })
    }

    const recentDevices = settingsStore.settings.panel.recentDevices ?? []
    for (const device of recentDevices) {
      if (device.controller_name !== formData.value.controller_name) {
        continue
      }
      const value = getStoredDeviceIdentity(device)
      if (options.has(value)) {
        continue
      }
      options.set(value, { label: buildStoredDeviceLabel(device), value })
    }

    return Array.from(options.values())
  })

  const resourceOptions = computed(() =>
    availableResources.value.map((resource) => ({
      label: resolveInterfaceText(
        interfaceModel.value,
        locale.value,
        resource.label,
        resource.name,
      ),
      value: resource.name,
    })),
  )

  const selectedDeviceAddress = computed<string | null>({
    get: () => formData.value.device?.device_address ?? null,
    set: (value) => {
      const controller = interfaceModel.value?.controller?.find(
        (item) => item.name === formData.value.controller_name,
      )
      if (!controller || !value) {
        formData.value.device = null
        return
      }
      if (!isDeviceControllerType(controller.type)) {
        formData.value.device = null
        return
      }
      formData.value.device = {
        controller_name: controller.name,
        device_type: controller.type,
        device_address: value,
      }
    },
  })

  async function fetchDevices(controllerName: string) {
    loadingDevices.value = true
    const [data, err] = await tryCatch(() => getDevices(controllerName))
    loadingDevices.value = false
    if (err) {
      console.error("Failed to fetch devices:", err)
      availableDevices.value = []
      return
    }
    availableDevices.value = data.devices
  }

  async function fetchResources(controllerType: string) {
    loadingResources.value = true
    const [data, err] = await tryCatch(() => getResource(controllerType))
    loadingResources.value = false
    if (err) {
      console.error("Failed to fetch resources:", err)
      availableResources.value = []
      return
    }
    availableResources.value = data
  }

  // 控制器切换时清空设备与资源选择，并拉取新控制器下的可用项
  watch(
    () => formData.value.controller_name,
    (newVal, oldVal) => {
      const controller = interfaceModel.value?.controller?.find((item) => item.name === newVal)
      const type = controller?.type

      if (!suppressFormInit.value && oldVal != null && oldVal !== newVal) {
        formData.value.device = null
        formData.value.resource_name = null
      }

      if (newVal && type) {
        void fetchDevices(newVal)
        void fetchResources(type)
        return
      }
      availableDevices.value = []
      availableResources.value = []
    },
  )

  /** Persist a user-typed device address as a custom device and select it. */
  async function handleCustomDeviceCreate(rawAddress: string) {
    const controllerName = formData.value.controller_name
    const controllerType = selectedControllerType.value
    if (!controllerName || !controllerType || !isDeviceControllerType(controllerType)) return

    const parseResult = customDeviceAddressSchema.safeParse({
      type: controllerType,
      address: rawAddress,
    })
    if (!parseResult.success) {
      showGlobalMessage("error", t("settings.scheduler.rules.invalidAddress"))
      return
    }
    const address = parseResult.data.address

    const [result, err] = await tryCatch(() =>
      postCustomDevice({
        controller_name: controllerName,
        type: controllerType,
        address,
      }),
    )
    if (err || !result?.success) {
      showGlobalMessage("error", result?.message || t("settings.scheduler.dialog.saveFail"))
      return
    }

    // Refresh device list so the new device appears, then select it
    await fetchDevices(controllerName)
    // 用户在请求期间可能已切换控制器：仅当当前选择仍匹配才写入地址，避免把旧地址落到别的控制器上。
    const currentControllerName = formData.value.controller_name
    const currentControllerType = selectedControllerType.value
    if (currentControllerName !== controllerName || currentControllerType !== controllerType) {
      return
    }
    selectedDeviceAddress.value = address
  }

  function handleDeviceAddressUpdate(value: string | null) {
    if (value && !deviceAddressOptions.value.some((option) => option.value === value)) {
      void handleCustomDeviceCreate(value)
      return
    }
    selectedDeviceAddress.value = value
  }

  return {
    availableDevices,
    availableResources,
    loadingDevices,
    loadingResources,
    selectedControllerType,
    isPlayCover,
    deviceControllerOptions,
    deviceAddressOptions,
    resourceOptions,
    selectedDeviceAddress,
    handleDeviceAddressUpdate,
  }
}
