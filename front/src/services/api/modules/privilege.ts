import type { ApiResponse } from "@/services/api/core/types"

/** 提权重启结果。 */
export interface RestartElevatedResult {
  success: boolean
  message: string
}

/** 请求以管理员权限重启当前程序（服务端构造命令，无客户端输入）。 */
export async function postRestartElevated(): Promise<RestartElevatedResult> {
  const response = await fetch("/api/privilege/restart-elevated", {
    method: "POST",
  })
  const payload = (await response.json()) as ApiResponse
  if (payload.status === "success") {
    return { success: true, message: payload.message || "提权重启已提交" }
  }
  return { success: false, message: payload.message || "提权请求被拒绝" }
}
