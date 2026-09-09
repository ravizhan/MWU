import { z } from "zod"

/** 提权重启结果。 */
export interface RestartElevatedResult {
  success: boolean
  message: string
}

const restartElevatedResponseSchema = z.object({
  status: z.string().optional(),
  message: z.string().optional(),
})

/** 请求以管理员权限重启当前程序（服务端构造命令，无客户端输入）。 */
export async function postRestartElevated(): Promise<RestartElevatedResult> {
  const response = await fetch("/api/privilege/restart-elevated", {
    method: "POST",
  })
  const parsed = restartElevatedResponseSchema.safeParse(await response.json().catch(() => null))
  const data = parsed.success ? parsed.data : null
  if (data?.status === "success") {
    return { success: true, message: data.message || "提权重启已提交" }
  }
  return { success: false, message: data?.message || "提权请求被拒绝" }
}
