import { computed, ref, watch, type Ref } from "vue"
import { useTaskConfigStore } from "@/stores"
import { checkNativeEligibility } from "@/validation/cron"
import type {
  ScheduledTask,
  ScheduledTaskCreate,
  TriggerConfig,
  TriggerType,
  CronTriggerConfig,
  DateTriggerConfig,
  IntervalTriggerConfig,
} from "@/types/schedulerModel"

export type SchedulerTaskFormData = Omit<ScheduledTaskCreate, "wakeup_enabled">

export interface SchedulerTaskForm {
  formData: Ref<SchedulerTaskFormData>
  wakeupEnabled: Ref<boolean>
  triggerType: Ref<TriggerType>
  isCronNativeEligible: Ref<boolean>
  cronConfig: Ref<CronTriggerConfig>
  dateConfig: Ref<DateTriggerConfig>
  intervalConfig: Ref<IntervalTriggerConfig>
  initFormData: (task?: ScheduledTask | null) => SchedulerTaskFormData
  setTriggerType: (newType: TriggerType) => void
  updateTriggerConfig: (updates: Partial<TriggerConfig>) => void
  setCronPreset: (preset: string) => void
}

function buildCronConfig(existing?: Partial<TriggerConfig>): CronTriggerConfig {
  const config = existing?.type === "cron" ? existing : undefined
  return { type: "cron", cron: config?.cron ?? "0 0 * * *" }
}

function buildDateConfig(existing?: Partial<TriggerConfig>): DateTriggerConfig {
  const config = existing?.type === "date" ? existing : undefined
  return { type: "date", run_date: config?.run_date ?? new Date().toISOString() }
}

function buildIntervalConfig(existing?: Partial<TriggerConfig>): IntervalTriggerConfig {
  const config = existing?.type === "interval" ? existing : undefined
  const result: IntervalTriggerConfig = {
    type: "interval",
    weeks: 0,
    days: 0,
    hours: 1,
    minutes: 0,
    seconds: 0,
  }
  if (config === undefined) {
    return result
  }
  if (config.weeks !== undefined) {
    result.weeks = config.weeks
  }
  if (config.days !== undefined) {
    result.days = config.days
  }
  if (config.hours !== undefined) {
    result.hours = config.hours
  }
  if (config.minutes !== undefined) {
    result.minutes = config.minutes
  }
  if (config.seconds !== undefined) {
    result.seconds = config.seconds
  }
  result.start_date = config.start_date
  result.end_date = config.end_date
  return result
}

function getTriggerConfigByType(
  type: TriggerType,
  existing?: Partial<TriggerConfig>,
): TriggerConfig {
  switch (type) {
    case "cron":
      return buildCronConfig(existing)
    case "date":
      return buildDateConfig(existing)
    case "interval":
      return buildIntervalConfig(existing)
    default:
      return buildCronConfig()
  }
}

export function useSchedulerTaskForm(): SchedulerTaskForm {
  const configStore = useTaskConfigStore()

  const formData = ref<SchedulerTaskFormData>({
    task_identity: "name",
    name: "",
    description: "",
    enabled: true,
    trigger_config: getTriggerConfigByType("cron"),
    task_list: [],
    task_options: configStore.buildOptionsForTasks([]),
    preTasks: [],
    controller_name: null,
    device: null,
    resource_name: null,
  })
  const wakeupEnabled = ref(false)

  const triggerType = computed(() => formData.value.trigger_config.type)

  const cronConfig = computed<CronTriggerConfig>(() => {
    const config = formData.value.trigger_config
    return config.type === "cron" ? config : { type: "cron", cron: "" }
  })
  const dateConfig = computed<DateTriggerConfig>(() => {
    const config = formData.value.trigger_config
    return config.type === "date" ? config : { type: "date", run_date: "" }
  })
  const intervalConfig = computed<IntervalTriggerConfig>(() => {
    const config = formData.value.trigger_config
    return config.type === "interval" ? config : { type: "interval" }
  })

  const isCronNativeEligible = computed(() => {
    const config = formData.value.trigger_config
    return config.type === "cron" && checkNativeEligibility(config.cron)
  })

  // cron 从合格变为不合格时同步清空唤醒开关，避免隐藏值随提交被静默屏蔽
  watch(isCronNativeEligible, (eligible) => {
    if (!eligible) {
      wakeupEnabled.value = false
    }
  })

  function initFormData(task?: ScheduledTask | null): SchedulerTaskFormData {
    wakeupEnabled.value = task ? (task.wakeup_enabled ?? false) : false
    if (task) {
      const normalizedTaskIds = configStore.normalizeTaskIds(task.task_list)
      const normalizedTaskIdSet = new Set(normalizedTaskIds)
      const unknownTaskIds = [
        ...new Set(task.task_list.filter((taskId) => !normalizedTaskIdSet.has(taskId))),
      ]
      const task_list = [...normalizedTaskIds, ...unknownTaskIds]
      return {
        task_identity: "name",
        name: task.name,
        description: task.description || "",
        enabled: task.enabled,
        trigger_config: getTriggerConfigByType(task.trigger_config.type, task.trigger_config),
        task_list,
        task_options: configStore.buildOptionsForTasks(task_list, task.task_options),
        preTasks: Array.isArray(task.preTasks) ? task.preTasks.map((pt) => ({ ...pt })) : [],
        controller_name: task.controller_name,
        device: task.device ? { ...task.device } : null,
        resource_name: task.resource_name,
      }
    }
    return {
      task_identity: "name",
      name: "",
      description: "",
      enabled: true,
      trigger_config: getTriggerConfigByType("cron"),
      task_list: [],
      task_options: configStore.buildOptionsForTasks([]),
      preTasks: [],
      controller_name: null,
      device: null,
      resource_name: null,
    }
  }

  function setTriggerType(newType: TriggerType) {
    formData.value.trigger_config = getTriggerConfigByType(newType)
    if (newType !== "cron") {
      wakeupEnabled.value = false
    }
  }

  function updateTriggerConfig(updates: Partial<TriggerConfig>) {
    formData.value.trigger_config = Object.assign({}, formData.value.trigger_config, updates)
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

  return {
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
  }
}
