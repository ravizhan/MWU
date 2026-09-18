<template>
  <div class="flex w-full max-w-sm flex-col gap-2">
    <div v-for="input in option.inputs" :key="input.name" class="flex flex-col gap-1">
      <span class="text-xs opacity-60">{{ resolveInputLabel(input.label, input.name) }}</span>
      <InterfaceDescription :text="input.description" />
      <NInputNumber
        v-if="getInputControlType(input) === 'number'"
        size="small"
        :value="getInputNumberValue(input.name)"
        :status="isInputError(input.name, input.verify) ? 'error' : undefined"
        @update:value="handleInputNumberChange(input.name, $event, input)"
      />
      <NSwitch
        v-else-if="getInputControlType(input) === 'bool'"
        size="small"
        :value="getBooleanInputValue(input.name)"
        @update:value="handleBooleanInputChange(input.name, $event, input)"
      />
      <NInput
        v-else-if="getInputControlType(input) === 'textarea'"
        type="textarea"
        size="small"
        :value="getInputValue(input.name)"
        :status="isInputError(input.name, input.verify) ? 'error' : undefined"
        @update:value="handleInputChange(input.name, $event, input)"
      />
      <NInput
        v-else
        size="small"
        :value="getInputValue(input.name)"
        :status="isInputError(input.name, input.verify) ? 'error' : undefined"
        @update:value="handleInputChange(input.name, $event, input)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"
import { showGlobalMessage } from "@/services/feedback/message"
import { useInterfaceStore } from "@/stores"
import type { InputCase, InputOption } from "@/types/interfaceModel"
import { resolveInterfaceText } from "@/utils/interface/content"
import { makeInterfaceInputSchema } from "@/validation/interfaceInput"
import InterfaceDescription from "@/components/common/InterfaceDescription.vue"

const { option, value } = defineProps<{
  option: InputOption
  value: Record<string, string>
}>()

const emit = defineEmits<{
  (event: "update:value", value: Record<string, string>): void
}>()

const { locale } = useI18n()
const interfaceStore = useInterfaceStore()
const inputInvalidState = ref<Record<string, boolean>>({})

type InputControlType = "string" | "number" | "bool" | "textarea"

function resolveInputLabel(label: string | undefined, fallback: string): string {
  return resolveInterfaceText(interfaceStore.interface, locale.value, label, fallback)
}

function getInputValue(inputName: string): string {
  return value[inputName] ?? ""
}

function setInputValue(inputName: string, nextValue: string): void {
  emit("update:value", { ...value, [inputName]: nextValue })
}

function isInputAllowed(value: string, verify?: string): boolean {
  if (!verify || value === "") return true
  return makeInterfaceInputSchema(verify).safeParse(value).success
}

function isInputError(inputName: string, verify?: string): boolean {
  return !isInputAllowed(getInputValue(inputName), verify)
}

function handleInputChange(inputName: string, value: string, input: InputCase): void {
  const allowed = isInputAllowed(value, input.verify)
  const wasInvalid = inputInvalidState.value[inputName] === true

  if (allowed) {
    setInputValue(inputName, value)
    inputInvalidState.value = { ...inputInvalidState.value, [inputName]: false }
    return
  }

  inputInvalidState.value = { ...inputInvalidState.value, [inputName]: true }
  if (!wasInvalid && input.pattern_msg) {
    const message = resolveInterfaceText(
      interfaceStore.interface,
      locale.value,
      input.pattern_msg,
      input.pattern_msg,
    )
    showGlobalMessage("error", message)
  }
}

function getInputControlType(input: InputCase): InputControlType {
  const pipelineType: string | undefined = input.pipeline_type
  if (pipelineType === "int" || pipelineType === "number") return "number"
  if (pipelineType === "bool") return "bool"
  if (pipelineType === "textarea") return "textarea"
  return "string"
}

function getInputNumberValue(inputName: string): number | null {
  const value = getInputValue(inputName)
  if (!value.trim()) return null
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : null
}

function handleInputNumberChange(inputName: string, value: number | null, input: InputCase): void {
  handleInputChange(inputName, value == null ? "" : String(value), input)
}

function getBooleanInputValue(inputName: string): boolean {
  return ["true", "True", "TRUE", "yes", "Yes", "Y", "y", "1", "on", "On", "ON"].includes(
    getInputValue(inputName),
  )
}

function handleBooleanInputChange(
  inputName: string,
  value: string | number | boolean,
  input: InputCase,
): void {
  const checked = value === true || value === 1 || value === "true" || value === "1"
  handleInputChange(inputName, checked ? "true" : "false", input)
}
</script>
