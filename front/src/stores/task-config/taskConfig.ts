import { defineStore } from "pinia"
import i18n from "@/app/i18n"
import { getTaskConfig, resetTaskConfig, saveTaskConfig } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useInterfaceStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"
import type { Option, Preset, PresetTaskOptionValue } from "@/types/interfaceModel"
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

    addTaskToQueue(taskName: string): QueuedTaskItem | null {
      const interfaceStore = useInterfaceStore()
      const task = interfaceStore.getTaskList.find((item) => item.id === taskName)
      if (!task) {
        return null
      }
      const queuedItem = createQueuedTaskItem(task)
      this.taskList = [...this.taskList, queuedItem]
      // 首次入队时填充默认选项，保证选项面板直接显示 interface 默认值
      // （含默认 case 下的嵌套选项），而不是空白控件
      if (this.options[task.id] === undefined) {
        this.options[task.id] = this.buildDefaultOptionsForTask(task.id)
      }
      return queuedItem
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

    serializeCurrentSnapshot(): TaskPresetSnapshot {
      const tasks = this.taskList.map((task) => task.id)
      return {
        tasks,
        taskOptions: this.buildOptionsForTasks(tasks),
        preTasks: [...this.preTasks],
      }
    },

    /** Snapshots carry complete option maps (server-normalized or built from the interface). */
    hydrateSnapshot(snapshot: TaskPresetSnapshot) {
      this.taskList = this.buildQueueFromIds(snapshot.tasks)
      this.options = cloneTaskOptionsByTask(snapshot.taskOptions)
      this.preTasks = [...snapshot.preTasks]
    },

    /** Client-only normalization: interface preset declaration -> preset snapshot. */
    buildPresetSnapshot(preset: Preset): TaskPresetSnapshot {
      const interfaceStore = useInterfaceStore()
      const taskMap = new Map(interfaceStore.getTaskList.map((task) => [task.id, task]))
      const optionMap = interfaceStore.interface?.option || {}
      const tasks: string[] = []
      const taskOptions: TaskOptionsByTask = {}

      for (const presetTask of preset.task || []) {
        if (presetTask.enabled === false) {
          continue
        }

        const taskItem = taskMap.get(presetTask.name)
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

      return { tasks, taskOptions: cloneTaskOptionsByTask(taskOptions), preTasks: [] }
    },

    /** Server-normalized snapshots are trusted as-is; presets the server did not send fall back to the interface. */
    seedPresetSnapshots(
      persistedSnapshots: Record<string, TaskPresetSnapshot> = {},
    ): Record<string, TaskPresetSnapshot> {
      const interfaceStore = useInterfaceStore()
      const presetSnapshots: Record<string, TaskPresetSnapshot> = {
        [CUSTOM_PRESET_NAME]: persistedSnapshots[CUSTOM_PRESET_NAME] ?? {
          tasks: [],
          taskOptions: {},
          preTasks: [],
        },
      }

      for (const preset of interfaceStore.getPresetList) {
        presetSnapshots[preset.name] =
          persistedSnapshots[preset.name] ?? this.buildPresetSnapshot(preset)
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
      return {
        selectedPreset: this.selectedPresetName,
        presets: { ...this.presetSnapshots },
      }
    },

    async loadConfig() {
      const [taskConfig, error] = await tryCatch(() => getTaskConfig())
      if (!taskConfig) {
        // No synthetic defaults: `configLoaded` stays false so autosave cannot
        // overwrite the persisted task_config.json with a regenerated config.
        console.error("Failed to load task config:", error)
        showGlobalMessage("error", i18n.global.t("panel.taskConfigLoadFailed"))
        return
      }

      this.presetSnapshots = this.seedPresetSnapshots(taskConfig.presets)
      this.selectedPresetName = taskConfig.selectedPreset
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
