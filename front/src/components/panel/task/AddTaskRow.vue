<template>
  <NTooltip :disabled="compatible" placement="left">
    <template #trigger>
      <button
        type="button"
        class="flex w-full items-center gap-2 rounded-md border border-solid px-3 py-2 text-left text-sm transition-colors"
        :style="{ borderColor: 'var(--border-color)', background: 'var(--card-color)' }"
        :class="rowClass"
        :aria-disabled="!compatible"
        @click="handleClick"
      >
        <span class="flex-1 truncate">{{ label }}</span>
        <NIcon size="16" class="shrink-0 opacity-50"><AddOutline /></NIcon>
      </button>
    </template>
    {{ reason }}
  </NTooltip>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { AddOutline } from "@vicons/ionicons5"
import { useInterfaceStore } from "@/stores"
import type { Task } from "@/types/interfaceModel"
import { resolveInterfaceText } from "@/utils/interface/content"

interface Props {
  task: Task
  controllerName?: string | null
  resourceName?: string | null
}

interface Emits {
  (e: "add", name: string): void
}

const { task, controllerName = null, resourceName = null } = defineProps<Props>()
const emit = defineEmits<Emits>()

const { locale, t } = useI18n()
const interfaceStore = useInterfaceStore()

const compatible = computed(() =>
  interfaceStore.isTaskCompatible(task, controllerName, resourceName),
)

const label = computed(() =>
  resolveInterfaceText(interfaceStore.interface, locale.value, task.label, task.name),
)

const reason = computed(() => {
  if (compatible.value) return ""
  const controllerMiss = Boolean(
    controllerName && task.controller?.length && !task.controller.includes(controllerName),
  )
  const resourceMiss = Boolean(
    resourceName && task.resource?.length && !task.resource.includes(resourceName),
  )
  if (controllerMiss && resourceMiss) return t("panel.addTask.incompatibleBoth")
  if (controllerMiss) return t("panel.addTask.incompatibleController")
  return t("panel.addTask.incompatibleResource")
})

const rowClass = computed(() => {
  if (!compatible.value) return "cursor-not-allowed opacity-50"
  return "task-add-row-action cursor-pointer"
})

function handleClick() {
  if (!compatible.value) return
  emit("add", task.name)
}
</script>

<style scoped>
.task-add-row-action:hover {
  background-color: var(--hover-color);
}
</style>
