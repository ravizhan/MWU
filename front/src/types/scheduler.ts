export type TriggerType = "cron" | "date" | "interval"

export type ExecutionStatus = "running" | "success" | "failed" | "stopped"

export interface CronTriggerConfig {
  type: "cron"
  cron: string
}

export interface DateTriggerConfig {
  type: "date"
  run_date: string // ISO 8601 datetime string
}

export interface IntervalTriggerConfig {
  type: "interval"
  weeks?: number
  days?: number
  hours?: number
  minutes?: number
  seconds?: number
  start_date?: string // ISO 8601 datetime string
  end_date?: string // ISO 8601 datetime string
}

export type TriggerConfig = CronTriggerConfig | DateTriggerConfig | IntervalTriggerConfig

export interface TaskExecutionPayload {
  task_list: string[]
  task_options: Record<string, string>
}

export interface ScheduledTask extends TaskExecutionPayload {
  id: string
  name: string
  description?: string
  enabled: boolean
  trigger_type: TriggerType
  trigger_config: TriggerConfig
  next_run_time?: string // ISO 8601 datetime string
  created_at: string // ISO 8601 datetime string
  updated_at: string // ISO 8601 datetime string
}

export interface ScheduledTaskCreate extends TaskExecutionPayload {
  name: string
  description?: string
  enabled: boolean
  trigger_type: TriggerType
  trigger_config: TriggerConfig
}

export interface ScheduledTaskUpdate {
  name?: string
  description?: string
  enabled?: boolean
  trigger_type?: TriggerType
  trigger_config?: TriggerConfig
  task_list?: string[]
  task_options?: Record<string, string>
}

export interface TaskExecution {
  id: string
  task_id: string
  task_name: string
  started_at: string // ISO 8601 datetime string
  finished_at?: string // ISO 8601 datetime string
  status: ExecutionStatus
  error_message?: string
}

export interface SchedulerApiResponse {
  status: "success" | "failed"
  message?: string
  tasks?: ScheduledTask[]
  task?: ScheduledTask
  executions?: TaskExecution[]
}
