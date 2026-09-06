<template>
  <NModal
    v-model:show="showDialog"
    preset="card"
    :closable="false"
    :mask-closable="true"
    :style="dialogBoxStyle"
    content-style="padding: 0"
  >
    <div class="flex h-[min(92dvh,540px)] w-full flex-col sm:h-[min(90dvh,540px)] sm:max-h-none">
      <!-- Header -->
      <header class="flex shrink-0 items-center justify-between gap-3 px-4 py-3 sm:px-5">
        <div class="flex min-w-0 items-center gap-2">
          <NIcon size="20" class="shrink-0 text-(--primary-color)">
            <CalendarOutline />
          </NIcon>
          <h3 class="truncate text-base font-semibold sm:text-lg">
            {{
              isEditMode
                ? t("settings.scheduler.dialog.editTitle")
                : t("settings.scheduler.dialog.createTitle")
            }}
          </h3>
        </div>
        <NButton
          quaternary
          circle
          size="small"
          class="shrink-0"
          :title="t('common.cancel')"
          :aria-label="t('common.cancel')"
          @click="handleCancel"
        >
          <template #icon>
            <NIcon size="18"><CloseOutline /></NIcon>
          </template>
        </NButton>
      </header>

      <!-- Body: section nav + scrollable content -->
      <div class="flex min-h-0 flex-1 flex-col md:flex-row">
        <!-- Section navigation -->
        <SchedulerTaskDialogSectionNav
          v-model:active-section="activeSection"
          :sections="sections"
        />

        <!-- Scrollable content -->
        <div
          class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5"
        >
          <!-- Basic info -->
          <div v-if="activeSection === 'basic'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><TextOutline /></NIcon>
              {{ t("settings.scheduler.dialog.taskName") }}
            </label>
            <NInput
              v-model:value="formData.name"
              size="medium"
              class="w-full"
              :placeholder="t('settings.scheduler.dialog.taskNamePlaceholder')"
              :input-props="{ autocomplete: 'off' }"
            />
          </div>

          <div v-if="activeSection === 'basic'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><TextOutline /></NIcon>
              {{ t("settings.scheduler.dialog.taskDesc") }}
            </label>
            <NInput
              v-model:value="formData.description"
              type="textarea"
              size="medium"
              class="w-full"
              :placeholder="t('settings.scheduler.dialog.taskDescPlaceholder')"
              :autosize="{ minRows: 3, maxRows: 5 }"
            />
          </div>

          <!-- Schedule: trigger type -->
          <SchedulerTaskDialogTriggerType
            v-if="activeSection === 'schedule'"
            :trigger-type="triggerType"
            :trigger-options="triggerOptions"
            @update:trigger-type="handleTriggerTypeChange"
          />

          <!-- Schedule: cron -->
          <div v-if="activeSection === 'schedule' && triggerType === 'cron'" class="space-y-1.5">
            <label class="text-sm font-medium">
              {{ t("settings.scheduler.dialog.cronExpression") }}
            </label>
            <NInput
              :value="cronConfig.cron"
              size="medium"
              class="w-full font-mono text-sm"
              :placeholder="t('settings.scheduler.dialog.cronPlaceholder')"
              :input-props="{ spellcheck: false }"
              @update:value="updateTriggerConfig({ cron: $event })"
            />
          </div>
          <div
            v-if="activeSection === 'schedule' && triggerType === 'cron'"
            class="flex flex-wrap gap-2"
          >
            <span class="self-center text-xs text-(--text-color-3)">
              {{ t("settings.scheduler.dialog.quickSelect") }}
            </span>
            <NButton size="tiny" secondary @click="setCronPreset('daily')">
              {{ t("settings.scheduler.dialog.presets.daily") }}
            </NButton>
            <NButton size="tiny" secondary @click="setCronPreset('daily9am')">
              {{ t("settings.scheduler.dialog.presets.daily9am") }}
            </NButton>
            <NButton size="tiny" secondary @click="setCronPreset('weekly')">
              {{ t("settings.scheduler.dialog.presets.weekly") }}
            </NButton>
            <NButton size="tiny" secondary @click="setCronPreset('hourly')">
              {{ t("settings.scheduler.dialog.presets.hourly") }}
            </NButton>
          </div>

          <!-- Schedule: wakeup -->
          <div v-if="activeSection === 'schedule' && triggerType === 'cron'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><MoonOutline /></NIcon>
              {{ t("settings.scheduler.dialog.runWhenClosed") }}
              <NSwitch v-model:value="wakeupEnabled" :disabled="!isCronNativeEligible" />
            </label>
            <div class="flex flex-wrap items-center">
              <span v-if="!isCronNativeEligible" class="text-xs text-(--warning-color)">
                {{ t("settings.scheduler.dialog.runWhenClosedIneligible") }}
              </span>
            </div>
          </div>

          <!-- Schedule: date -->
          <div v-if="activeSection === 'schedule' && triggerType === 'date'" class="space-y-1.5">
            <label class="text-sm font-medium">
              {{ t("settings.scheduler.dialog.executionTime") }}
            </label>
            <NInput
              :value="dateConfigLocal"
              size="medium"
              class="w-full max-w-xs"
              :input-props="{ type: 'datetime-local' }"
              @update:value="updateTriggerConfig({ run_date: toIsoOrEmpty($event) })"
            />
          </div>

          <!-- Schedule: interval duration -->
          <div
            v-if="activeSection === 'schedule' && triggerType === 'interval'"
            class="space-y-1.5"
          >
            <label class="text-sm font-medium">
              {{ t("settings.scheduler.dialog.intervalTime") }}
            </label>
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.week") }}</span>
                <NInputNumber
                  :value="intervalConfig.weeks ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ weeks: $event ?? 0 })"
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.day") }}</span>
                <NInputNumber
                  :value="intervalConfig.days ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ days: $event ?? 0 })"
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{ t("settings.scheduler.formatter.hour") }}</span>
                <NInputNumber
                  :value="intervalConfig.hours ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ hours: $event ?? 0 })"
                />
              </label>
              <label class="flex flex-col gap-1">
                <span class="text-xs opacity-60">{{
                  t("settings.scheduler.formatter.minute")
                }}</span>
                <NInputNumber
                  :value="intervalConfig.minutes ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ minutes: $event ?? 0 })"
                />
              </label>
              <label class="col-span-2 flex flex-col gap-1 sm:col-span-1">
                <span class="text-xs opacity-60">{{
                  t("settings.scheduler.formatter.second")
                }}</span>
                <NInputNumber
                  :value="intervalConfig.seconds ?? 0"
                  :min="0"
                  size="medium"
                  class="w-full"
                  @update:value="updateTriggerConfig({ seconds: $event ?? 0 })"
                />
              </label>
            </div>
          </div>

          <!-- Schedule: interval start/end -->
          <div
            v-if="activeSection === 'schedule' && triggerType === 'interval'"
            class="grid grid-cols-1 gap-3 sm:grid-cols-2"
          >
            <div class="space-y-1.5">
              <label class="text-sm font-medium">
                {{ t("settings.scheduler.dialog.startTime") }}
              </label>
              <NInput
                :value="intervalStartLocal"
                size="medium"
                class="w-full"
                :input-props="{ type: 'datetime-local' }"
                @update:value="
                  updateTriggerConfig({
                    start_date: toIsoOrEmpty($event) || undefined,
                  })
                "
              />
            </div>
            <div class="space-y-1.5">
              <label class="text-sm font-medium">
                {{ t("settings.scheduler.dialog.endTime") }}
              </label>
              <NInput
                :value="intervalEndLocal"
                size="medium"
                class="w-full"
                :input-props="{ type: 'datetime-local' }"
                @update:value="
                  updateTriggerConfig({
                    end_date: toIsoOrEmpty($event) || undefined,
                  })
                "
              />
            </div>
          </div>

          <!-- Environment -->
          <div v-if="activeSection === 'environment'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><GameControllerOutline /></NIcon>
              {{ t("settings.scheduler.dialog.controller") }}
            </label>
            <NSelect
              v-model:value="formData.controller_name"
              :options="deviceControllerOptions"
              :placeholder="t('panel.selectDeviceType')"
              :disabled="loadingDevices"
              size="medium"
              class="w-full"
            />
          </div>

          <div v-if="activeSection === 'environment'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><PhonePortraitOutline /></NIcon>
              {{ t("settings.scheduler.dialog.deviceAddress") }}
            </label>
            <NInput
              v-if="isPlayCover"
              v-model:value="selectedDeviceAddress"
              size="medium"
              class="w-full"
              :placeholder="t('panel.playcoverAddress')"
              :disabled="!formData.controller_name"
            />
            <NSelect
              v-else
              filterable
              tag
              :value="selectedDeviceAddress"
              :options="deviceAddressOptions"
              :placeholder="t('panel.selectDevice')"
              :disabled="!formData.controller_name || loadingDevices"
              size="medium"
              class="w-full"
              :on-create="(label: string) => ({ label, value: label })"
              @update:value="handleDeviceAddressUpdate"
            />
          </div>

          <div v-if="activeSection === 'environment'" class="space-y-1.5">
            <label class="flex items-center gap-1.5 text-sm font-medium">
              <NIcon size="16" class="opacity-70"><FolderOpenOutline /></NIcon>
              {{ t("settings.scheduler.dialog.resource") }}
            </label>
            <NSelect
              v-model:value="formData.resource_name"
              :options="resourceOptions"
              :placeholder="t('panel.selectResource')"
              :disabled="!formData.controller_name || loadingResources"
              size="medium"
              class="w-full"
            />
          </div>

          <!-- Content: tasks -->
          <SchedulerTaskDialogContentTabs
            v-if="activeSection === 'content'"
            v-model:active-tab="activeTab"
            v-model:pre-tasks="formData.preTasks"
            :task-list-data="taskListData"
            :selected-tasks="formData.task_list"
            :controller-name="formData.controller_name"
            :resource-name="formData.resource_name"
            :task-options="formData.task_options"
            :current-setting-task-id="currentSettingTaskId"
            @update:tasks="handleTasksUpdate"
            @update:selected-tasks="handleSelectedTasksUpdate"
            @config="openTaskSettings"
          />
        </div>
      </div>

      <!-- Footer -->
      <footer class="flex shrink-0 items-center justify-end px-4 py-3 sm:px-5">
        <NSpace justify="end">
          <NButton quaternary @click="handleCancel">
            {{ t("common.cancel") }}
          </NButton>
          <NButton type="primary" :loading="loading" :disabled="loading" @click="handleSave">
            {{ t("common.save") }}
          </NButton>
        </NSpace>
      </footer>
    </div>
  </NModal>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, toRef, watch } from "vue"
