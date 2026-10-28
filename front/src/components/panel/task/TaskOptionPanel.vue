<template>
  <NCard :bordered="false" content-style="padding: 0.5rem">
    <div v-if="showHeader && currentTaskName" class="text-center mb-2">
      <NTag type="primary" size="large">{{ headerLabel }}{{ currentTaskName }}</NTag>
    </div>

    <div :class="scrollbarClass">
      <div v-if="!currentTaskId" class="text-center py-8 opacity-50">
        <NIcon size="30" class="mx-auto mb-2"><SettingsOutline /></NIcon>
        <p>{{ emptyText }}</p>
      </div>
      <NEl v-else-if="taskOptions.length > 0" tag="div" class="rounded-lg overflow-hidden">
        <OptionItem
          v-for="optName in taskOptions"
          :key="optName"
          :name="optName"
          :task-options="currentTaskOptions"
        />
      </NEl>
      <div v-else class="text-center py-8 opacity-50">
        <NIcon size="30" class="mx-auto mb-2"><FileTrayOutline /></NIcon>
        <p>{{ noOptionsText }}</p>
      </div>
    </div>
  </NCard>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { FileTrayOutline, SettingsOutline } from "@vicons/ionicons5"
import { useInterfaceStore } from "@/stores"
import type { TaskOptionsByTask } from "@/types/schedulerModel"
import OptionItem from "@/components/panel/task/OptionItem.vue"
import { resolveInterfaceText } from "@/utils/interface/content"

interface Props {
  currentTaskId: string | null
  options: TaskOptionsByTask
  showHeader?: boolean
  headerLabel?: string
  emptyText?: string
  noOptionsText?: string
  scrollbarClass?: string
}

const {
  currentTaskId,
  options,
  showHeader = false,
  headerLabel = "",
  emptyText = "",
  noOptionsText = "",
  scrollbarClass = "max-h-65 overflow-y-auto rounded-xl",
} = defineProps<Props>()

const interfaceStore = useInterfaceStore()

const currentTaskName = computed(() => {
  if (!currentTaskId) return ""
  const task = interfaceStore.getTaskByName(currentTaskId)
  return resolveInterfaceText(task?.label, task?.name || "")
})

const currentTaskOptions = computed(() => {
  if (!currentTaskId) {
    return {}
  }
  return options[currentTaskId] ?? {}
})

const taskOptions = computed(() => {
  if (!currentTaskId) return []
  const task = interfaceStore.getTaskByName(currentTaskId)
  return task?.option || []
})
</script>
