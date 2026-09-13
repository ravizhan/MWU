import type { ApiResponse } from "@/services/api/core/types"
import { showGlobalMessage } from "@/services/feedback/message"

export interface ResourceInfo {
  name: string
  label?: string | null
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
