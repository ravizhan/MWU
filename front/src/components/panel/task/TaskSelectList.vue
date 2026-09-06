<template>
  <NCard size="small" content-style="padding: 0">
    <template #header>
      <div class="flex items-center justify-between w-full">
        <span class="text-sm font-medium">{{ t("tasks.list") }}</span>
        <NRadioGroup
          v-if="hasGroups"
          size="small"
          :value="viewMode"
          @update:value="handleViewModeChange"
        >
          <NRadioButton value="group">{{ t("tasks.viewMode.group") }}</NRadioButton>
          <NRadioButton value="order">{{ t("tasks.viewMode.order") }}</NRadioButton>
        </NRadioGroup>
      </div>
    </template>
    <NEl
      tag="div"
      class="rounded-lg overflow-hidden"
      :class="{ 'overflow-y-auto': maxHeight }"
      :style="maxHeight ? { maxHeight } : undefined"
    >
      <!-- 分组视图：按 group 声明顺序折叠展示；未分组项在最后 -->
      <template v-if="viewMode === 'group' && hasGroups">
        <NEl
          v-for="group in groupedView"
          :key="group.key"
          tag="div"
          class="border-b border-solid last:border-b-0"
          :style="{ borderColor: 'var(--divider-color)' }"
        >
          <button
            type="button"
            class="group-header w-full flex items-center gap-2 px-3 py-2 text-left text-sm font-medium"
            :style="{ background: 'var(--card-color)' }"
            @click="toggleGroup(group.key)"
          >
            <NIcon
              size="16"
              class="transition-transform"
              :class="{ 'rotate-90': expandedGroups.has(group.key) }"
            >
              <CaretForwardOutline />
            </NIcon>
            <span class="flex-1 truncate">{{ group.label }}</span>
            <span class="text-xs opacity-60">{{ group.items.length }}</span>
          </button>
          <NEl v-show="expandedGroups.has(group.key)" tag="div">
            <div
              v-for="item in group.items"
              :key="item.id"
              class="task-row flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors"
              :style="{ background: 'var(--card-color)' }"
              @click="handleRowClick(item.id)"
            >
              <NCheckbox
                class="shrink-0"
                :checked="isTaskSelected(item.id)"
                size="large"
                @click.stop
                @update:checked="handleSelectedChange(item.id, $event)"
              />
              <span class="flex-1 text-base truncate select-none">{{
                resolveTaskLabel(item.id, item.name)
              }}</span>
              <NButton
                quaternary
                circle
                size="small"
                class="shrink-0"
                @click.stop="handleConfig(item.id)"
              >
                <template #icon>
                  <NIcon size="20"><SettingsOutline /></NIcon>
                </template>
              </NButton>
            </div>
          </NEl>
        </NEl>
      </template>

      <!-- 平面视图：可拖拽排序（仅修改 taskOrder） -->
      <VueDraggable
        v-else
        v-model="taskListData"
        :animation="150"
        :delay="120"
        :delay-on-touch-only="true"
        ghost-class="ghost"
      >
        <NEl
          tag="div"
          v-for="item in taskListData"
          :key="item.id"
          class="task-row flex items-center gap-3 px-3 py-2.5 border-b border-solid last:border-b-0 cursor-pointer transition-colors"
          :style="{ borderColor: 'var(--divider-color)', background: 'var(--card-color)' }"
          @click="handleRowClick(item.id)"
        >
          <NIcon size="20" class="cursor-grab active:cursor-grabbing shrink-0">
            <ReorderThreeOutline />
          </NIcon>
          <NCheckbox
            class="shrink-0"
            :checked="isTaskSelected(item.id)"
            size="large"
            @click.stop
            @update:checked="handleSelectedChange(item.id, $event)"
          />
          <span class="flex-1 text-base truncate select-none">{{
            resolveTaskLabel(item.id, item.name)
          }}</span>
          <NButton
            quaternary
            circle
            size="small"
            class="shrink-0"
            @click.stop="handleConfig(item.id)"
          >
            <template #icon>
              <NIcon size="20"><SettingsOutline /></NIcon>
            </template>
          </NButton>
        </NEl>
      </VueDraggable>
    </NEl>
  </NCard>
</template>

<script setup lang="ts">
import { computed, ref, watchEffect } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import { useI18n } from "vue-i18n"
import { CaretForwardOutline, ReorderThreeOutline, SettingsOutline } from "@vicons/ionicons5"
import { useInterfaceStore } from "@/stores"
import type { TaskListItem } from "@/types/taskConfigModel"
import type { Task } from "@/types/interfaceModel"
import { resolveInterfaceText } from "@/utils/interface/content"

interface Props {
  tasks: TaskListItem[]
  selectedTasks: string[]
  controllerName?: string | null
  resourceName?: string | null
  hideIncompatible?: boolean
  maxHeight?: string
}

interface Emits {
  (e: "update:selected-tasks", value: string[]): void
  (e: "update:tasks", value: TaskListItem[]): void
  (e: "config", taskId: string): void
}

const {
  tasks,
  selectedTasks,
  controllerName = null,
  resourceName = null,
  hideIncompatible = false,
  maxHeight = "",
} = defineProps<Props>()