import { useI18n } from "vue-i18n"
import {
  CalendarNumberOutline,
  CalendarOutline,
  CloseOutline,
  CodeSlashOutline,
  FolderOpenOutline,
  GameControllerOutline,
  HardwareChipOutline,
  InformationCircleOutline,
  ListOutline,
  MoonOutline,
  PhonePortraitOutline,
  TextOutline,
  TimeOutline,
  TimerOutline,
} from "@vicons/ionicons5"
import { useInterfaceStore, useTaskConfigStore } from "@/stores"
import type { TaskListItem } from "@/types/taskConfigModel"
import SchedulerTaskDialogContentTabs from "./SchedulerTaskDialogContentTabs.vue"
import SchedulerTaskDialogSectionNav from "./SchedulerTaskDialogSectionNav.vue"
import SchedulerTaskDialogTriggerType from "./SchedulerTaskDialogTriggerType.vue"
import { toIsoOrEmpty, toDatetimeLocalValue } from "@/utils/datetime"
import { showGlobalMessage } from "@/services/feedback/message"
import { useViewport } from "@/utils/viewport/useViewport"
import type { ScheduledTask } from "@/types/schedulerModel"
import { useSchedulerTaskForm } from "./composables/useSchedulerTaskForm"
import { useTaskEnvironment } from "./composables/useTaskEnvironment"
import {
  useSchedulerTaskSave,
  type DialogSection,
  type ContentTab,
} from "./composables/useSchedulerTaskSave"

