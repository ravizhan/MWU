export interface TelemetryStatus {
  status: string
  available: boolean
  blocked_reason: "no_dsn" | "dev_build" | "debug_resource" | null
  enabled: boolean
}

export function getTelemetryStatusApi(): Promise<TelemetryStatus> {
  return fetch("/api/telemetry/status", { method: "GET" }).then((res) => res.json())
}
