<template>
  <div class="flex flex-wrap gap-2">
    <NSelect
      :value="selectedController"
      :options="controllerOptions"
      :placeholder="t('panel.selectDeviceType')"
      :disabled="disabled"
      class="flex-1 min-w-[8rem]"
      @update:value="handleControllerUpdate"
    />
    <NInput
      v-if="isPlayCover"
      :value="playCoverAddress"
      :placeholder="t('panel.playcoverAddress')"
      :disabled="disabled"
      class="flex-1 min-w-[10rem]"
      @update:value="emit('update:play-cover-address', $event)"
    />
    <NSelect
      v-else
      filterable
      tag
      :value="selectedDeviceKey"
      :options="deviceOptions"
      :placeholder="t('panel.selectDevice')"
      :disabled="!selectedController || selectedControllerDisabled || disabled"
      class="flex-1 min-w-[10rem]"
      :on-create="(label: string) => ({ label, value: label })"
      @update:value="handleDeviceSelect"
      @update:show="(show: boolean) => show && emit('open-devices')"
    />
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"

const {
  selectedController,
  selectedDeviceKey,
  playCoverAddress,
  controllerOptions,
  deviceOptions,
  disabled,
  selectedControllerDisabled,
  isPlayCover,
} = defineProps<{
  selectedController: string | null
  selectedDeviceKey: string | null
  playCoverAddress: string
  controllerOptions: Array<{ label: string; value: string; disabled?: boolean }>
  deviceOptions: Array<{ label: string; value: string; disabled?: boolean }>
  disabled: boolean
  selectedControllerDisabled: boolean
  isPlayCover: boolean
}>()

const emit = defineEmits<{
  (e: "update:selected-controller", value: string | null): void
  (e: "update:selected-device-key", value: string | null): void
  (e: "update:play-cover-address", value: string): void
  (e: "controller-change"): void
  (e: "open-devices"): void
  (e: "create-device", value: string): void
}>()

const { t } = useI18n()

function handleControllerUpdate(value: string | null) {
  emit("update:selected-controller", value)
  if (value !== selectedController) {
    emit("controller-change")
  }
}

// Device-instance select: a value that is not one of the backend-provided
// options is a brand-new (user-typed) entry — route it through the create
// flow (side effect) instead of a plain select.
function handleDeviceSelect(value: string | null) {
  if (value && !deviceOptions.some((opt) => opt.value === value)) {
    emit("create-device", value)
    return
  }
  emit("update:selected-device-key", value)
}
</script>