const emit = defineEmits<Emits>()
const { t, locale } = useI18n()
const interfaceStore = useInterfaceStore()

function isTaskVisible(taskId: string): boolean {
  if (!hideIncompatible) {
    return true
  }
  return interfaceStore.isTaskCompatibleByName(taskId, controllerName, resourceName)
}

const visibleTasks = computed(() => tasks.filter((task) => isTaskVisible(task.id)))

// ---- 分组视图 ------------------------------------------------------------

interface GroupView {
  key: string
  label: string
  items: TaskListItem[]
}

const hasGroups = computed(() => (interfaceStore.interface?.group ?? []).length > 0)

const viewMode = ref<"group" | "order">("group")

// group 声明存在时默认分组视图；否则固定平面
watchEffect(() => {
  if (!hasGroups.value) {
    viewMode.value = "order"
  }
})

const expandedGroups = ref(new Set<string>())

const groupedView = computed<GroupView[]>(() => {
  const groups = interfaceStore.interface?.group ?? []
  const result: GroupView[] = []
  const assigned = new Set<string>()

  for (const group of groups) {
    const members: TaskListItem[] = []
    for (const task of visibleTasks.value) {
      const interfaceTask = interfaceStore.getTaskByName(task.id)
      if (interfaceTask?.group?.includes(group.name)) {
        members.push(task)
        assigned.add(task.id)
      }
    }
    // 空分组也保留声明位置（展示结构稳定性）
    result.push({
      key: group.name,
      label: resolveInterfaceText(interfaceStore.interface, locale.value, group.label, group.name),
      items: members,
    })
  }

  const ungrouped = visibleTasks.value.filter((task) => !assigned.has(task.id))
  if (ungrouped.length > 0) {
    result.push({
      key: "__ungrouped__",
      label: t("tasks.viewMode.ungrouped"),
      items: ungrouped,
    })
  }
  return result
})

// 初始展开状态由 default_expand 控制；未分组区始终展开
watchEffect(() => {
  if (viewMode.value !== "group" || !hasGroups.value) {
    return
  }
  const next = new Set<string>()
  for (const group of interfaceStore.interface?.group ?? []) {
    if (group.default_expand !== false) {
      next.add(group.name)
    }
  }
  next.add("__ungrouped__")
  expandedGroups.value = next
})

function toggleGroup(key: string): void {
  const next = new Set(expandedGroups.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedGroups.value = next
}

function handleViewModeChange(value: string | number | null): void {
  if (value === "group" || value === "order") {
    viewMode.value = value
  }
}

// ---- 平面视图（拖拽排序）--------------------------------------------------

const taskListData = computed({
  get: () => visibleTasks.value,
  set: (value: TaskListItem[]) => {
    if (!hideIncompatible) {
      emit("update:tasks", value)
      return
    }

    const visibleTaskIds = tasks.filter((task) => isTaskVisible(task.id)).map((task) => task.id)
    const visibleTaskIdSet = new Set(visibleTaskIds)

    const reorderedVisibleTaskIds = value.map((task) => task.id)
    const reorderedVisibleTaskIdSet = new Set(reorderedVisibleTaskIds)
    const taskById = new Map(tasks.map((task) => [task.id, task]))

    const orderedVisibleTasks: TaskListItem[] = []
    for (const taskId of reorderedVisibleTaskIds) {
      if (!visibleTaskIdSet.has(taskId)) {
        continue
      }
      const task = taskById.get(taskId)
      if (task) {
        orderedVisibleTasks.push(task)
      }
    }

    for (const taskId of visibleTaskIds) {
      if (reorderedVisibleTaskIdSet.has(taskId)) {
        continue
      }
      const task = taskById.get(taskId)
      if (task) {
        orderedVisibleTasks.push(task)
      }
    }

    let visibleCursor = 0
    const mergedTasks = tasks.map((task) => {
      if (!visibleTaskIdSet.has(task.id)) {
        return task
      }
      const visibleTask = orderedVisibleTasks[visibleCursor]
      visibleCursor += 1
      return visibleTask || task
    })

    emit("update:tasks", mergedTasks)
  },
})

function resolveTaskLabel(taskId: string, fallback: string) {
  const task = interfaceStore.getTaskByName(taskId)
  return resolveInterfaceText(interfaceStore.interface, locale.value, task?.label, fallback)
}

function isTaskSelected(taskId: string): boolean {
  return selectedTasks.includes(taskId)
}

function handleSelectedChange(taskId: string, checked: boolean) {
  if (checked) {
    emit("update:selected-tasks", [...selectedTasks, taskId])
    return
  }
  emit(
    "update:selected-tasks",
    selectedTasks.filter((id) => id !== taskId),
  )
}

function handleConfig(taskId: string) {
  emit("config", taskId)
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

function handleRowClick(taskId: string) {
  if (isTaskSelected(taskId)) {
    handleSelectedChange(taskId, false)
    return
  }
  handleSelectedChange(taskId, true)
  const task = interfaceStore.getTaskByName(taskId)
  if (taskHasContent(task)) {
    emit("config", taskId)
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
.group-header {
  cursor: pointer;
}
.group-header:hover {
  background: var(--hover-color);
}
</style>