interface Props {
  show: boolean
  task?: ScheduledTask | null
}

interface Emits {
  (e: "update:show", value: boolean): void
  (e: "saved"): void
}

const { show, task } = defineProps<Props>()
const emit = defineEmits<Emits>()

const taskRef = toRef(() => task)

const { t } = useI18n()
const configStore = useTaskConfigStore()
const interfaceStore = useInterfaceStore()

const { isMobile, width: viewportWidth } = useViewport()

/** Keep the card within the viewport while retaining the desktop content-driven width. */
const dialogBoxStyle = computed(() => {
  if (isMobile.value) {
    return { width: "calc(100vw - 32px)", maxWidth: "calc(100vw - 32px)" }
  }
  const w = Math.min(Math.round(viewportWidth.value * 0.72), 960)
  return { width: `${w}px`, maxWidth: "none" }
})

const activeSection = ref<DialogSection>("basic")
const activeTab = ref<ContentTab>("task-list")
const currentSettingTaskId = ref<string | null>(null)
const suppressFormInit = ref(false)

const {
  formData,
  wakeupEnabled,
  triggerType,
  isCronNativeEligible,
  cronConfig,
  dateConfig,
  intervalConfig,
  initFormData,
  setTriggerType,
  updateTriggerConfig,
  setCronPreset,
} = useSchedulerTaskForm()

