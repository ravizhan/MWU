import type { ApiResponse } from "@/services/api/core/types"
import { showGlobalMessage } from "@/services/feedback/message"

export interface PostResourceResult {
  success: boolean
  message: string
}

export interface ResourceInfo {
  name: string
  label?: string | null
  icon?: string | null
  controller?: string[] | null
}

interface ResourceResponse {
  status: string
  resource: ResourceInfo[]
}

export function getResource(controllerType?: string): Promise<ResourceInfo[]> {
  const query = controllerType ? `?controller_type=${encodeURIComponent(controllerType)}` : ""
  return fetch(`/api/resource${query}`, { method: "GET" })
    .then((res) => res.json())
    .then((data: ResourceResponse & ApiResponse) => {
      if (data.status !== "success") {
        showGlobalMessage("error", data.message || "获取资源失败")
        return []
      }
      return data.resource
    })
}

export function postResource(name: string): Promise<PostResourceResult> {
  return fetch("/api/resource?name=" + encodeURIComponent(name), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return { success: true, message: "资源添加成功" }
      }
      return { success: false, message: data.message || "资源设置失败" }
    })
    .catch((error) => {
      console.error("Failed to set resource:", error)
      return { success: false, message: "网络错误，请稍后重试" }
    })
}
