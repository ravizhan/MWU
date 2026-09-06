import { defineStore } from "pinia"
import { getTaskConfig, resetTaskConfig, saveTaskConfig } from "@/services/api"
import { useInterfaceStore } from "@/stores"
import type { Option, PresetTaskOptionValue } from "@/types/interfaceModel"
import type {
  NullableTaskOptionValue,
  TaskExecutionPayload,
  TaskOptionsByTask,
  TaskOptionValue,
} from "@/types/schedulerModel"
import {
  CUSTOM_PRESET_NAME,
  type PersistedTaskConfig,
  type PreTaskCommand,
  type TaskListItem,
  type TaskPresetSnapshot,
} from "@/types/taskConfigModel"
import {
  buildDefaultsFromOptionMap,
  normalizeOptionValueForBoundary,
} from "@/utils/task-config/options"

export interface TaskConfigLoadError {
  code: string
  message: string
}

function cloneOptionValue(value: TaskOptionValue): TaskOptionValue
function cloneOptionValue(value: NullableTaskOptionValue): NullableTaskOptionValue {
  if (value === null) {
    return null
  }
  if (Array.isArray(value)) {
    return [...value]
  }
  if (value && typeof value === "object") {
    return { ...value }
  }
  return value
}

function cloneTaskOptionMap(
  optionMap: Record<string, TaskOptionValue> | null | undefined,
): Record<string, TaskOptionValue> {
  const clonedOptions: Record<string, TaskOptionValue> = {}
  if (!optionMap) {
    return clonedOptions
  }

  for (const [key, value] of Object.entries(optionMap)) {
    clonedOptions[key] = cloneOptionValue(value)
  }
  return clonedOptions
}

function cloneTaskOptionsByTask(
  optionsByTask: TaskOptionsByTask | null | undefined,
): TaskOptionsByTask {
  const cloned: TaskOptionsByTask = {}
  if (!optionsByTask) {
    return cloned
  }

  for (const [taskId, optionMap] of Object.entries(optionsByTask)) {
    const taskOptions: Record<string, TaskOptionValue> = {}
    for (const [key, value] of Object.entries(optionMap)) {
      taskOptions[key] = cloneOptionValue(value)
    }
    cloned[taskId] = taskOptions
  }
  return cloned
}

function buildTaskCheckedMap(taskList: TaskListItem[]): Record<string, boolean> {
  const taskChecked: Record<string, boolean> = {}
  for (const task of taskList) {
    taskChecked[task.id] = Boolean(task.checked)
  }
  return taskChecked
}

function buildTaskListFromOrder(
  defaultTaskList: TaskListItem[],
  taskOrder: string[] | null | undefined,
  taskChecked: Record<string, boolean>,
): TaskListItem[] {
  if (!taskOrder?.length) {
    return defaultTaskList.map((task) => ({
      ...task,
      checked: taskChecked[task.id] || false,
    }))
  }

  const taskMap = new Map(defaultTaskList.map((task) => [task.id, task]))
  const reorderedTasks: TaskListItem[] = []
  const seenTaskIds = new Set<string>()

  for (const id of taskOrder) {
    const task = taskMap.get(id)
    if (!task || seenTaskIds.has(id)) {
      continue
    }

    reorderedTasks.push({
      id: task.id,
      name: task.name,
      order: task.order,
      checked: taskChecked[id] || false,
    })
    seenTaskIds.add(id)
  }

  for (const task of defaultTaskList) {
    if (seenTaskIds.has(task.id)) {
      continue
    }

    reorderedTasks.push({
      id: task.id,
      name: task.name,
      order: task.order,
      checked: taskChecked[task.id] || false,
    })
  }

  return reorderedTasks
}

function isRecordStringString(value: unknown): value is Record<string, string> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function applyPresetInputValue(
  optionName: string,
  inputs: Array<{ name: string }>,
  value: Record<string, string>,
  targetOptions: Record<string, TaskOptionValue>,
) {
  const currentValue = targetOptions[optionName]
  const nextValue = isRecordStringString(currentValue) ? { ...currentValue } : {}

  for (const input of inputs) {
    const inputValue = value[input.name]
    if (typeof inputValue === "string") {
      nextValue[input.name] = inputValue
    }
  }

  targetOptions[optionName] = nextValue
}

