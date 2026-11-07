<template>
  <div class="tasks-view grid grid-cols-1 md:grid-cols-2 gap-4 max-w-7xl mx-auto">
    <!-- Left: Task list with start/stop -->
    <NCard
      :bordered="false"
      class="tasks-column"
      content-style="display: flex; flex-direction: column; min-height: 0; gap: 0.75rem"
      header-style="padding-bottom: 0.75rem"
    >
      <template #header>
        <div class="flex items-center gap-2 h-8">
          <h2 class="text-base font-semibold shrink-0 flex items-center gap-2">
            <NIcon size="22">
              <ListOutline />
            </NIcon>
            {{ t("panel.taskList") }}
          </h2>
          <NSelect
            v-if="interfaceStore.getPresetList.length > 0"
            :value="configStore.selectedPresetName"
            :options="presetOptions"
            size="small"
            class="ml-auto w-36 max-w-[40vw]"
            @update:value="handlePresetChange"
          />
          <NButton secondary size="small" @click="showAddTask = true">
            <template #icon>
              <NIcon><AddOutline /></NIcon>
            </template>
            {{ t("panel.addTask.button") }}
          </NButton>
        </div>
      </template>
      <PreTaskList
        v-model="configStore.preTasks"
        class="shrink-0"
        :controller-name="deviceStore.selectedControllerName"
        :resource-name="deviceStore.resource"
      />
      <TaskSelectList
        class="min-h-0"
        :tasks="configStore.taskList"
        :controller-name="deviceStore.selectedControllerName"
        :resource-name="deviceStore.resource"
        :hide-incompatible="true"
        :selected-uid="selectedTaskUid"
        @update:tasks="handleTasksUpdate"
        @config="handleConfigTask"
        @remove="handleRemoveTask"
      />
      <div class="mt-auto shrink-0 flex flex-col items-center gap-1">
        <div class="flex justify-center gap-2">
          <NButton
            type="primary"
            class="min-w-32"
            :disabled="indexStore.TaskRunning"
            @click="handleStart"
          >
            <template #icon>
              <NIcon><PlayOutline /></NIcon>
            </template>
            {{ t("panel.start") }}
          </NButton>
          <NButton
            type="warning"
            class="min-w-32"
            :disabled="!indexStore.TaskRunning"
            @click="handleStop"
          >
            <template #icon>
              <NIcon><StopOutline /></NIcon>
            </template>
            {{ t("panel.stop") }}
          </NButton>
        </div>
        <NButton quaternary size="small" type="warning" @click="handleResetPreset">
          <template #icon>
            <NIcon><RefreshOutline /></NIcon>
          </template>
          {{ t("panel.resetConfig") }}
        </NButton>
      </div>
    </NCard>

    <!-- Right: Task Options + Description (hidden on mobile, which uses the drawer) -->
    <NCard
      :bordered="false"
      class="tasks-column task-settings-card"
      content-style="display: flex; flex-direction: column; min-height: 0"
      header-style="padding-bottom: 0.75rem"
    >
      <template #header>
        <div class="flex items-center gap-2 h-8 min-w-0">
          <h2 class="text-base font-semibold shrink-0 flex items-center gap-2">
            <NIcon size="22">
              <OptionsOutline />
            </NIcon>
            {{ t("panel.taskSettings") }}
          </h2>
          <NTag v-if="selectedTaskLabel" type="primary" size="small" class="ml-auto min-w-0">
            <span class="block truncate">{{ selectedTaskLabel }}</span>
          </NTag>
        </div>
      </template>
      <PanelTaskColumn />
    </NCard>

    <!-- Mobile task settings drawer -->
    <TaskSettingsDrawer v-if="isMobile" />
  </div>

  <StartConflictDialog />
  <AddTaskDialog
    v-model:show="showAddTask"
    :controller-name="deviceStore.selectedControllerName"
    :resource-name="deviceStore.resource"
    @add="handleAddTask"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import {
  AddOutline,
  ListOutline,
  OptionsOutline,
  PlayOutline,
  RefreshOutline,
  StopOutline,
} from "@vicons/ionicons5"
import PanelTaskColumn from "@/components/panel/PanelTaskColumn.vue"
import AddTaskDialog from "@/components/panel/task/AddTaskDialog.vue"
import TaskSettingsDrawer from "@/components/panel/task/TaskSettingsDrawer.vue"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import StartConflictDialog from "@/components/tasks/StartConflictDialog.vue"
import { stopTask } from "@/services/api"
import {
  useIndexStore,
  useInterfaceStore,
  useTaskConfigStore,
  useDeviceConnectionStore,
} from "@/stores"
import { CUSTOM_PRESET_NAME, type QueuedTaskItem } from "@/types/taskConfigModel"
import { resolveInterfaceText } from "@/utils/interface/content"
import { useViewport } from "@/utils/viewport/useViewport"

