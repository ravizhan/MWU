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
  type QueuedTaskItem,
  type TaskListItem,
  type TaskPresetSnapshot,
} from "@/types/taskConfigModel"
import {
  buildDefaultsFromOptionMap,
  normalizeOptionValueForBoundary,
} from "@/utils/task-config/options"

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

function createQueuedTaskItem(task: TaskListItem): QueuedTaskItem {
  return {
    uid: crypto.randomUUID(),
    id: task.id,
    name: task.name,
    order: task.order,
  }
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
    taskList: QueuedTaskItem[]
    selectedPresetName: string
    presetSnapshots: Record<string, TaskPresetSnapshot>
    configLoaded: boolean
    saveTimer: ReturnType<typeof setTimeout> | null
    preTasks: PreTaskCommand[]
  } => ({
    options: {},
    taskList: [],
    selectedPresetName: CUSTOM_PRESET_NAME,
    presetSnapshots: {},
    configLoaded: false,
    saveTimer: null,
    preTasks: [],
  }),
  getters: {
    selectedTaskIds(state): string[] {
      return state.taskList.map((task) => task.id)
    },
  },
  actions: {
    normalizeTaskIds(taskIds: string[]): string[] {
      const interfaceStore = useInterfaceStore()
      const validTaskIds = new Set(interfaceStore.getTaskList.map((task) => task.id))
      return taskIds.filter((taskId) => validTaskIds.has(taskId))
    },

    buildQueueFromIds(taskIds: string[]): QueuedTaskItem[] {
      const interfaceStore = useInterfaceStore()
      const taskMap = new Map(interfaceStore.getTaskList.map((task) => [task.id, task]))

      return taskIds.flatMap((taskId) => {
        const task = taskMap.get(taskId)
        return task === undefined ? [] : [createQueuedTaskItem(task)]
      })
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
        task_list,
        task_options: this.buildOptionsForTasks(task_list, overridesByTask),
        preTasks: this.preTasks ? [...this.preTasks] : [],
      }
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
      const tasks = this.taskList.map((task) => task.id)
      const taskOptions = this.buildOptionsFromPersisted(tasks, this.options)

      return {
        tasks,
        taskOptions,
        preTasks: [...this.preTasks],
      }
    },

    hydrateSnapshot(snapshot: TaskPresetSnapshot) {
      this.taskList = this.buildQueueFromIds(snapshot.tasks)
      this.options = this.buildOptionsFromPersisted(snapshot.tasks, snapshot.taskOptions)
      this.preTasks = snapshot.preTasks ? [...snapshot.preTasks] : []
    },

    normalizeSnapshot(snapshot?: TaskPresetSnapshot | null): TaskPresetSnapshot {
      const tasks = Array.isArray(snapshot?.tasks)
        ? this.normalizeTaskIds(
            snapshot.tasks.filter((taskId): taskId is string => typeof taskId === "string"),
          )
        : []
      const taskOptions = this.buildOptionsFromPersisted(tasks, snapshot?.taskOptions)

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
        tasks,
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

    buildPresetSnapshot(presetName: string): TaskPresetSnapshot | null {
      const interfaceStore = useInterfaceStore()
      const preset = interfaceStore.getPresetByName(presetName)
      if (!preset) {
        return null
      }

      const taskMap = new Map(interfaceStore.getTaskList.map((task) => [task.id, task]))
      const optionMap = interfaceStore.interface?.option || {}
      const tasks: string[] = []
      const taskOptions: TaskOptionsByTask = {}

      for (const presetTask of preset.task || []) {
        if (presetTask.enabled === false) {
          continue
        }

        const interfaceTask = interfaceStore.getTaskByName(presetTask.name)
        if (!interfaceTask) {
          continue
        }

        const taskItem = taskMap.get(interfaceTask.entry)
        if (taskItem === undefined) {
          continue
        }

        tasks.push(taskItem.id)
        if (taskOptions[taskItem.id] === undefined) {
          taskOptions[taskItem.id] = this.buildDefaultOptionsForTask(taskItem.id)
        }

        const taskOptionValues = taskOptions[taskItem.id]
        for (const [optionName, optionValue] of Object.entries(presetTask.option || {})) {
          applyPresetOptionValue(optionName, optionValue, optionMap, taskOptionValues)
        }
      }

      return this.normalizeSnapshot({
        tasks,
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
        selectedPreset: this.selectedPresetName,
        presets: normalizedSnapshots,
      }
    },

    async loadConfig() {
      const taskConfig = await getTaskConfig()
      this.presetSnapshots = this.seedPresetSnapshots(taskConfig.presets)

      const interfaceStore = useInterfaceStore()
      this.selectedPresetName =
        taskConfig.selectedPreset && this.presetSnapshots[taskConfig.selectedPreset]
          ? taskConfig.selectedPreset
          : (interfaceStore.getPresetList[0]?.name ?? CUSTOM_PRESET_NAME)
      this.hydrateSnapshot(this.presetSnapshots[this.selectedPresetName])
      this.configLoaded = true
    },

    debouncedSave() {
      if (this.saveTimer) {
        clearTimeout(this.saveTimer)
      }
      this.saveTimer = setTimeout(() => {
        void this.saveConfig()
      }, 500)
    },

    async saveConfig() {
      await saveTaskConfig(this.buildPersistedConfig())
    },

    async resetConfig() {
      await resetTaskConfig()
      this.presetSnapshots = this.seedPresetSnapshots()
      const interfaceStore = useInterfaceStore()
      this.selectedPresetName = interfaceStore.getPresetList[0]?.name ?? CUSTOM_PRESET_NAME
      this.preTasks = []
      this.hydrateSnapshot(this.presetSnapshots[this.selectedPresetName])
    },
  },
})