const {
  loadingDevices,
  loadingResources,
  isPlayCover,
  deviceControllerOptions,
  deviceAddressOptions,
  resourceOptions,
  selectedDeviceAddress,
  handleDeviceAddressUpdate,
} = useTaskEnvironment(formData, suppressFormInit)

const showDialog = computed({
  get: () => show,
  set: (value) => emit("update:show", value),
})

const isEditMode = computed(() => !!task)
const availableTasks = computed(() => configStore.taskList)

const dateConfigLocal = computed(() => toDatetimeLocalValue(dateConfig.value.run_date))
const intervalStartLocal = computed(() => toDatetimeLocalValue(intervalConfig.value.start_date))
const intervalEndLocal = computed(() => toDatetimeLocalValue(intervalConfig.value.end_date))

const taskListData = ref<TaskListItem[]>([])

const sections = computed(() => [
  {
    id: "basic" as const,
    label: t("settings.scheduler.dialog.sections.basic"),
    icon: InformationCircleOutline,
  },
  {
    id: "schedule" as const,
    label: t("settings.scheduler.dialog.sections.schedule"),
    icon: TimeOutline,
  },
  {
    id: "environment" as const,
    label: t("settings.scheduler.dialog.sections.environment"),
    icon: HardwareChipOutline,
  },
  {
    id: "content" as const,
    label: t("settings.scheduler.dialog.sections.content"),
    icon: ListOutline,
  },
])

const triggerOptions = computed(() => [
  {
    value: "cron" as const,
    label: t("settings.scheduler.dialog.cronExpression"),
    icon: CodeSlashOutline,
  },
  {
    value: "date" as const,
    label: t("settings.scheduler.dialog.specificTime"),
    icon: CalendarNumberOutline,
  },
  {
    value: "interval" as const,
    label: t("settings.scheduler.dialog.intervalExecution"),
    icon: TimerOutline,
  },
])

function syncTaskListData(preferredOrder: string[]) {
  const allTasks = availableTasks.value
  const taskMap = new Map(allTasks.map((task) => [task.id, task]))
  const orderedTasks: TaskListItem[] = []

  for (const taskId of preferredOrder) {
    const task = taskMap.get(taskId)
    if (task) {
      orderedTasks.push(task)
      taskMap.delete(taskId)
    }
  }

  for (const task of allTasks) {
    if (taskMap.has(task.id)) {
      orderedTasks.push(task)
    }
  }

  taskListData.value = orderedTasks
}

