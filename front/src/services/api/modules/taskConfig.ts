import type { ApiResponse } from "@/services/api/core/types"
import type { PersistedTaskConfig } from "@/types/taskConfigModel"

interface TaskConfigResponse {
  status: string
  config: PersistedTaskConfig
  message?: string
}

export function getTaskConfig(): Promise<PersistedTaskConfig> {
  return fetch("/api/task-config", { method: "GET" })
    .then((res) => res.json())
    .then((data: TaskConfigResponse) => {
      if (data.status !== "success") {
        throw new Error(data.message || "Failed to load task config")
      }
      return data.config
    })
}

export function saveTaskConfig(config: PersistedTaskConfig): Promise<boolean> {
  return fetch("/api/task-config", {
    method: "POST",
    body: JSON.stringify(config),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return true
      }
      console.error("Failed to save task config:", data.message)
      return false
    })
    .catch((error) => {
      console.error("Failed to save task config:", error)
      return false
    })
}

export function resetTaskConfig(): Promise<boolean> {
  return fetch("/api/task-config", {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return true
      }
      console.error("Failed to reset task config:", data.message)
      return false
    })
    .catch((error) => {
      console.error("Failed to reset task config:", error)
      return false
    })
}
