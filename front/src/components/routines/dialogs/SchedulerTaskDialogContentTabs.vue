<template>
  <NTabs
    v-model:value="activeTab"
    type="segment"
    size="small"
    class="w-full flex-nowrap overflow-x-auto"
  >
    <NTabPane name="pre-tasks">
      <template #tab>
        <span class="flex items-center gap-1.5 whitespace-nowrap">
          <NIcon size="16"><TerminalOutline /></NIcon>
          {{ t("settings.scheduler.dialog.tab.preTasks") }}
        </span>
      </template>
      <PreTaskList
        v-model="preTasks"
        class="min-h-48"
        embedded
        :controller-name="controllerName"
        :resource-name="resourceName"
      />
    </NTabPane>
    <NTabPane name="task-list">
      <template #tab>
        <span class="flex items-center gap-1.5 whitespace-nowrap">
          <NIcon size="16"><ListOutline /></NIcon>
          {{ t("settings.scheduler.dialog.tab.taskList") }}
        </span>
      </template>
      <div class="mb-2 flex justify-end">
        <NButton secondary size="small" @click="showAddTask = true">
          <template #icon>
            <NIcon><AddOutline /></NIcon>
          </template>
          {{ t("panel.addTask.button") }}
        </NButton>
      </div>
      <TaskSelectList
        class="min-h-48"
        :tasks="taskListData"
        :controller-name="controllerName"
        :resource-name="resourceName"
        :hide-incompatible="true"
        max-height="20rem"
        :selected-uid="selectedUid"
        @update:tasks="emit('update:tasks', $event)"
        @config="handleConfig"
        @remove="emit('remove', $event)"
      />
      <AddTaskDialog
        v-model:show="showAddTask"
        :controller-name="controllerName"
        :resource-name="resourceName"
        @add="emit('add', $event)"
      />
    </NTabPane>
    <NTabPane name="task-settings">
      <template #tab>
        <span class="flex items-center gap-1.5 whitespace-nowrap">
          <NIcon size="16"><OptionsOutline /></NIcon>
          {{ t("settings.scheduler.dialog.tab.taskSettings") }}
        </span>
      </template>
      <TaskOptionPanel
        class="min-h-48"
        :current-task-id="currentSettingTaskId"
        :options="taskOptions"
        :show-header="true"
        :header-label="t('settings.scheduler.dialog.currentSetting')"
        :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
        :no-options-text="t('settings.scheduler.dialog.noOptions')"
      />
    </NTabPane>
  </NTabs>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"
import { AddOutline, ListOutline, OptionsOutline, TerminalOutline } from "@vicons/ionicons5"
import AddTaskDialog from "@/components/panel/task/AddTaskDialog.vue"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import type { PreTaskCommand, QueuedTaskItem } from "@/types/taskConfigModel"
import type { TaskOptionsByTask } from "@/types/schedulerModel"

type ActiveTab = "task-list" | "task-settings" | "pre-tasks"

interface Props {
  taskListData: QueuedTaskItem[]
  selectedUid?: string | null
  controllerName?: string | null
  resourceName?: string | null
  taskOptions: TaskOptionsByTask
  currentSettingTaskId: string | null
}

const {
  taskListData,
  selectedUid = null,
  controllerName,
  resourceName,
  taskOptions,
  currentSettingTaskId,
} = defineProps<Props>()

const activeTab = defineModel<ActiveTab>("activeTab", { required: true })
const preTasks = defineModel<PreTaskCommand[]>("preTasks", { required: true })

const emit = defineEmits<{
  (e: "update:tasks", value: QueuedTaskItem[]): void
  (e: "config", uid: string, name: string): void
  (e: "remove", uid: string): void
  (e: "add", name: string): void
}>()

const { t } = useI18n()
const showAddTask = ref(false)

function handleConfig(uid: string, name: string) {
  emit("config", uid, name)
}
</script>
