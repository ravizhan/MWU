/**
 * 任务配置统一类型定义
 *
 * 用于统一主面板用户配置和计划任务的任务选择与配置逻辑。
 */

import type { TaskListItem } from "../stores/interface"

/**
 * 任务配置基础模型
 *
 * 包含任务列表、选中状态和选项配置三个核心要素。
 * - 主面板: 使用全部三个字段
 * - 计划任务: 仅使用 taskList 和 taskOptions
 */
export interface TaskConfig {
  /** 任务ID列表（有序，表示执行顺序） */
  taskList: string[]
  /** 任务选中状态映射，key为任务ID，value为是否选中 */
  taskChecked?: Record<string, boolean>
  /** 任务选项配置，key为选项名，value为选项值 */
  taskOptions: Record<string, string>
}

/**
 * 任务配置状态
 *
 * 用于管理任务选择和配置的响应式状态
 */
export interface TaskConfigState {
  /** 所有可选任务列表 */
  availableTasks: TaskListItem[]
  /** 选中的任务ID列表 */
  selectedTasks: string[]
  /** 当前正在配置的任务ID */
  currentConfigTaskId: string | null
  /** 任务选项配置 */
  taskOptions: Record<string, string>
}

/**
 * 任务配置操作
 */
export interface TaskConfigActions {
  /** 切换任务选中状态 */
  toggleTask: (taskId: string, checked: boolean) => void
  /** 设置当前配置任务 */
  setCurrentConfigTask: (taskId: string | null) => void
  /** 更新任务选项 */
  updateTaskOption: (key: string, value: string) => void
  /** 批量更新任务选项 */
  updateTaskOptions: (options: Record<string, string>) => void
  /** 获取选中的任务列表 */
  getSelectedTasks: () => string[]
  /** 获取任务配置 */
  getTaskConfig: () => TaskConfig
  /** 从任务配置初始化状态 */
  initFromConfig: (config: Partial<TaskConfig>) => void
  /** 重置状态 */
  reset: () => void
}

/**
 * 任务配置 composable 返回值
 */
export interface UseTaskConfigReturn {
  /** 响应式状态 */
  state: TaskConfigState
  /** 操作方法 */
  actions: TaskConfigActions
  /** 当前配置任务的选项列表 */
  currentTaskOptions: string[]
  /** 当前配置任务的名称 */
  currentTaskName: string
}
