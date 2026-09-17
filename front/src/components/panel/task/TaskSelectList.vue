<template>
  <NCard size="small" content-style="padding: 0">
    <NEl
      tag="div"
      class="rounded-lg overflow-hidden"
      :class="{ 'overflow-y-auto': maxHeight }"
      :style="maxHeight ? { maxHeight } : undefined"
    >
      <VueDraggable
        v-if="taskListData.length > 0"
        v-model="taskListData"
        :animation="150"
        :delay="120"
        :delay-on-touch-only="true"
        ghost-class="ghost"
      >
        <NEl
          tag="div"
          v-for="item in taskListData"
          :key="item.uid"
          class="task-row flex items-center gap-3 px-3 py-2.5 border-b border-solid last:border-b-0 cursor-pointer transition-colors"
          :style="{
            borderColor: 'var(--divider-color)',
            background:
              item.uid === selectedUid
                ? 'color-mix(in srgb, var(--primary-color) 14%, var(--card-color))'
                : 'var(--card-color)',
          }"
          @click="handleRowClick(item)"
        >
          <NIcon size="20" class="cursor-grab active:cursor-grabbing shrink-0">
            <ReorderThreeOutline />
          </NIcon>
          <span
            class="flex-1 text-base truncate select-none"
            :class="{ 'opacity-60': isIncompatible(item.id) }"
            >{{ resolveTaskLabel(item.id, item.name) }}</span
          >
          <NTooltip v-if="isIncompatible(item.id)">
            <template #trigger>
              <NIcon size="18" class="shrink-0 opacity-70">
                <WarningOutline />
              </NIcon>
            </template>
            {{ t("panel.taskQueue.incompatible") }}
          </NTooltip>
          <NButton
            quaternary
            circle
            size="tiny"
            class="shrink-0"
            @click.stop="emit('remove', item.uid)"
          >
            <template #icon>
              <NIcon><CloseOutline /></NIcon>
            </template>
          </NButton>
        </NEl>
      </VueDraggable>
      <NEl v-else tag="div" class="text-center text-sm opacity-50 py-6">
        {{ t("panel.taskQueue.empty") }}
      </NEl>
    </NEl>
  </NCard>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import { useI18n } from "vue-i18n"
import { CloseOutline, ReorderThreeOutline, WarningOutline } from "@vicons/ionicons5"
import { useInterfaceStore } from "@/stores"
import type { QueuedTaskItem } from "@/types/taskConfigModel"
import type { Task } from "@/types/interfaceModel"
import { resolveInterfaceText } from "@/utils/interface/content"

interface Props {
  tasks: QueuedTaskItem[]
  controllerName?: string | null
  resourceName?: string | null
  hideIncompatible?: boolean
  maxHeight?: string
  selectedUid?: string | null
}

interface Emits {
  (e: "update:tasks", value: QueuedTaskItem[]): void
  (e: "config", uid: string, name: string): void
  (e: "remove", uid: string): void
}

const {
  tasks,
  controllerName = null,
  resourceName = null,
  hideIncompatible = false,
  maxHeight = "",
  selectedUid = null,
} = defineProps<Props>()

const emit = defineEmits<Emits>()
const { locale, t } = useI18n()
const interfaceStore = useInterfaceStore()

function isIncompatible(taskId: string): boolean {
  return (
    hideIncompatible && !interfaceStore.isTaskCompatibleByName(taskId, controllerName, resourceName)
  )
}

const taskListData = computed({
  get: () => tasks,
  set: (value: QueuedTaskItem[]) => emit("update:tasks", value),
})

function resolveTaskLabel(taskId: string, fallback: string) {
  const task = interfaceStore.getTaskByName(taskId)
  return resolveInterfaceText(interfaceStore.interface, locale.value, task?.label, fallback)
}

function hasDocumentContent(task: Task): boolean {
  if (task.description) return true
  if (typeof task.desc === "string" && task.desc) return true
  if (Array.isArray(task.desc) && task.desc.length > 0) return true
  if (typeof task.doc === "string" && task.doc) return true
  if (Array.isArray(task.doc) && task.doc.length > 0) return true
  return false
}

function taskHasContent(task: Task | null): boolean {
  if (!task) return false
  const hasOptions = task.option && task.option.length > 0
  return hasOptions || hasDocumentContent(task)
}

function handleRowClick(item: QueuedTaskItem) {
  const task = interfaceStore.getTaskByName(item.id)
  if (taskHasContent(task)) {
    emit("config", item.uid, item.id)
  }
}
</script>

<style scoped>
.cursor-grab {
  cursor: grab;
}
.cursor-grab:active {
  cursor: grabbing;
}
</style>
