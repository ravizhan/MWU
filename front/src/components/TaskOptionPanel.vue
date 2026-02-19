<template>
  <div class="task-option-panel">
    <!-- 当前配置任务提示（可选显示） -->
    <div v-if="showHeader && currentTaskName" class="text-center mb-2">
      <n-tag type="info" size="large"> {{ headerLabel }}{{ currentTaskName }} </n-tag>
    </div>

    <!-- 选项列表 -->
    <n-scrollbar trigger="none" :class="scrollbarClass">
      <div v-if="!currentTaskId">
        <n-empty :description="emptyText" />
      </div>
      <div v-else>
        <n-list v-if="taskOptions.length > 0" hoverable>
          <OptionItem
            v-for="optName in taskOptions"
            :key="optName"
            :name="optName"
            :options="options"
          />
        </n-list>
        <n-empty v-else :description="noOptionsText" />
      </div>
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useInterfaceStore } from "../stores/interface"
import OptionItem from "./OptionItem.vue"

interface Props {
  /** 当前配置的任务ID */
  currentTaskId: string | null
  /** 选项数据 */
  options: Record<string, string>
  /** 是否显示头部 */
  showHeader?: boolean
  /** 头部标签前缀 */
  headerLabel?: string
  /** 空状态提示文本 */
  emptyText?: string
  /** 无选项提示文本 */
  noOptionsText?: string
  /** 滚动区域 class */
  scrollbarClass?: string
}

const props = withDefaults(defineProps<Props>(), {
  showHeader: false,
  headerLabel: "",
  emptyText: "",
  noOptionsText: "",
  scrollbarClass: "max-h-65 !rounded-[12px]",
})

const interfaceStore = useInterfaceStore()

// 获取当前任务名称
const currentTaskName = computed(() => {
  if (!props.currentTaskId) return ""
  const task = interfaceStore.getTaskList.find((t) => t.id === props.currentTaskId)
  return task?.name || ""
})

// 获取当前任务的选项列表
const taskOptions = computed(() => {
  if (!props.currentTaskId) return []
  const task = interfaceStore.interface?.task?.find((t) => t.entry === props.currentTaskId)
  return task?.option || []
})
</script>

<style scoped>
.task-option-panel {
  min-height: 50px;
}
</style>
