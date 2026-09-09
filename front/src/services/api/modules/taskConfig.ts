import type { ApiResponse } from "@/services/api/core/types"
import type { PersistedTaskConfig } from "@/types/taskConfigModel"
import { tryCatch } from "@/utils/tryCatch"
import { z } from "zod"

const taskOptionValueSchema = z.union([
  z.string(),
  z.array(z.string()),
  z.record(z.string(), z.string()),
])

const persistedTaskConfigSchema = z.object({
  taskIdentity: z.literal("name"),
  selectedPreset: z.string(),
  presets: z.record(
    z.string(),
    z.object({
      taskOrder: z.array(z.string()),
      taskChecked: z.record(z.string(), z.boolean()),
      taskOptions: z.record(z.string(), z.record(z.string(), taskOptionValueSchema)),
      preTasks: z.array(
        z.object({
          id: z.string(),
          command: z.string(),
          enabled: z.boolean(),
          timeout: z.number(),
        }),
      ),
    }),
  ),
})

const taskConfigResponseSchema = z.object({
  status: z.string().optional(),
  config: z.unknown().optional(),
  code: z.string().optional(),
  message: z.string().optional(),
})

type TaskConfigResponse = z.infer<typeof taskConfigResponseSchema>

export type TaskConfigLoadResult =
  | { ok: true; config: PersistedTaskConfig }
  | { ok: false; code: string; message: string }

function getRequestFailure(error: Error): TaskConfigLoadResult {
  return {
    ok: false,
    code: "task_config_request_failed",
    message: error.message || "加载任务配置失败",
  }
}

function getFailureResult(
  data: TaskConfigResponse | null,
  fallbackCode: string,
  fallbackMessage: string,
): TaskConfigLoadResult {
  const code = data?.code?.trim() || fallbackCode
  const message = data?.message?.trim() || fallbackMessage
  return { ok: false, code, message }
}

function parseSuccessfulTaskConfig(
  response: Response,
  data: TaskConfigResponse | null,
): PersistedTaskConfig | null {
  if (!response.ok || data?.status !== "success") {
    return null
  }

  const parsedConfig = persistedTaskConfigSchema.safeParse(data.config)
  return parsedConfig.success ? parsedConfig.data : null
}

function getFailureFallback(
  response: Response,
  data: TaskConfigResponse | null,
): { code: string; message: string } {
  if (!response.ok) {
    return { code: `task_config_http_${response.status}`, message: "加载任务配置失败" }
  }
  if (data?.status === "success") {
    return { code: "task_config_format_unsupported", message: "任务配置响应格式不受支持" }
  }
  return { code: "task_config_load_failed", message: "加载任务配置失败" }
}

export async function getTaskConfig(): Promise<TaskConfigLoadResult> {
  const [response, requestError] = await tryCatch(() =>
    fetch("/api/task-config", { method: "GET" }),
  )
  if (requestError || !response) {
    return getRequestFailure(requestError || new Error("加载任务配置失败"))
  }

  const [rawData, responseError] = await tryCatch(() => response.json())
  if (responseError) {
    return getRequestFailure(responseError)
  }

  const parsedResponse = taskConfigResponseSchema.safeParse(rawData)
  const data = parsedResponse.success ? parsedResponse.data : null
  const config = parseSuccessfulTaskConfig(response, data)

  if (config) {
    return { ok: true, config }
  }

  const fallback = getFailureFallback(response, data)
  return getFailureResult(data, fallback.code, fallback.message)
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
