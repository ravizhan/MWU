import type { ApiResponse } from "@/services/api/core/types"

export interface DownloadedFile {
  blob: Blob
  filename: string
}

function attachmentName(res: Response, fallback: string): string {
  const match = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") ?? "")
  return match?.[1] ?? fallback
}

async function readFailure(res: Response, fallback: string): Promise<Error> {
  const data: ApiResponse | null = await res.json().catch(() => null)
  return new Error(data?.message || fallback)
}

/** Fetch an attachment endpoint; non-2xx responses reject with the backend message. */
export async function fetchAttachment(url: string, fallbackName: string): Promise<DownloadedFile> {
  const res = await fetch(url)
  if (!res.ok) {
    throw await readFailure(res, `HTTP ${res.status}`)
  }
  return { blob: await res.blob(), filename: attachmentName(res, fallbackName) }
}
