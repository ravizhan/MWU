import type { TaskOptionsByTask } from "@/types/schedulerModel"

export const CUSTOM_PRESET_NAME = "__mwu_reserved_custom_preset__"

export interface TaskListItem {
  id: string
  name: string
  order: number
  checked?: boolean
}

export interface PreTaskCommand {
  id: string
  command: string
  enabled: boolean
  timeout: number
}

export interface TaskPresetSnapshot {
  taskOrder: string[]
  taskChecked: Record<string, boolean>
  taskOptions: TaskOptionsByTask
  preTasks: PreTaskCommand[]
}

export interface PersistedTaskConfig {
  taskIdentity: "name"
  selectedPreset: string
  presets: Record<string, TaskPresetSnapshot>
}