function applyPresetOptionValue(
  optionName: string,
  value: PresetTaskOptionValue,
  optionMap: Record<string, Option>,
  targetOptions: Record<string, TaskOptionValue>,
) {
  const option = optionMap[optionName]
  if (!option) {
    return
  }

  if (option.type === "input") {
    if (!isRecordStringString(value)) {
      return
    }
    applyPresetInputValue(optionName, option.inputs, value, targetOptions)
    return
  }

  if (option.type === "checkbox") {
    if (Array.isArray(value)) {
      targetOptions[optionName] = value.filter((item): item is string => typeof item === "string")
    }
    return
  }

  if (typeof value === "string") {
    targetOptions[optionName] = value
  }
}

export const useTaskConfigStore = defineStore("taskConfig", {
  state: (): {
    options: TaskOptionsByTask
    taskList: TaskListItem[]
    selectedPresetName: string
    presetSnapshots: Record<string, TaskPresetSnapshot>
    configLoaded: boolean
    configLoadError: TaskConfigLoadError | null
    saveTimer: ReturnType<typeof setTimeout> | null
    preTasks: PreTaskCommand[]
  } => ({
    options: {},
    taskList: [],
    selectedPresetName: CUSTOM_PRESET_NAME,
    presetSnapshots: {},
    configLoaded: false,
    configLoadError: null,
    saveTimer: null,
    preTasks: [],
  }),
  getters: {
    selectedTaskIds(state): string[] {
      return state.taskList.filter((task) => task.checked).map((task) => task.id)
    },
  },
  actions: {
    normalizeTaskIds(taskIds: string[]): string[] {
      const interfaceStore = useInterfaceStore()
      const taskSource = this.taskList.length > 0 ? this.taskList : interfaceStore.getTaskList
      const validTaskIds = new Set(taskSource.map((task) => task.id))
      return [...new Set(taskIds)].filter((taskId) => validTaskIds.has(taskId))
    },

    buildDefaultOptionsForTask(taskId: string): Record<string, TaskOptionValue> {
      const interfaceStore = useInterfaceStore()
      const optionMap = interfaceStore.getOptionList(taskId)
      return buildDefaultsFromOptionMap(optionMap)
    },

    buildOptionsForTasks(
      taskIds: string[],
      overridesByTask: TaskOptionsByTask = {},
    ): TaskOptionsByTask {
      const normalizedTaskIds = this.normalizeTaskIds(taskIds)
      const mergedTaskOptions: TaskOptionsByTask = {}

      for (const taskId of normalizedTaskIds) {
        const defaults = this.buildDefaultOptionsForTask(taskId)
        const currentTaskOptions = this.options[taskId] || {}
        const overrideTaskOptions = overridesByTask[taskId] || {}
        const relevantOptions: Record<string, TaskOptionValue> = {}

        for (const key of Object.keys(defaults)) {
          const currentValue = normalizeOptionValueForBoundary(currentTaskOptions[key])
          if (currentValue !== undefined) {
            relevantOptions[key] = currentValue
          }

          const overrideValue = normalizeOptionValueForBoundary(overrideTaskOptions[key])
          if (overrideValue !== undefined) {
            relevantOptions[key] = overrideValue
          }
        }

        mergedTaskOptions[taskId] = {
          ...cloneTaskOptionMap(defaults),
          ...cloneTaskOptionMap(relevantOptions),
        }
      }

      return mergedTaskOptions
    },

    buildExecutionPayload(
      taskIds: string[],
      overridesByTask: TaskOptionsByTask = {},
    ): TaskExecutionPayload {
      const task_list = this.normalizeTaskIds(taskIds)
      return {
        task_identity: "name",
        task_list,
        task_options: this.buildOptionsForTasks(task_list, overridesByTask),
        preTasks: this.preTasks ? [...this.preTasks] : [],
      }
    },

    buildDefaultTaskList() {
      const interfaceStore = useInterfaceStore()
      return interfaceStore.getTaskList.map((task) => ({ ...task, checked: false }))
    },

    buildTaskListFromPersisted(
      taskOrder: string[] | null | undefined,
      taskChecked: Record<string, boolean> | null | undefined,
    ): TaskListItem[] {
      return buildTaskListFromOrder(this.buildDefaultTaskList(), taskOrder, taskChecked || {})
    },

    buildOptionsFromPersisted(
      taskIds: string[],
      optionsByTask: TaskOptionsByTask | null | undefined,
    ): TaskOptionsByTask {
      const normalizedTaskIds = this.normalizeTaskIds(taskIds)
      const mergedTaskOptions: TaskOptionsByTask = {}

      for (const taskId of normalizedTaskIds) {
        const defaults = this.buildDefaultOptionsForTask(taskId)
        const persistedTaskOptions = optionsByTask?.[taskId]
        const mergedOptions: Record<string, TaskOptionValue> = cloneTaskOptionMap(defaults)

        if (persistedTaskOptions) {
          for (const key of Object.keys(defaults)) {
            const normalizedValue = normalizeOptionValueForBoundary(persistedTaskOptions[key])
            if (normalizedValue !== undefined) {
              mergedOptions[key] = normalizedValue
            }
          }
        }

        mergedTaskOptions[taskId] = mergedOptions
      }

      return mergedTaskOptions
    },

    serializeCurrentSnapshot(): TaskPresetSnapshot {
      const taskOrder = this.taskList.map((task) => task.id)
      const taskChecked = buildTaskCheckedMap(this.taskList)
      const taskOptions = this.buildOptionsFromPersisted(taskOrder, this.options)

      return {
        taskOrder,
        taskChecked,
        taskOptions,
        preTasks: [...this.preTasks],
      }
    },

    hydrateSnapshot(snapshot: TaskPresetSnapshot) {
      this.taskList = this.buildTaskListFromPersisted(snapshot.taskOrder, snapshot.taskChecked)
      const taskIds = this.taskList.map((task) => task.id)
      this.options = this.buildOptionsFromPersisted(taskIds, snapshot.taskOptions)
      this.preTasks = snapshot.preTasks ? [...snapshot.preTasks] : []
    },

    normalizeSnapshot(snapshot?: TaskPresetSnapshot | null): TaskPresetSnapshot {
      const taskList = this.buildTaskListFromPersisted(snapshot?.taskOrder, snapshot?.taskChecked)
      const taskIds = taskList.map((task) => task.id)
      const taskOptions = this.buildOptionsFromPersisted(taskIds, snapshot?.taskOptions)

      const preTasks = Array.isArray(snapshot?.preTasks)
        ? snapshot.preTasks
            .filter((pt) => typeof pt.command === "string" && pt.command.length > 0)
            .map((pt) => ({
              id: pt.id || crypto.randomUUID(),
              command: pt.command,
              enabled: typeof pt.enabled === "boolean" ? pt.enabled : true,
              timeout: typeof pt.timeout === "number" && pt.timeout > 0 ? pt.timeout : 30,
            }))
        : []

      return {
        taskOrder: taskIds,
        taskChecked: buildTaskCheckedMap(taskList),
        taskOptions: cloneTaskOptionsByTask(taskOptions),
        preTasks,
      }
    },

    buildDefaultTaskOptionsByTask(taskList: TaskListItem[]): TaskOptionsByTask {
      const taskOptions: TaskOptionsByTask = {}
      for (const task of taskList) {
        taskOptions[task.id] = this.buildDefaultOptionsForTask(task.id)
      }
      return taskOptions
    },

    appendUnusedTaskIds(
      taskList: TaskListItem[],
      usedTaskIds: Set<string>,
      orderedTaskIds: string[],
    ) {
      for (const task of taskList) {
        if (!usedTaskIds.has(task.id)) {
          orderedTaskIds.push(task.id)
        }
      }
    },

    processPresetTasks(
      presetTasks: Array<{
        name: string
        enabled?: boolean
        option?: Record<string, PresetTaskOptionValue>
      }>,
      taskMap: Map<string, TaskListItem>,
      optionMap: Record<string, Option>,
      taskOptions: TaskOptionsByTask,
      taskChecked: Record<string, boolean>,
      orderedTaskIds: string[],
      usedTaskIds: Set<string>,
    ) {
      const interfaceStore = useInterfaceStore()
      for (const presetTask of presetTasks) {
        const interfaceTask = interfaceStore.getTaskByName(presetTask.name)
        if (!interfaceTask) {
          continue
        }

        const taskItem = taskMap.get(interfaceTask.name)
        if (!taskItem || usedTaskIds.has(taskItem.id)) {
          continue
        }

        orderedTaskIds.push(taskItem.id)
        usedTaskIds.add(taskItem.id)
        taskChecked[taskItem.id] = presetTask.enabled ?? true

        const taskOptionValues = taskOptions[taskItem.id] || {}
        for (const [optionName, optionValue] of Object.entries(presetTask.option || {})) {
          applyPresetOptionValue(optionName, optionValue, optionMap, taskOptionValues)
        }
        taskOptions[taskItem.id] = taskOptionValues
      }
    },

    buildPresetSnapshot(presetName: string): TaskPresetSnapshot | null {
      const interfaceStore = useInterfaceStore()
      const preset = interfaceStore.getPresetByName(presetName)
      if (!preset) {
        return null
      }

      const defaultTaskList = this.buildDefaultTaskList()
      const taskMap = new Map(defaultTaskList.map((task) => [task.id, task]))
      const taskChecked = buildTaskCheckedMap(defaultTaskList)
      const orderedTaskIds: string[] = []
      const usedTaskIds = new Set<string>()
      const optionMap = interfaceStore.interface?.option || {}
      const taskOptions = this.buildDefaultTaskOptionsByTask(defaultTaskList)

      this.processPresetTasks(
        preset.task || [],
        taskMap,
        optionMap,
        taskOptions,
        taskChecked,
        orderedTaskIds,
        usedTaskIds,
      )
      this.appendUnusedTaskIds(defaultTaskList, usedTaskIds, orderedTaskIds)

      return this.normalizeSnapshot({
        taskOrder: orderedTaskIds,
        taskChecked,
        taskOptions,
        preTasks: [],
      })
    },

    seedPresetSnapshots(
      persistedSnapshots: Record<string, TaskPresetSnapshot> = {},
    ): Record<string, TaskPresetSnapshot> {
      const interfaceStore = useInterfaceStore()
      const presetSnapshots: Record<string, TaskPresetSnapshot> = {
        [CUSTOM_PRESET_NAME]: this.normalizeSnapshot(persistedSnapshots[CUSTOM_PRESET_NAME]),
      }

      for (const preset of interfaceStore.getPresetList) {
        presetSnapshots[preset.name] = this.normalizeSnapshot(
          persistedSnapshots[preset.name] || this.buildPresetSnapshot(preset.name),
        )
      }

      return presetSnapshots
    },

    syncCurrentPresetSnapshot() {
      this.presetSnapshots[this.selectedPresetName] = this.serializeCurrentSnapshot()
    },

    selectPreset(presetName: string): boolean {
      const targetPresetName = presetName || CUSTOM_PRESET_NAME
      const targetSnapshot = this.presetSnapshots[targetPresetName]
      if (!targetSnapshot) {
        return false
      }

      if (targetPresetName === this.selectedPresetName) {
        return true
      }

      this.syncCurrentPresetSnapshot()
      this.selectedPresetName = targetPresetName
      this.hydrateSnapshot(targetSnapshot)
      return true
    },

    buildPersistedConfig(): PersistedTaskConfig {
      this.syncCurrentPresetSnapshot()

      const normalizedSnapshots = Object.fromEntries(
        Object.entries(this.presetSnapshots).map(([presetName, snapshot]) => [
          presetName,
          this.normalizeSnapshot(snapshot),
        ]),
      )

      return {
        taskIdentity: "name",
        selectedPreset: this.selectedPresetName,
        presets: normalizedSnapshots,
      }
    },

    async loadConfig() {
      const taskConfig = await getTaskConfig()
      if (!taskConfig.ok) {
        if (this.saveTimer) {
          clearTimeout(this.saveTimer)
          this.saveTimer = null
        }
        this.configLoaded = false
        this.configLoadError = {
          code: taskConfig.code,
          message: taskConfig.message,
        }
        return
      }

      const persistedConfig = taskConfig.config
      this.presetSnapshots = this.seedPresetSnapshots(persistedConfig.presets)

      this.selectedPresetName =
        persistedConfig.selectedPreset && this.presetSnapshots[persistedConfig.selectedPreset]
          ? persistedConfig.selectedPreset
          : CUSTOM_PRESET_NAME
      this.hydrateSnapshot(this.presetSnapshots[this.selectedPresetName])
      this.configLoaded = true
      this.configLoadError = null
    },

    debouncedSave() {
      if (!this.configLoaded) {
        return
      }

      if (this.saveTimer) {
        clearTimeout(this.saveTimer)
      }
      this.saveTimer = setTimeout(() => {
        void this.saveConfig()
      }, 500)
    },

    async saveConfig() {
      if (!this.configLoaded) {
        return
      }
      await saveTaskConfig(this.buildPersistedConfig())
    },

    async resetConfig() {
      const resetSucceeded = await resetTaskConfig()
      if (!resetSucceeded) {
        return
      }

      if (this.saveTimer) {
        clearTimeout(this.saveTimer)
        this.saveTimer = null
      }
      this.presetSnapshots = this.seedPresetSnapshots()
      this.selectedPresetName = CUSTOM_PRESET_NAME
      this.preTasks = []
      this.hydrateSnapshot(this.presetSnapshots[CUSTOM_PRESET_NAME])
      this.configLoaded = true
      this.configLoadError = null
    },
  },
})