const { t } = useI18n()
const router = useRouter()
const indexStore = useIndexStore()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const deviceStore = useDeviceConnectionStore()
const { isMobile } = useViewport()

const clickedTaskUid = ref<string | null>(null)
const selectedTaskUid = computed(() => {
  if (
    clickedTaskUid.value &&
    configStore.taskList.some((task) => task.uid === clickedTaskUid.value)
  ) {
    return clickedTaskUid.value
  }
  return configStore.taskList.find((task) => task.id === indexStore.SelectedTaskID)?.uid ?? null
})

const presetOptions = computed(() => [
  { label: t("panel.preset.custom"), value: CUSTOM_PRESET_NAME },
  ...interfaceStore.getPresetList.map((preset) => ({
    label: resolveInterfaceText(preset.label, preset.name),
    value: preset.name,
    disabled: !interfaceStore.isPresetCompatible(preset, deviceStore.selectedControllerName),
  })),
])

const selectedTaskLabel = computed(() => {
  const task = interfaceStore.getTaskByName(indexStore.SelectedTaskID)
  return task ? resolveInterfaceText(task.label, task.name) : ""
})

function handleTasksUpdate(tasks: QueuedTaskItem[]) {
  configStore.taskList = tasks
}

const showAddTask = ref(false)

function handleAddTask(name: string) {
  configStore.addTaskToQueue(name)
}

function handleRemoveTask(uid: string) {
  configStore.taskList = configStore.taskList.filter((task) => task.uid !== uid)
  if (clickedTaskUid.value === uid) {
    clickedTaskUid.value = null
  }
  if (configStore.taskList.length === 0) {
    // 队列为空时清空选中任务并关闭设置抽屉，避免对已删任务的选项
    // 进行静默丢弃的编辑（序列化只覆盖在队任务）
    indexStore.SelectTask("")
    indexStore.closeTaskSettingsDrawer()
  }
}

function handleConfigTask(uid: string, name: string) {
  clickedTaskUid.value = uid
  indexStore.SelectTask(name)
  if (isMobile.value) {
    indexStore.openTaskSettingsDrawer(name)
  }
}

function handlePresetChange(name: string) {
  if (!configStore.selectPreset(name)) return
  selectFirstTask()
}

async function handleResetPreset() {
  if (await deviceStore.resetCurrentPreset()) {
    selectFirstTask()
  }
}

// Queue items are rebuilt with new uids, so drop the stale click and follow the new head.
function selectFirstTask() {
  clickedTaskUid.value = null
  indexStore.SelectTask(configStore.taskList[0]?.id ?? "")
}

async function handleStart() {
  const success = await deviceStore.StartTask()
  if (success) {
    router.push({ name: "logs" })
  }
}

async function handleStop() {
  // Await stop API; leave TaskRunning true until SSE task.failed/completed clears it
  await stopTask()
}

onMounted(() => {
  deviceStore.init()
})

onUnmounted(() => {
  deviceStore.cleanup()
})
</script>

<style scoped>
/* Below md the settings live in TaskSettingsDrawer. A scoped rule is used
   because a utility class would race naive-ui's own `.n-card { display: flex }`. */
.task-settings-card {
  display: none;
}
/* From md up both columns share one viewport-fitted row: viewport minus the
   4rem navbar, the 2rem wrapper padding and main's bottom padding (6rem while
   the dock is shown below lg, 1rem above). Inner lists scroll instead of the page. */
@media (min-width: 768px) {
  .tasks-view {
    height: max(32rem, calc(100dvh - 12rem));
  }
  .tasks-column {
    min-height: 0;
  }
  .task-settings-card {
    display: flex;
  }
}
@media (min-width: 1024px) {
  .tasks-view {
    height: max(32rem, calc(100dvh - 7rem));
  }
}
</style>
