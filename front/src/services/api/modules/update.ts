import type { ApiResponse } from "@/services/api/core/types"
import { tryCatch } from "@/utils/tryCatch"

export interface UpdateInfo {
  latest_version: string
  current_version: string
  is_update_available: boolean
  release_notes: string
  download_source: "mirrorchyan" | "github"
  /** full: MWU + resources; resource: resources only; incremental: MirrorChyan diff package */
  package_type: "full" | "resource" | "incremental"
  /** MWU version used by the target release, null when unknown */
  client_version: string | null
  /** MWU version recorded by the local install manifest, null when unknown */
  current_client_version: string | null
  download_url: string
  file_hash: string
  file_name: string
}

export interface UpdateCheckResponse {
  status: string
  update_info?: UpdateInfo
  message?: string
}

export interface UpdateStatusResponse {
  status: "idle" | "downloading" | "updating" | "success" | "failed"
  message: string
}

export function checkUpdateApi(): Promise<UpdateCheckResponse> {
  return fetch("/api/update/check", { method: "GET" }).then((res) => res.json())
}

export function performUpdateApi(): Promise<ApiResponse> {
  return fetch("/api/update", { method: "GET" }).then((res) => res.json())
}

export function getUpdateStatusApi(): Promise<UpdateStatusResponse> {
  return fetch("/api/update/status", { method: "GET" }).then((res) => res.json())
}

/** Whether the backend answers again, used to detect the restart after an update. */
export async function isBackendReachable(): Promise<boolean> {
  const [response, err] = await tryCatch(() => fetch("/api/settings", { method: "GET" }))
  return err === null && response.ok
}
