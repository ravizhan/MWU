<template>
  <n-modal
    v-model:show="showDialog"
    preset="card"
    :title="
      isEditMode
        ? t('settings.scheduler.dialog.editTitle')
        : t('settings.scheduler.dialog.createTitle')
    "
    class="xl:w-45% w-95"
  >
    <n-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-placement="left"
      label-width="100"
    >
      <n-form-item :label="t('settings.scheduler.dialog.taskName')" path="name">
        <n-input
          v-model:value="formData.name"
          :placeholder="t('settings.scheduler.dialog.taskNamePlaceholder')"
        />
      </n-form-item>

      <n-form-item :label="t('settings.scheduler.dialog.taskDesc')" path="description">
        <n-input
          v-model:value="formData.description"
          type="textarea"
          :placeholder="t('settings.scheduler.dialog.taskDescPlaceholder')"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </n-form-item>

      <n-form-item :label="t('settings.scheduler.dialog.triggerType')" path="trigger_type">
        <n-radio-group v-model:value="formData.trigger_type">
          <n-radio value="cron">{{ t("settings.scheduler.dialog.cronExpression") }}</n-radio>
          <n-radio value="date">{{ t("settings.scheduler.dialog.specificTime") }}</n-radio>
          <n-radio value="interval">{{ t("settings.scheduler.dialog.intervalExecution") }}</n-radio>
        </n-radio-group>
      </n-form-item>

      <!-- Cron 表达式编辑器 -->
      <template v-if="formData.trigger_type === 'cron'">
        <n-form-item
          :label="t('settings.scheduler.dialog.cronExpression')"
          path="trigger_config.cron"
        >
          <n-input
            :value="cronConfig.cron"
            @update:value="(v: string) => updateTriggerConfig({ cron: v })"
            :placeholder="t('settings.scheduler.dialog.cronPlaceholder')"
          />
        </n-form-item>
        <n-form-item :label="t('settings.scheduler.dialog.quickSelect')">
          <n-space>
            <n-button size="small" @click="setCronPreset('daily')">{{
              t("settings.scheduler.dialog.presets.daily")
            }}</n-button>
            <n-button size="small" @click="setCronPreset('daily9am')">{{
              t("settings.scheduler.dialog.presets.daily9am")
            }}</n-button>
            <n-button size="small" @click="setCronPreset('weekly')">{{
              t("settings.scheduler.dialog.presets.weekly")
            }}</n-button>
            <n-button size="small" @click="setCronPreset('hourly')">{{
              t("settings.scheduler.dialog.presets.hourly")
            }}</n-button>
          </n-space>
        </n-form-item>
      </template>

      <!-- Date 触发器 -->
      <template v-if="formData.trigger_type === 'date'">
        <n-form-item
          :label="t('settings.scheduler.dialog.executionTime')"
          path="trigger_config.run_date"
        >
          <n-date-picker
            :value="dateConfigTimestamp"
            @update:value="
              (v: number | null) =>
                updateTriggerConfig({
                  run_date: v ? new Date(v).toISOString() : new Date().toISOString(),
                })
            "
            type="datetime"
            :placeholder="t('settings.scheduler.dialog.selectTime')"
            style="width: 100%"
          />
        </n-form-item>
      </template>

      <!-- Interval 触发器 -->
      <template v-if="formData.trigger_type === 'interval'">
        <n-form-item :label="t('settings.scheduler.dialog.intervalTime')" path="trigger_config">
          <n-flex>
            <n-input-number
              :value="intervalConfig.hours"
              @update:value="(v: number | null) => updateTriggerConfig({ hours: v || 0 })"
              :min="0"
              style="width: 45%"
            >
              <template #suffix>{{ t("settings.scheduler.formatter.hour") }}</template>
            </n-input-number>
            <n-input-number
              :value="intervalConfig.minutes"
              @update:value="(v: number | null) => updateTriggerConfig({ minutes: v || 0 })"
              :min="0"
              style="width: 45%"
            >
              <template #suffix>{{ t("settings.scheduler.formatter.minute") }}</template>
            </n-input-number>
          </n-flex>
        </n-form-item>
      </template>

      <n-tabs v-model:value="activeTab" type="segment" animated>
        <!-- Tab 1: 任务列表 -->
        <n-tab-pane name="task-list" :tab="t('settings.scheduler.dialog.tab.taskList')">
          <n-scrollbar trigger="none" class="max-h-65 !rounded-[12px]">
            <TaskSelectList
              :tasks="availableTasks"
              :selected-tasks="formData.task_list"
              @update:selected-tasks="handleSelectedTasksUpdate"
              @config="openTaskSettings"
            />
          </n-scrollbar>
        </n-tab-pane>

        <!-- Tab 2: 任务设置 -->
        <n-tab-pane name="task-settings" :tab="t('settings.scheduler.dialog.tab.taskSettings')">
          <TaskOptionPanel
            :current-task-id="currentSettingTaskId"
            :options="formData.task_options"
            :show-header="true"
            :header-label="t('settings.scheduler.dialog.currentSetting')"
            :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
            :no-options-text="t('settings.scheduler.dialog.noOptions')"
          />
        </n-tab-pane>
      </n-tabs>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="handleCancel">{{ t("common.cancel") }}</n-button>
        <n-button type="primary" @click="handleSave" :loading="loading">{{
          t("common.save")
        }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue"
import { useMessage, type FormInst, type FormRules } from "naive-ui"
import { useI18n } from "vue-i18n"
import { useSchedulerStore } from "../stores/scheduler"
import { useInterfaceStore } from "../stores/interface"
import { useTaskConfigStore } from "../stores/taskConfig"
import TaskSelectList from "./TaskSelectList.vue"
import TaskOptionPanel from "./TaskOptionPanel.vue"
import type {
  ScheduledTask,
  ScheduledTaskCreate,
  TriggerType,
  TriggerConfig,
  CronTriggerConfig,
  DateTriggerConfig,
  IntervalTriggerConfig,
} from "../types/scheduler"

interface Props {
  show: boolean
  task?: ScheduledTask | null
}

interface Emits {
  (e: "update:show", value: boolean): void
  (e: "saved"): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const message = useMessage()
const { t } = useI18n()
const schedulerStore = useSchedulerStore()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()

const formRef = ref<FormInst | null>(null)
const loading = ref(false)

const activeTab = ref<"task-list" | "task-settings">("task-list")
const currentSettingTaskId = ref<string | null>(null)

const showDialog = computed({
  get: () => props.show,
  set: (value) => emit("update:show", value),
})

const isEditMode = computed(() => !!props.task)
const availableTasks = computed(() => interfaceStore.getTaskList)

// 触发器配置的 computed 属性
const cronConfig = computed(() => formData.value.trigger_config as CronTriggerConfig)
const dateConfig = computed(() => formData.value.trigger_config as DateTriggerConfig)
const dateConfigTimestamp = computed(() =>
  dateConfig.value.run_date ? new Date(dateConfig.value.run_date).getTime() : null,
)
const intervalConfig = computed(() => formData.value.trigger_config as IntervalTriggerConfig)

const formData = ref<ScheduledTaskCreate>(initFormData(props.task))

const formRules = computed<FormRules>(() => ({
  name: [
    { required: true, message: t("settings.scheduler.rules.nameRequired"), trigger: "blur" },
    { min: 1, max: 100, message: t("settings.scheduler.rules.nameLength"), trigger: "blur" },
  ],
  "trigger_config.cron": [
    {
      validator: (rule, value: string) => {
        if (formData.value.trigger_type !== "cron") return true
        if (!value) return new Error(t("settings.scheduler.rules.cronRequired"))
        const pattern =
          /^(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)\s+(\*|[0-9\-*,/]+)$/
        if (!pattern.test(value)) return new Error(t("settings.scheduler.rules.cronInvalid"))
        return true
      },
      trigger: ["blur", "input"],
    },
  ],
  "trigger_config.run_date": [
    {
      validator: (rule, value: string) => {
        if (formData.value.trigger_type !== "date") return true
        if (!value) return new Error(t("settings.scheduler.rules.dateRequired"))
        if (new Date(value).getTime() < Date.now())
          return new Error(t("settings.scheduler.rules.dateInPast"))
        return true
      },
      trigger: ["blur", "change"],
    },
  ],
  trigger_config: [
    {
      validator: (rule, value: IntervalTriggerConfig) => {
        if (formData.value.trigger_type !== "interval") return true
        if ((value.hours || 0) <= 0 && (value.minutes || 0) <= 0) {
          return new Error(t("settings.scheduler.rules.intervalRequired"))
        }
        return true
      },
      trigger: ["blur", "change"],
    },
  ],
  task_list: [
    {
      type: "array",
      required: true,
      min: 1,
      message: t("settings.scheduler.rules.taskListRequired"),
      trigger: "change",
    },
  ],
}))

// 监听触发器类型变化，更新 trigger_config
watch(
  () => formData.value.trigger_type,
  (newType) => {
    formData.value.trigger_config = getTriggerConfigByType(newType)
  },
)

// 监听编辑模式，填充表单
watch(
  () => props.task,
  (task) => {
    formData.value = initFormData(task)
  },
)

function resetForm() {
  formData.value = initFormData()
  currentSettingTaskId.value = null
  activeTab.value = "task-list"
}

// 初始化表单数据
function initFormData(task?: ScheduledTask | null): ScheduledTaskCreate {
  if (task) {
    const task_list = configStore.normalizeTaskIds(task.task_list)
    return {
      name: task.name,
      description: task.description || "",
      enabled: task.enabled,
      trigger_type: task.trigger_type,
      trigger_config: { ...task.trigger_config },
      task_list,
      task_options: configStore.buildOptionsForTasks(task_list, task.task_options),
    }
  }
  return {
    name: "",
    description: "",
    enabled: true,
    trigger_type: "cron",
    trigger_config: getTriggerConfigByType("cron"),
    task_list: [],
    task_options: configStore.buildOptionsForTasks([]),
  }
}

// 根据类型获取触发器配置
function getTriggerConfigByType(
  type: TriggerType,
  existing?: Partial<TriggerConfig>,
): TriggerConfig {
  switch (type) {
    case "cron":
      return { type: "cron", cron: (existing as CronTriggerConfig)?.cron ?? "0 0 * * *" }
    case "date":
      return {
        type: "date",
        run_date: (existing as DateTriggerConfig)?.run_date ?? new Date().toISOString(),
      }
    case "interval":
      return {
        type: "interval",
        hours: (existing as IntervalTriggerConfig)?.hours ?? 1,
        minutes: (existing as IntervalTriggerConfig)?.minutes ?? 0,
      } as IntervalTriggerConfig
    default:
      return { type: "cron", cron: "0 0 * * *" }
  }
}

function updateTriggerConfig(updates: Partial<TriggerConfig>) {
  formData.value.trigger_config = {
    ...formData.value.trigger_config,
    ...updates,
  } as TriggerConfig
}

function setCronPreset(preset: string) {
  const presets: Record<string, string> = {
    daily: "0 0 * * *",
    daily9am: "0 9 * * *",
    weekly: "0 0 * * 1",
    hourly: "0 * * * *",
  }
  updateTriggerConfig({ cron: presets[preset] })
}

// 处理任务选择更新
function handleSelectedTasksUpdate(newSelectedTasks: string[]) {
  const task_list = configStore.normalizeTaskIds(newSelectedTasks)
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
    const task_list = configStore.normalizeTaskIds([...formData.value.task_list, taskId])
    formData.value.task_list = task_list
    formData.value.task_options = configStore.buildOptionsForTasks(
      task_list,
      formData.value.task_options,
    )
  }
  currentSettingTaskId.value = taskId
  activeTab.value = "task-settings"
}

async function handleSave() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  loading.value = true
  try {
    const taskPayload = {
      ...formData.value,
      ...configStore.buildExecutionPayload(formData.value.task_list, formData.value.task_options),
    }
    let success = false
    if (isEditMode.value && props.task) {
      success = await schedulerStore.updateTask(props.task.id, taskPayload)
    } else {
      success = await schedulerStore.createTask(taskPayload)
    }

    if (success) {
      message.success(
        isEditMode.value
          ? t("settings.scheduler.dialog.taskUpdated")
          : t("settings.scheduler.dialog.taskCreated"),
      )
      showDialog.value = false
      emit("saved")
      resetForm()
    } else {
      message.error(schedulerStore.error || t("settings.scheduler.dialog.saveFail"))
    }
  } catch (e) {
    message.error(t("settings.scheduler.dialog.saveFail"))
    console.error("Failed to save task:", e)
  } finally {
    loading.value = false
  }
}

function handleCancel() {
  showDialog.value = false
  resetForm()
}
</script>
