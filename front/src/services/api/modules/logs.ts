import { fetchAttachment, type DownloadedFile } from "@/services/api/core/attachment"

/** Download the backend log bundle (zip of MWU/MaaFramework logs and debug images). */
export function exportLogsApi(): Promise<DownloadedFile> {
  return fetchAttachment("/api/logs/export", "mwu-logs.zip")
}
