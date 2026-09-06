import type {
  ManualStartPayload,
  ManualStartResult,
  SchedulerApiResponse,
} from "@/types/schedulerModel"
import { showGlobalMessage } from "@/services/feedback/message"

export function startTask(payload: ManualStartPayload): Promise<ManualStartResult> {
  return fetch("/api/start", {
    method: "POST",
    body: JSON.stringify(payload),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: SchedulerApiResponse): ManualStartResult => {
      if (data.status === "success") {
        return { accepted: true, runId: data.run_id ?? "" }
      }
      if (data.status === "conflict") {
        // Conflict is surfaced by the caller via StartConflictDialog, not a toast
        return { accepted: false, conflict: data.conflict }
      }
      return { accepted: false, error: data.message || "任务启动失败" }
    })
    .catch((error) => {
      console.error("Failed to start task:", error)
      return { accepted: false, error: "任务启动失败" }
    })
}

export function stopTask(): Promise<boolean> {
  return fetch("/api/stop", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: SchedulerApiResponse) => {
      if (data.status === "success") {
        showGlobalMessage("success", "正在中止任务，请稍后")
        return true
      }
      showGlobalMessage("error", data.message || "任务停止失败")
      return false
    })
    .catch((error) => {
      console.error("Failed to stop task:", error)
      showGlobalMessage("error", "任务停止失败")
      return false
    })
}
