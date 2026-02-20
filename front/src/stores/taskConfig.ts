import { defineStore } from "pinia"
import { getTaskConfig, saveTaskConfig, resetTaskConfig, type TaskConfig } from "../script/api"
import { type TaskListItem, useInterfaceStore } from "./interface"
import type { Option } from "../types/interface"
import type { TaskExecutionPayload } from "../types/scheduler"

// 根据选项定义生成默认值
function buildDefaultsFromOptionMap(optionMap: Record<string, Option>): Record<string, string> {
  const options: Record<string, string> = {}
  for (const key in optionMap) {
    const option = optionMap[key]!
    if (option.type === "select") {
      options[key] = option.default_case || option.cases[0]?.name || ""
    } else if (option.type === "input") {
      for (const input of option.inputs) {
        options[`${key}_${input.name}`] = input.default || ""
      }
    } else if (option.type === "switch") {
      options[key] = option.default_case || option.cases[0]?.name || ""
    }
  }
  return options
}

export const useTaskConfigStore = defineStore("taskConfig", {
  state: () => {
    return {
      options: {} as Record<string, string>,
      taskList: [] as TaskListItem[],
      configLoaded: false,
      saveTimer: null as ReturnType<typeof setTimeout> | null,
    }
  },
  actions: {
    normalizeTaskIds(taskIds: string[]): string[] {
      const interfaceStore = useInterfaceStore()
      const taskSource = this.taskList.length > 0 ? this.taskList : interfaceStore.getTaskList
      const validTaskIds = new Set(taskSource.map((task) => task.id))
      return [...new Set(taskIds)].filter((taskId) => validTaskIds.has(taskId))
    },

    buildDefaultOptions() {
      const interfaceStore = useInterfaceStore()
      const optionMap = interfaceStore.interface?.option || {}
      return buildDefaultsFromOptionMap(optionMap)
    },

    // 根据任务ID列表获取所需的选项（带默认值和用户覆盖）
    buildOptionsForTasks(
      taskIds: string[],
      overrides: Record<string, string> = {},
    ): Record<string, string> {
      const interfaceStore = useInterfaceStore()
      const normalizedTaskIds = this.normalizeTaskIds(taskIds)
      const mergedOptionMap: Record<string, Option> = {}

      // 收集所有选中任务的选项
      for (const taskId of normalizedTaskIds) {
        const taskOptions = interfaceStore.getOptionList(taskId)
        Object.assign(mergedOptionMap, taskOptions)
      }

      // 生成默认值
      const defaults = buildDefaultsFromOptionMap(mergedOptionMap)

      // 只过滤出相关的用户配置
      const relevantOptions: Record<string, string> = {}
      for (const key of Object.keys(defaults)) {
        if (this.options[key] !== undefined) {
          relevantOptions[key] = this.options[key]
        }
        if (overrides[key] !== undefined) {
          relevantOptions[key] = overrides[key]
        }
      }

      return {
        ...defaults,
        ...relevantOptions,
      }
    },

    buildExecutionPayload(
      taskIds: string[],
      overrides: Record<string, string> = {},
    ): TaskExecutionPayload {
      const task_list = this.normalizeTaskIds(taskIds)
      return {
        task_list,
        task_options: this.buildOptionsForTasks(task_list, overrides),
      }
    },

    buildDefaultTaskList() {
      const interfaceStore = useInterfaceStore()
      return interfaceStore.getTaskList.map((task) => ({ ...task, checked: false }))
    },

    async loadConfig() {
      const taskConfig = await getTaskConfig()

      this.options = this.buildDefaultOptions()
      if (taskConfig.taskOptions) {
        Object.assign(this.options, taskConfig.taskOptions)
      }

      this.taskList = this.buildDefaultTaskList()
      if (taskConfig.taskOrder && taskConfig.taskChecked) {
        const taskMap = new Map(this.taskList.map((task) => [task.id, task]))
        const reorderedTasks: TaskListItem[] = []
        for (const id of taskConfig.taskOrder) {
          const task = taskMap.get(id)
          if (task) {
            reorderedTasks.push({
              id: task.id,
              name: task.name,
              order: task.order,
              checked: taskConfig.taskChecked?.[id] || false,
            })
          }
        }
        this.taskList = reorderedTasks
      }

      this.configLoaded = true
    },

    debouncedSave() {
      if (this.saveTimer) {
        clearTimeout(this.saveTimer)
      }
      this.saveTimer = setTimeout(() => {
        this.saveConfig()
      }, 500)
    },

    async saveConfig() {
      const taskOrder = this.taskList.map((task) => task.id)
      const taskChecked: Record<string, boolean> = {}
      this.taskList.forEach((task) => {
        taskChecked[task.id] = task.checked || false
      })

      const config: TaskConfig = {
        taskOrder,
        taskChecked,
        taskOptions: { ...this.options },
      }
      await saveTaskConfig(config)
    },

    async resetConfig() {
      await resetTaskConfig()
      this.options = this.buildDefaultOptions()
      this.taskList = this.buildDefaultTaskList()
    },
  },
})
