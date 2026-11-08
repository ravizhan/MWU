import type { InterfaceModel, OptionCase } from "@/types/interfaceModel"
import type { ApiResponse } from "@/services/api/core/types"

export function getInterface(): Promise<InterfaceModel> {
  return fetch("/api/interface", { method: "GET" }).then((res) => res.json())
}

interface ScanSelectRescanResponse extends ApiResponse {
  option_name: string
  cases: OptionCase[]
}

export function rescanScanSelectOption(optionName: string): Promise<OptionCase[]> {
  return fetch("/api/interface/scan-select/rescan", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ option_name: optionName }),
  })
    .then((res) => res.json())
    .then((data: ScanSelectRescanResponse) => {
      if (data.status !== "success" || !Array.isArray(data.cases)) {
        throw new Error(data.message || "重扫 scan_select 失败")
      }
      return data.cases
    })
}

export interface ProjectEntry {
  name: string
  /** Project-relative POSIX path. */
  path: string
  is_dir: boolean
}

interface ProjectEntriesResponse extends ApiResponse {
  entries?: ProjectEntry[]
}

/** List one level of the project directory ("" = project root). */
export function listProjectDir(path: string): Promise<ProjectEntry[]> {
  return fetch(`/api/file/list?${new URLSearchParams({ path })}`)
    .then((res) => res.json())
    .then((data: ProjectEntriesResponse) => {
      if (data.status !== "success" || !Array.isArray(data.entries)) {
        throw new Error(data.message || "读取目录失败")
      }
      return data.entries
    })
}
