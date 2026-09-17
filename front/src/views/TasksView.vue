<template>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-start max-w-7xl mx-auto">
    <!-- Left: Task list with start/stop -->
    <NCard
      ref="leftCard"
      :bordered="false"
      content-style="display: flex; flex-direction: column; padding-bottom: 0"
      header-style="padding-bottom: 0.5rem"
    >
      <template #header>
        <div class="flex items-center justify-between gap-2">
          <h2 class="text-base shrink-0 flex items-center gap-2">
            <NIcon size="24">
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
        ref="preTaskList"
        v-model="configStore.preTasks"
        class="mb-3"
        :controller-name="deviceStore.selectedControllerName"
        :resource-name="deviceStore.resource"
      />
      <TaskSelectList
        :tasks="configStore.taskList"
        :controller-name="deviceStore.selectedControllerName"
        :resource-name="deviceStore.resource"
        :hide-incompatible="true"
        :max-height="taskListMaxHeight"
        :selected-uid="selectedTaskUid"
        @update:tasks="handleTasksUpdate"
        @config="handleConfigTask"
        @remove="handleRemoveTask"
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
  <AddTaskDialog
    v-model:show="showAddTask"
    :controller-name="deviceStore.selectedControllerName"
    :resource-name="deviceStore.resource"
    @add="handleAddTask"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import { AddOutline, ListOutline, PlayOutline, StopOutline } from "@vicons/ionicons5"
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

const { t, locale } = useI18n()
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
    label: resolveInterfaceText(interfaceStore.interface, locale.value, preset.label, preset.name),
    value: preset.name,
  })),
])

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

function handleTasksUpdate(tasks: QueuedTaskItem[]) {
  configStore.taskList = tasks
}

const showAddTask = ref(false)

function handleAddTask(entry: string) {
  const task = interfaceStore.getTaskList.find((item) => item.id === entry)
  if (!task) return
  configStore.taskList = [
    ...configStore.taskList,
    { uid: crypto.randomUUID(), id: task.id, name: task.name, order: task.order },
  ]
}

function handleRemoveTask(uid: string) {
  configStore.taskList = configStore.taskList.filter((task) => task.uid !== uid)
}

function handleConfigTask(uid: string, entry: string) {
  clickedTaskUid.value = uid
  indexStore.SelectTask(entry)
  if (isMobile.value) {
    indexStore.openTaskSettingsDrawer(entry)
  }
}

function handlePresetChange(name: string) {
  if (!configStore.selectPreset(name)) return
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
