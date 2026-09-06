<template>
  <template v-if="option && applicable">
    <div
      class="flex items-center justify-between w-full gap-4 py-2 px-3 border-b border-solid last:border-b-0"
      :style="{
        paddingLeft: (level || 0) * 20 + 12 + 'px',
        borderBottomColor: 'var(--divider-color)',
      }"
    >
      <div class="min-w-0 flex-1 text-sm">{{ resolvedLabel }}</div>
      <div class="flex flex-1 justify-end">
        <OptionSwitchControl
          v-if="option.type === 'switch'"
          v-model:value="switchValue"
          :option="option"
        />
        <OptionSelectControl
          v-else-if="option.type === 'select'"
          v-model:value="selectValue"
          :options="selectOptions"
        />
        <OptionSelectControl
          v-else-if="option.type === 'scan_select'"
          v-model:value="selectValue"
          :options="selectOptions"
          :refreshing="scanSelectRefreshing"
          show-rescan
          @rescan="handleRescanScanSelect"
        />
        <OptionInputControl
          v-else-if="option.type === 'input'"
          v-model:value="inputValue"
          :option="option"
        />
        <OptionCheckboxControl
          v-else-if="option.type === 'checkbox'"
          v-model:value="checkboxValue"
          :option="option"
        />
        <OptionHotkeyControl
          v-else-if="option.type === 'hotkey'"
          v-model:value="hotkeyValue"
          :option="option"
        />
      </div>
    </div>

    <template v-if="nestedOptions.length > 0">
      <OptionItem
        v-for="childName in nestedOptions"
        :key="childName"
        :name="childName"
        :level="(level || 0) + 1"
        :task-options="taskOptions"
      />
    </template>
  </template>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { showGlobalMessage } from "@/services/feedback/message"
import { useInterfaceStore } from "@/stores"
import type {
  CheckboxOption,
  ScanSelectOption,
  SelectOption,
  SwitchOption,
} from "@/types/interfaceModel"
import type { NullableTaskOptionValue } from "@/types/schedulerModel"
import { useDeviceConnectionStore } from "@/stores"
import { resolveInterfaceText } from "@/utils/interface/content"
import { isOptionApplicable } from "@/utils/interface/applicability"
import { tryCatch } from "@/utils/tryCatch"
import OptionCheckboxControl from "@/components/common/controls/OptionCheckboxControl.vue"
import OptionHotkeyControl from "@/components/common/controls/OptionHotkeyControl.vue"
import OptionInputControl from "@/components/common/controls/OptionInputControl.vue"
import OptionSelectControl from "@/components/common/controls/OptionSelectControl.vue"
import OptionSwitchControl from "@/components/common/controls/OptionSwitchControl.vue"

const {
  name,
  level,
  taskOptions: rawTaskOptions,
} = defineProps<{
  name: string
  level?: number
  taskOptions: Record<string, NullableTaskOptionValue>
}>()

const { locale } = useI18n()
const interfaceStore = useInterfaceStore()
const deviceStore = useDeviceConnectionStore()
const taskOptions = computed(() => rawTaskOptions)
const option = computed(() => interfaceStore.interface?.option?.[name])
// 不适用的 option 隐藏子树；值保留在 taskOptions 中，切回环境即恢复
// option.controller 存的是规范控制器名，必须用 selectedControllerName
// （selectedController 是 UI display_label，label≠name 时会误判不适用）。
const applicable = computed(() =>
  isOptionApplicable(
    option.value,
    deviceStore.selectedControllerName,
    deviceStore.resource || null,
  ),
)
const scanSelectRefreshing = ref(false)

const resolvedLabel = computed(() =>
  resolveInterfaceText(interfaceStore.interface, locale.value, option.value?.label, name),
)

function normalizeObjectValue(value: NullableTaskOptionValue | undefined): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {}
  return Object.fromEntries(
    Object.entries(value).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  )
}

const switchValue = computed<string>({
  get() {
    const value = taskOptions.value[name]
    return typeof value === "string" ? value : ""
  },
  set(value) {
    taskOptions.value[name] = value
  },
})

const selectValue = computed<string | null>({
  get() {
    const value = taskOptions.value[name]
    return typeof value === "string" ? value : null
  },
  set(value) {
    taskOptions.value[name] = value
  },
})

const inputValue = computed<Record<string, string>>({
  get() {
    return normalizeObjectValue(taskOptions.value[name])
  },
  set(value) {
    taskOptions.value[name] = value
  },
})

const hotkeyValue = computed<Record<string, string>>({
  get() {
    return normalizeObjectValue(taskOptions.value[name])
  },
  set(value) {
    taskOptions.value[name] = value
  },
})

const checkboxValue = computed<string[]>({
  get() {
    const value = taskOptions.value[name]
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : []
  },
  set(value) {
    taskOptions.value[name] = value
  },
})

function resolveCaseLabel(label: string | undefined, fallback: string): string {
  return resolveInterfaceText(interfaceStore.interface, locale.value, label, fallback)
}

const selectOptions = computed(() => {
  const currentOption = option.value
  if (currentOption?.type !== "select" && currentOption?.type !== "scan_select") return []
  return currentOption.cases.map((caseItem) => ({
    label: resolveCaseLabel(caseItem.label, caseItem.name),
    value: caseItem.name,
  }))
})

const isSelectValueInvalid = computed(() => {
  const currentOption = option.value
  if (currentOption?.type !== "select" && currentOption?.type !== "scan_select") return false
  const currentValue = taskOptions.value[name]
  if (currentValue == null || typeof currentValue !== "string") return false
  return !selectOptions.value.some((item) => item.value === currentValue)
})

watch(
  () => isSelectValueInvalid.value,
  (invalid) => {
    if (invalid) taskOptions.value[name] = null
  },
  { immediate: true },
)

async function handleRescanScanSelect(): Promise<void> {
  const currentOption = option.value
  if (!currentOption || currentOption.type !== "scan_select") return

  const previousValue = taskOptions.value[name]
  scanSelectRefreshing.value = true
  taskOptions.value[name] = null
  const [, err] = await tryCatch(() => interfaceStore.rescanScanSelectOption(name))
  if (err) {
    taskOptions.value[name] = previousValue
    if (err.message) showGlobalMessage("error", err.message)
  }
  scanSelectRefreshing.value = false
}

function getSwitchNestedOptions(currentOption: SwitchOption): string[] {
  const activeCase = currentOption.cases.find(
    (caseItem) => caseItem.name === taskOptions.value[name],
  )
  return activeCase?.option || []
}

function getSelectNestedOptions(currentOption: SelectOption | ScanSelectOption): string[] {
  const activeCase = currentOption.cases.find(
    (caseItem) => caseItem.name === taskOptions.value[name],
  )
  return activeCase?.option || []
}

function getCheckboxNestedOptions(currentOption: CheckboxOption): string[] {
  const activeNames = new Set(checkboxValue.value)
  const childNames: string[] = []
  const seen = new Set<string>()

  for (const caseItem of currentOption.cases) {
    if (!activeNames.has(caseItem.name)) continue
    for (const childName of caseItem.option || []) {
      if (seen.has(childName)) continue
      seen.add(childName)
      childNames.push(childName)
    }
  }
  return childNames
}

const nestedOptions = computed(() => {
  const currentOption = option.value
  if (!currentOption) return []
  if (currentOption.type === "switch") return getSwitchNestedOptions(currentOption)
  if (currentOption.type === "select" || currentOption.type === "scan_select") {
    return getSelectNestedOptions(currentOption)
  }
  if (currentOption.type === "checkbox") return getCheckboxNestedOptions(currentOption)
  return []
})
</script>
