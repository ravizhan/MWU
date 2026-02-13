import { computed, reactive } from "vue"
import { useInterfaceStore } from "../stores/interface"
import type { Option } from "../types/interface"
import type {
  TaskConfig,
  TaskConfigState,
  TaskConfigActions,
  UseTaskConfigReturn,
} from "../types/taskConfig"

/**
 * 根据选项定义生成默认值
 */
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

/**
 * 任务配置 composable
 *
 * 封装任务选择和配置的通用逻辑，供主面板和计划任务共用。
 *
 * @param initialConfig - 初始配置（可选）
 * @param options - 配置选项
 * @param options.enableChecked - 是否启用选中状态管理（主面板需要，计划任务不需要）
 */
export function useTaskConfig(
  initialConfig?: Partial<TaskConfig>,
  options?: { enableChecked?: boolean },
): UseTaskConfigReturn {
  const interfaceStore = useInterfaceStore()
  const enableChecked = options?.enableChecked ?? true

  // 响应式状态
  const state = reactive<TaskConfigState>({
    availableTasks: [],
    selectedTasks: [],
    currentConfigTaskId: null,
    taskOptions: {},
  })

  // 初始化可用任务列表
  state.availableTasks = interfaceStore.getTaskList

  /**
   * 规范化任务ID列表
   * 支持通过 ID 或 name 识别任务
   */
  function normalizeTaskList(taskList: string[]): string[] {
    if (!taskList?.length) return []
    const byId = new Map(state.availableTasks.map((task) => [task.id, task.id]))
    const byName = new Map(state.availableTasks.map((task) => [task.name, task.id]))
    return taskList
      .map((item) => byId.get(item) || byName.get(item) || item)
      .filter((item, index, self) => self.indexOf(item) === index)
  }

  /**
   * 获取完整的任务信息（包含 option）
   */
  function getFullTask(taskId: string) {
    return interfaceStore.interface?.task?.find((t) => t.entry === taskId)
  }

  /**
   * 获取任务所需的选项列表
   */
  function getOptionList(entry: string): Record<string, Option> {
    return interfaceStore.getOptionList(entry)
  }

  /**
   * 构建多个任务的合并选项
   */
  function buildOptionsForTasks(
    taskIds: string[],
    overrides: Record<string, string> = {},
  ): Record<string, string> {
    const mergedOptionMap: Record<string, Option> = {}

    // 收集所有选中任务的选项
    for (const taskId of taskIds) {
      const taskOptions = getOptionList(taskId)
      Object.assign(mergedOptionMap, taskOptions)
    }

    // 生成默认值
    const defaults = buildDefaultsFromOptionMap(mergedOptionMap)

    // 合并用户配置
    return {
      ...defaults,
      ...overrides,
    }
  }

  // 操作方法
  const actions: TaskConfigActions = {
    toggleTask(taskId: string, checked: boolean) {
      if (checked) {
        if (!state.selectedTasks.includes(taskId)) {
          state.selectedTasks.push(taskId)
        }
      } else {
        state.selectedTasks = state.selectedTasks.filter((id) => id !== taskId)
        // 如果取消选中的是当前配置任务，清除当前配置任务
        if (state.currentConfigTaskId === taskId) {
          state.currentConfigTaskId = null
        }
      }
    },

    setCurrentConfigTask(taskId: string | null) {
      state.currentConfigTaskId = taskId
    },

    updateTaskOption(key: string, value: string) {
      state.taskOptions[key] = value
    },

    updateTaskOptions(options: Record<string, string>) {
      Object.assign(state.taskOptions, options)
    },

    getSelectedTasks() {
      return [...state.selectedTasks]
    },

    getTaskConfig() {
      const config: TaskConfig = {
        taskList: [...state.selectedTasks],
        taskOptions: { ...state.taskOptions },
      }
      if (enableChecked) {
        const taskChecked: Record<string, boolean> = {}
        for (const task of state.availableTasks) {
          taskChecked[task.id] = state.selectedTasks.includes(task.id)
        }
        config.taskChecked = taskChecked
      }
      return config
    },

    initFromConfig(config: Partial<TaskConfig>) {
      // 初始化任务列表
      if (config.taskList) {
        state.selectedTasks = normalizeTaskList(config.taskList)
      }

      // 初始化选项（合并默认值）
      const defaults = buildOptionsForTasks(state.selectedTasks)
      state.taskOptions = { ...defaults }

      if (config.taskOptions) {
        Object.assign(state.taskOptions, config.taskOptions)
      }

      // 如果启用选中状态，从 taskChecked 初始化
      if (enableChecked && config.taskChecked) {
        state.selectedTasks = Object.entries(config.taskChecked)
          .filter(([, checked]) => checked)
          .map(([id]) => id)
      }
    },

    reset() {
      state.selectedTasks = []
      state.currentConfigTaskId = null
      state.taskOptions = {}
    },
  }

  // 计算属性：当前配置任务的选项列表
  const currentTaskOptions = computed(() => {
    if (!state.currentConfigTaskId) return []
    const task = getFullTask(state.currentConfigTaskId)
    return task?.option || []
  })

  // 计算属性：当前配置任务的名称
  const currentTaskName = computed(() => {
    if (!state.currentConfigTaskId) return ""
    const task = state.availableTasks.find((t) => t.id === state.currentConfigTaskId)
    return task?.name || ""
  })

  // 如果提供了初始配置，初始化状态
  if (initialConfig) {
    actions.initFromConfig(initialConfig)
  }

  return {
    state,
    actions,
    currentTaskOptions,
    currentTaskName,
  }
}

/**
 * 判断任务是否被选中
 */
export function isTaskSelected(state: TaskConfigState, taskId: string): boolean {
  return state.selectedTasks.includes(taskId)
}

/**
 * 获取任务的选中状态
 */
export function getTaskCheckedState(state: TaskConfigState, taskId: string): boolean {
  return state.selectedTasks.includes(taskId)
}
