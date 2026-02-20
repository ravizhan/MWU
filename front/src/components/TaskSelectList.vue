<template>
  <n-list hoverable bordered>
    <template v-if="scrollable">
      <n-scrollbar trigger="none" class="max-h-75">
        <VueDraggable v-model="taskListData" :animation="150" ghost-class="ghost">
          <n-list-item
            v-for="item in taskListData"
            :key="item.id"
            class="cursor-grab active:cursor-grabbing"
          >
            <n-checkbox
              size="large"
              :label="item.name"
              :checked="isTaskSelected(item.id)"
              @update:checked="(v: boolean) => handleToggle(item.id, v)"
            />
            <template #suffix>
              <n-button quaternary circle @click="handleConfig(item.id)">
                <template #icon>
                  <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
                </template>
              </n-button>
            </template>
          </n-list-item>
        </VueDraggable>
      </n-scrollbar>
    </template>
    <template v-else>
      <VueDraggable v-model="taskListData" :animation="150" ghost-class="ghost">
        <n-list-item
          v-for="item in taskListData"
          :key="item.id"
          class="cursor-grab active:cursor-grabbing"
        >
          <n-checkbox
            size="large"
            :label="item.name"
            :checked="isTaskSelected(item.id)"
            @update:checked="(v: boolean) => handleToggle(item.id, v)"
          />
          <template #suffix>
            <n-button quaternary circle @click="handleConfig(item.id)">
              <template #icon>
                <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
              </template>
            </n-button>
          </template>
        </n-list-item>
      </VueDraggable>
    </template>
  </n-list>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import type { TaskListItem } from "../stores/interface"

interface Props {
  /** 所有可用任务 */
  tasks: TaskListItem[]
  /** 选中的任务ID列表 */
  selectedTasks: string[]
  /** 是否显示滚动条 */
  scrollable?: boolean
}

interface Emits {
  (e: "update:selectedTasks", value: string[]): void
  (e: "update:tasks", value: TaskListItem[]): void
  (e: "config", taskId: string): void
}

const props = withDefaults(defineProps<Props>(), {
  scrollable: false,
})

const emit = defineEmits<Emits>()

// 本地任务列表数据（用于拖拽）
const taskListData = computed({
  get: () => props.tasks,
  set: (value: TaskListItem[]) => emit("update:tasks", value),
})

// 判断任务是否选中
function isTaskSelected(taskId: string): boolean {
  return props.selectedTasks.includes(taskId)
}

// 切换任务选中状态
function handleToggle(taskId: string, checked: boolean) {
  let newSelected: string[]
  if (checked) {
    newSelected = [...props.selectedTasks, taskId]
  } else {
    newSelected = props.selectedTasks.filter((id) => id !== taskId)
  }
  emit("update:selectedTasks", newSelected)
}

// 打开任务配置
function handleConfig(taskId: string) {
  emit("config", taskId)
}
</script>

<style scoped>
.cursor-grab {
  cursor: grab;
}

.cursor-grab:active {
  cursor: grabbing;
}

.ghost {
  opacity: 0.5;
  background: #c8ebfb;
}
</style>
