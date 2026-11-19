<template>
  <div class="flex flex-wrap gap-2">
    <NSelect
      :value="selectedController"
      :options="controllerOptions"
      :render-label="renderIconLabel"
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
    <div v-if="needsScreenSize" class="flex basis-full gap-2">
      <NInputNumber
        :value="screenWidth || null"
        :min="1"
        :precision="0"
        :show-button="false"
        :placeholder="t('panel.screenWidth')"
        :disabled="disabled"
        class="flex-1"
        @update:value="emit('update:screen-width', $event ?? 0)"
      />
      <NInputNumber
        :value="screenHeight || null"
        :min="1"
        :precision="0"
        :show-button="false"
        :placeholder="t('panel.screenHeight')"
        :disabled="disabled"
        class="flex-1"
        @update:value="emit('update:screen-height', $event ?? 0)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { renderIconLabel } from "@/utils/interface/iconLabel"

const {
  selectedController,
  selectedDeviceKey,
  playCoverAddress,
  controllerOptions,
  deviceOptions,
  disabled,
  selectedControllerDisabled,
  isPlayCover,
  needsScreenSize,
  screenWidth,
  screenHeight,
} = defineProps<{
  selectedController: string | null
  selectedDeviceKey: string | null
  playCoverAddress: string
  controllerOptions: Array<{
    label: string
    value: string
    icon?: string | null
    disabled?: boolean
  }>
  deviceOptions: Array<{ label: string; value: string; disabled?: boolean }>
  disabled: boolean
  selectedControllerDisabled: boolean
  isPlayCover: boolean
  needsScreenSize: boolean
  screenWidth: number
  screenHeight: number
}>()

const emit = defineEmits<{
  (e: "update:selected-controller", value: string | null): void
  (e: "update:selected-device-key", value: string | null): void
  (e: "update:play-cover-address", value: string): void
  (e: "update:screen-width", value: number): void
  (e: "update:screen-height", value: number): void
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
