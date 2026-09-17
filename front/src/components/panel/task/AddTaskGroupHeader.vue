<template>
  <div class="flex min-w-0 items-center gap-2">
    <img v-if="icon" :src="icon" alt="" class="h-5 w-5 shrink-0 object-contain" />
    <div class="min-w-0">
      <div class="font-medium">{{ label }}</div>
      <div v-if="description" class="text-xs opacity-60">{{ description }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "@/stores"
import type { TaskGroupSection } from "@/utils/task-config/order"
import { resolveInterfaceAssetUrl, resolveInterfaceText } from "@/utils/interface/content"

const { section } = defineProps<{ section: TaskGroupSection }>()

const { locale, t } = useI18n()
const interfaceStore = useInterfaceStore()

const label = computed(() => {
  if (section.kind === "ungrouped") return t("panel.addTask.ungrouped")
  if (section.kind === "adhoc") return section.key
  return resolveInterfaceText(
    interfaceStore.interface,
    locale.value,
    section.group?.label,
    section.key,
  )
})

const description = computed(() => {
  if (section.kind !== "declared" || !section.group?.description) return ""
  return resolveInterfaceText(
    interfaceStore.interface,
    locale.value,
    section.group.description,
    section.group.description,
  )
})

const icon = computed(() => {
  if (section.kind !== "declared") return undefined
  return resolveInterfaceAssetUrl(interfaceStore.interface, locale.value, section.group?.icon)
})
</script>