function buildOrderedTaskList(selectedTasks: string[], tasks: TaskListItem[] = taskListData.value) {
  const selectedSet = new Set(configStore.normalizeTaskIds(selectedTasks))
  return tasks.filter((task) => selectedSet.has(task.id)).map((task) => task.id)
}

function resetForm() {
  formData.value = initFormData()
  syncTaskListData(formData.value.task_list)
  currentSettingTaskId.value = null
  activeTab.value = "task-list"
  activeSection.value = "basic"
}

const { loading, handleSave } = useSchedulerTaskSave(
  taskRef,
  formData,
  wakeupEnabled,
  isCronNativeEligible,
  {
    focusSection: (section, tab) => {
      activeSection.value = section
      if (tab) {
        activeTab.value = tab
      }
    },
    close: () => {
      showDialog.value = false
    },
    saved: () => emit("saved"),
    reset: resetForm,
  },
)

watch(
  () => show,
  (open, previousOpen) => {
    if (open) {
      activeSection.value = "basic"
    } else if (previousOpen) {
      resetForm()
    }
  },
)

watch(
  () => task,
  (newTask) => {
    suppressFormInit.value = true
    formData.value = initFormData(newTask)
    syncTaskListData(formData.value.task_list)
    void nextTick(() => {
      suppressFormInit.value = false
    })
  },
)

// 控制器或资源变更时剔除不兼容任务，避免静默提交隐藏任务
watch(
  [() => formData.value.controller_name, () => formData.value.resource_name],
  ([controllerName, resourceName]) => {
    if (!showDialog.value || suppressFormInit.value) {
      return
    }

    const compatibleTaskIds = formData.value.task_list.filter((taskId) =>
      interfaceStore.isTaskCompatibleByName(taskId, controllerName, resourceName),
    )
    const removedCount = formData.value.task_list.length - compatibleTaskIds.length
    if (removedCount <= 0) {
      return
    }

    formData.value.task_list = compatibleTaskIds
    formData.value.task_options = configStore.buildOptionsForTasks(
      compatibleTaskIds,
      formData.value.task_options,
    )

    if (currentSettingTaskId.value && !compatibleTaskIds.includes(currentSettingTaskId.value)) {
      currentSettingTaskId.value = null
      activeTab.value = "task-list"
    }

    showGlobalMessage(
      "warning",
      t("settings.scheduler.dialog.removedIncompatibleTasks", {
        count: removedCount,
      }),
    )
  },
  { flush: "post" },
)

watch(
  availableTasks,
  () => {
    syncTaskListData(formData.value.task_list)
  },
  { immediate: true },
)

function handleTasksUpdate(tasks: TaskListItem[]) {
  taskListData.value = tasks
  formData.value.task_list = buildOrderedTaskList(formData.value.task_list, tasks)
}

function handleTriggerTypeChange(value: string | number) {
  if (value === "cron" || value === "date" || value === "interval") {
    setTriggerType(value)
  }
}

function handleSelectedTasksUpdate(newSelectedTasks: string[]) {
  const task_list = buildOrderedTaskList(newSelectedTasks)
  formData.value.task_list = task_list
  formData.value.task_options = configStore.buildOptionsForTasks(
    task_list,
    formData.value.task_options,
  )
  if (currentSettingTaskId.value && !task_list.includes(currentSettingTaskId.value)) {
    currentSettingTaskId.value = null
    activeTab.value = "task-list"
  }
}

function openTaskSettings(taskId: string) {
  if (!formData.value.task_list.includes(taskId)) {
    const task_list = buildOrderedTaskList([...formData.value.task_list, taskId])
    formData.value.task_list = task_list
    formData.value.task_options = configStore.buildOptionsForTasks(
      task_list,
      formData.value.task_options,
    )
  }
  currentSettingTaskId.value = taskId
  activeSection.value = "content"
  activeTab.value = "task-settings"
}

function handleCancel() {
  showDialog.value = false
  resetForm()
}
</script>
