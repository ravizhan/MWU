import { defineStore } from "pinia"
import { getUserConfig, saveUserConfig, resetUserConfig, type UserConfig } from "../script/api"
import { type TaskListItem, useInterfaceStore } from "./interface"
import type { Option } from "../types/interface"

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

export const useUserConfigStore = defineStore("userConfig", {
  state: () => {
    return {
      options: {} as Record<string, string>,
      taskList: [] as TaskListItem[],
      configLoaded: false,
      saveTimer: null as ReturnType<typeof setTimeout> | null,
    }
  },
  actions: {
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
      const mergedOptionMap: Record<string, Option> = {}

      // 收集所有选中任务的选项
      for (const taskId of taskIds) {
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

    buildDefaultTaskList() {
      const interfaceStore = useInterfaceStore()
      return interfaceStore.getTaskList.map((task) => ({ ...task, checked: true }))
    },

    async loadConfig() {
      const userConfig = await getUserConfig()

      this.options = this.buildDefaultOptions()
      if (userConfig.taskOptions) {
        Object.assign(this.options, userConfig.taskOptions)
      }

      this.taskList = this.buildDefaultTaskList()
      if (userConfig.taskOrder && userConfig.taskChecked) {
        const taskMap = new Map(this.taskList.map((task) => [task.id, task]))
        const reorderedTasks: TaskListItem[] = []
        for (const id of userConfig.taskOrder) {
          const task = taskMap.get(id)
          if (task) {
            reorderedTasks.push({
              id: task.id,
              name: task.name,
              order: task.order,
              checked: userConfig.taskChecked?.[id] || false,
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

      const config: UserConfig = {
        taskOrder,
        taskChecked,
        taskOptions: { ...this.options },
      }
      await saveUserConfig(config)
    },

    async resetConfig() {
      await resetUserConfig()
      this.options = this.buildDefaultOptions()
      this.taskList = this.buildDefaultTaskList()
    },
  },
})
