import type { ApiResponse } from "@/services/api/core/types"
import { tryCatch } from "@/utils/tryCatch"

export async function confirmFocusModal(id: string): Promise<boolean> {
  const [success, error] = await tryCatch(async () => {
    const response = await fetch(`/api/focus/${encodeURIComponent(id)}/confirm`, {
      method: "POST",
    })
    if (!response.ok) return false
    const data: ApiResponse = await response.json()
    return data.status === "success"
  })
  return error ? false : success
}
