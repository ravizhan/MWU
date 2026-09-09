<template>
  <NAlert
    v-if="configStore.configLoadError"
    type="error"
    class="col-span-full mb-[-0.5rem]"
    :title="t('tasks.configError.title')"
  >
    {{ configStore.configLoadError.message }}{{ t("tasks.configError.hint") }}
  </NAlert>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-start max-w-7xl mx-auto">
    <!-- Left: Task list with start/stop -->
    <NCard
      ref="leftCard"
      :bordered="false"
      content-style="display: flex; flex-direction: column; padding-bottom: 0"
      header-style="padding-bottom: 0.5rem"
    >
      <template #header>
        <h2 class="text-base shrink-0 flex items-center gap-2">
          <NIcon size="24">
            <ListOutline />
          </NIcon>
          {{ t("panel.taskList") }}
        </h2>
      </template>
      <PreTaskList
        ref="preTaskList"
        v-model="configStore.preTasks"
        class="mb-3"
        :controller-name="deviceStore.selectedControllerName"
        :resource-name="deviceStore.resource"
      />
      <TaskSelectList
        :tasks="configStore.taskList"
        :selected-tasks="configStore.selectedTaskIds"
        :controller-name="deviceStore.selectedControllerName"
        :resource-name="deviceStore.resource"
        :hide-incompatible="true"
        :max-height="taskListMaxHeight"
        @update:tasks="handleTasksUpdate"
        @update:selected-tasks="handleSelectedTasksUpdate"
        @config="handleConfigTask"
      />
      <div class="flex justify-center gap-2 pt-4 shrink-0">
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
      <div class="text-center shrink-0 py-2">
        <NButton quaternary size="small" type="warning" @click="deviceStore.resetConfig()">
          {{ t("panel.resetConfig") }}
        </NButton>
      </div>
    </NCard>

    <!-- Right: Task Options + Description (desktop only) -->
    <NCard
      :bordered="false"
      class="task-settings-card"
      content-style="display: flex; flex-direction: column"
    >
      <PanelTaskColumn />
    </NCard>

    <!-- Mobile task settings drawer -->
    <TaskSettingsDrawer v-if="isMobile" />
  </div>

  <StartConflictDialog />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import { ListOutline, PlayOutline, StopOutline } from "@vicons/ionicons5"
import PanelTaskColumn from "@/components/panel/PanelTaskColumn.vue"
import TaskSettingsDrawer from "@/components/panel/task/TaskSettingsDrawer.vue"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import StartConflictDialog from "@/components/tasks/StartConflictDialog.vue"
import { stopTask } from "@/services/api"
import { useIndexStore, useTaskConfigStore, useDeviceConnectionStore } from "@/stores"
import type { TaskListItem } from "@/types/taskConfigModel"
import { useViewport } from "@/utils/viewport/useViewport"

const { t } = useI18n()
const router = useRouter()
const indexStore = useIndexStore()
const configStore = useTaskConfigStore()
const deviceStore = useDeviceConnectionStore()
const { isMobile } = useViewport()

/* Left column must fit under the sticky navbar without page overflow. The
   task list is the only flexible region, so its max-height = viewport minus
   navbar, main vertical padding, the card's fixed chrome (header/buttons/
   reset/padding) and the PreTaskList's current height. Expanding PreTaskList
   shrinks the list by the same amount; collapsing restores it. Desktop only. */
const leftCard = useTemplateRef("leftCard")
const preTaskList = useTemplateRef("preTaskList")
const preTaskHeight = ref(0)
const chromeHeight = ref(0)
const topOffset = ref(0)
const bottomReserve = ref(0)
const viewportHeight = ref(0)
let resizeObserver: ResizeObserver | null = null

const taskListMaxHeight = computed(() => {
  if (isMobile.value || viewportHeight.value === 0) {
    return ""
  }
  const available =
    viewportHeight.value -
    topOffset.value -
    bottomReserve.value -
    chromeHeight.value -
    preTaskHeight.value
  return `${Math.round(Math.max(160, available))}px`
})

function measureHeights() {
  const cardEl: HTMLElement | undefined = leftCard.value?.$el
  const preTaskEl: HTMLElement | undefined = preTaskList.value?.$el
  preTaskHeight.value = preTaskEl?.offsetHeight ?? 0
  if (cardEl) {
    // The scroll container is the single overflow-y-auto child (TaskSelectList).
    const listEl = cardEl.querySelector<HTMLElement>(".overflow-y-auto")
    // Card height = preTask + listScroll + chrome, so chrome is exact.
    chromeHeight.value = cardEl.offsetHeight - preTaskHeight.value - (listEl?.offsetHeight ?? 0)
    // Space the card top occupies from the viewport top (navbar + wrapper
    // top padding), and the bottom padding to preserve below the grid.
    topOffset.value = cardEl.getBoundingClientRect().top
  }
  bottomReserve.value = bottomPaddingOf("main") + bottomPaddingOf("main > div")
}

function bottomPaddingOf(selector: string): number {
  const el = document.querySelector(selector)
  return el ? parseFloat(getComputedStyle(el).paddingBottom) : 0
}

watch(isMobile, measureHeights)

function handleWindowResize() {
  viewportHeight.value = window.innerHeight
  measureHeights()
}

onMounted(() => {
  viewportHeight.value = window.innerHeight
  window.addEventListener("resize", handleWindowResize)
  const el = preTaskList.value?.$el
  if (el) {
    resizeObserver = new ResizeObserver(measureHeights)
    resizeObserver.observe(el)
  }
  measureHeights()
})

onUnmounted(() => {
  window.removeEventListener("resize", handleWindowResize)
  resizeObserver?.disconnect()
  resizeObserver = null
})

function handleTasksUpdate(tasks: TaskListItem[]) {
  configStore.taskList = tasks
}

function handleSelectedTasksUpdate(selectedIds: string[]) {
  configStore.taskList = configStore.taskList.map((task) => ({
    ...task,
    checked: selectedIds.includes(task.id),
  }))
}

function handleConfigTask(taskId: string) {
  indexStore.SelectTask(taskId)
  if (isMobile.value) {
    indexStore.openTaskSettingsDrawer(taskId)
  }
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
.task-settings-card {
  display: none;
}
@media (min-width: 1024px) {
  .task-settings-card {
    display: block;
    /* Vertically center within the grid row. The left card is capped to the
       viewport, so the row height tracks the visible area and the settings
       card stays centered regardless of its own height. */
    align-self: center;
  }
}
</style>
