<template>
  <template v-if="option">
    <n-list-item>
      <div
        :style="{ paddingLeft: (level || 0) * 20 + 'px' }"
        class="flex items-center justify-between w-full"
      >
        <div class="mr-4">{{ label || name }}</div>
        <div class="flex-1 flex justify-end">
          <!-- Switch -->
          <template v-if="option.type === 'switch'">
            <n-switch
              :checked-value="
                ['Yes', 'yes', 'Y', 'y'].includes(option.cases[1].name)
                  ? option.cases[1].name
                  : option.cases[0].name
              "
              :unchecked-value="
                ['Yes', 'yes', 'Y', 'y'].includes(option.cases[1].name)
                  ? option.cases[0].name
                  : option.cases[1].name
              "
              :round="false"
              v-model:value="options[name]"
            />
          </template>
          <!-- Select -->
          <template v-else-if="option.type === 'select'">
            <n-select class="w-40" :options="selectOptions" v-model:value="options[name]" />
          </template>
          <!-- Input -->
          <template v-else-if="option.type === 'input'">
            <div class="flex flex-col gap-2 w-full max-w-xs">
              <div v-for="input in option.inputs" :key="input.name" class="flex flex-col gap-1">
                <span class="text-sm text-gray-500">{{ input.label || input.name }}</span>
                <n-input
                  v-model:value="options[`${name}_${input.name}`]"
                  :allow-input="(v: string) => handleAllowInput(v, input.verify, input.pattern_msg)"
                />
              </div>
            </div>
          </template>
        </div>
      </div>
    </n-list-item>

    <!-- Recursive children -->
    <template v-if="nestedOptions.length > 0">
      <OptionItem
        v-for="childName in nestedOptions"
        :key="childName"
        :name="childName"
        :level="(level || 0) + 1"
        :options="options"
      />
    </template>
  </template>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useInterfaceStore } from "../stores/interface"
import { useTaskConfigStore } from "../stores/taskConfig"
import { storeToRefs } from "pinia"
import { useMessage } from "naive-ui"

const props = defineProps<{
  name: string
  level?: number
  options?: Record<string, any>
}>()

const message = useMessage()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const options = props.options ? computed(() => props.options!) : storeToRefs(configStore).options

const option = computed(() => interfaceStore.interface?.option?.[props.name])
const label = computed(() => option.value?.label)

const selectOptions = computed(() => {
  const opt = option.value
  if (opt?.type === "select") {
    return opt.cases.map((c) => ({
      label: c.label || c.name,
      value: c.name,
    }))
  }
  return []
})

const nestedOptions = computed(() => {
  const opt = option.value
  if (!opt) return []
  const currentVal = options.value[props.name]

  if (opt.type === "switch") {
    const activeCase = opt.cases.find((c) => c.name === currentVal)
    return activeCase?.option || []
  }

  if (opt.type === "select") {
    const activeCase = opt.cases.find((c) => c.name === currentVal)
    return activeCase?.option || []
  }

  return []
})

const handleAllowInput = (value: string, verify?: string, pattern_msg?: string) => {
  if (!verify || value === "") return true
  try {
    const isValid = new RegExp(verify).test(value)
    if (!isValid && pattern_msg) {
      message.error(pattern_msg)
    }
    return isValid
  } catch (e) {
    return true
  }
}
</script>
