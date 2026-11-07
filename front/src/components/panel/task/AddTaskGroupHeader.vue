<template>
  <div class="flex min-w-0 items-center gap-2">
    <InterfaceIcon v-if="section.kind === 'declared'" :icon="section.group?.icon" class="h-5 w-5" />
    <div class="min-w-0">
      <div class="font-medium">{{ label }}</div>
      <div v-if="description" class="text-xs opacity-60">{{ description }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import type { TaskGroupSection } from "@/utils/task-config/order"
import { resolveInterfaceText } from "@/utils/interface/content"
import InterfaceIcon from "@/components/common/InterfaceIcon.vue"

const { section } = defineProps<{ section: TaskGroupSection }>()

const { t } = useI18n()

const label = computed(() => {
  if (section.kind === "ungrouped") return t("panel.addTask.ungrouped")
  if (section.kind === "adhoc") return section.key
  return resolveInterfaceText(section.group?.label, section.key)
})

const description = computed(() => {
  if (section.kind !== "declared" || !section.group?.description) return ""
  return resolveInterfaceText(section.group.description, section.group.description)
})
</script>
