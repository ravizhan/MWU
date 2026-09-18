<template>
  <div class="flex w-full max-w-sm flex-col gap-2">
    <div v-for="hotkey in option.hotkeys" :key="hotkey.name" class="flex flex-col gap-1">
      <span class="text-xs opacity-60">{{ resolveHotkeyLabel(hotkey.label, hotkey.name) }}</span>
      <InterfaceDescription :text="hotkey.description" />
      <NInput
        size="small"
        readonly
        :value="capturingName === hotkey.name ? '' : getHotkeyValue(hotkey.name)"
        :placeholder="capturingName === hotkey.name ? t('option.hotkeyCapturing') : undefined"
        :status="captureError?.name === hotkey.name ? 'error' : undefined"
        @focus="startCapture(hotkey.name)"
        @blur="handleBlur(hotkey.name)"
        @keydown="handleKeydown(hotkey.name, $event)"
      />
      <span v-if="captureError?.name === hotkey.name" class="text-xs text-error">
        {{ captureError.message }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "@/stores"
import type { HotkeyOption } from "@/types/interfaceModel"
import { buildHotkeyCombo, getHotkeyCaptureIssue } from "@/utils/hotkey"
import { resolveInterfaceText } from "@/utils/interface/content"
import InterfaceDescription from "@/components/common/InterfaceDescription.vue"

const { option, value } = defineProps<{
  option: HotkeyOption
  value: Record<string, string>
}>()

const emit = defineEmits<{
  (event: "update:value", value: Record<string, string>): void
}>()

const { locale, t } = useI18n()
const interfaceStore = useInterfaceStore()
const capturingName = ref<string | null>(null)
const captureError = ref<{ name: string; message: string } | null>(null)

function resolveHotkeyLabel(label: string | undefined, fallback: string): string {
  return resolveInterfaceText(interfaceStore.interface, locale.value, label, fallback)
}

function getHotkeyValue(name: string): string {
  return value[name] ?? ""
}

function startCapture(name: string): void {
  capturingName.value = name
  captureError.value = null
}

function handleBlur(name: string): void {
  if (capturingName.value === name) {
    capturingName.value = null
  }
}

function handleKeydown(name: string, event: KeyboardEvent): void {
  event.preventDefault()
  const issue = getHotkeyCaptureIssue(event)
  if (issue) {
    const messageKey =
      issue === "unsupported_key" ? "option.hotkeyUnsupportedKey" : "option.hotkeyTooManyModifiers"
    captureError.value = { name, message: t(messageKey) }
    return
  }
  const combo = buildHotkeyCombo(event)
  if (!combo) return
  captureError.value = null
  emit("update:value", { ...value, [name]: combo })
}
</script>
