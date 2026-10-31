<template>
  <div class="flex flex-wrap gap-3">
    <NCheckbox
      v-for="checkbox in option.cases"
      :key="checkbox.name"
      :checked="normalizedValue.includes(checkbox.name)"
      :disabled="isLocked(checkbox.name)"
      @update:checked="handleCheckboxChange(checkbox.name, $event)"
    >
      {{ resolveCaseLabel(checkbox.label, checkbox.name) }}
    </NCheckbox>
    <NText
      v-if="minCount > 0 || maxCount !== undefined"
      :type="selectedCount < minCount ? 'error' : undefined"
      :depth="selectedCount < minCount ? undefined : 3"
      class="w-full text-xs"
    >
      {{
        t("option.checkboxCount", {
          count: selectedCount,
          min: minCount,
          max: maxCount ?? option.cases.length,
        })
      }}
    </NText>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import type { CheckboxOption } from "@/types/interfaceModel"
import { resolveInterfaceText } from "@/utils/interface/content"

const { t } = useI18n()

const { option, value } = defineProps<{
  option: CheckboxOption
  value: string[]
}>()

const emit = defineEmits<{
  (event: "update:value", value: string[]): void
}>()

const normalizedValue = computed(() => {
  const selected = new Set(value)
  return option.cases.map((item) => item.name).filter((name) => selected.has(name))
})

const selectedCount = computed(() => normalizedValue.value.length)
const minCount = computed(() => option.min_count ?? 0)
// /api/interface 把未设置的上限序列化为 null，统一视为无上限
const maxCount = computed(() => option.max_count ?? undefined)

function resolveCaseLabel(label: string | undefined, fallback: string): string {
  return resolveInterfaceText(label, fallback)
}

// 只拦截超出上限；低于下限允许暂存（如上下限相等时先取消再勾选），启动前由后端校验
function isLocked(checkboxName: string): boolean {
  if (normalizedValue.value.includes(checkboxName)) {
    return false
  }
  return maxCount.value !== undefined && selectedCount.value >= maxCount.value
}

function handleCheckboxChange(checkboxName: string, checked: boolean): void {
  if (isLocked(checkboxName)) {
    return
  }

  const selected = new Set(normalizedValue.value)
  if (checked) {
    selected.add(checkboxName)
  }
  if (!checked) {
    selected.delete(checkboxName)
  }
  emit(
    "update:value",
    option.cases.map((item) => item.name).filter((name) => selected.has(name)),
  )
}
</script>
