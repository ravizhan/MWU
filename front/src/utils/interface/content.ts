import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"

const textFilePattern = /^(?:\.\/)?(?:[^/]+[/])*[^/]+\.(?:md|markdown|txt|html?)$/i
const invalidPathNotified = new Set<string>()
const windowsDrivePattern = /^[A-Za-z]:/

export function isExternalUrl(value: string): boolean {
  return /^(?:https?:)?\/\//i.test(value) || /^(?:data|blob):/i.test(value)
}

function normalizeRootRelativePath(path: string): string | undefined {
  const normalizedPath = path.trim().replace(/\\/g, "/")
  if (!normalizedPath) {
    notifyInvalidPath(path, "路径不能为空")
    return undefined
  }

  if (normalizedPath.startsWith("//")) {
    notifyInvalidPath(path, "不允许使用 UNC 或双斜杠开头路径")
    return undefined
  }

  if (normalizedPath.startsWith("/")) {
    notifyInvalidPath(path, "不允许使用绝对路径")
    return undefined
  }

  if (windowsDrivePattern.test(normalizedPath)) {
    notifyInvalidPath(path, "不允许使用 Windows 盘符路径")
    return undefined
  }

  if (normalizedPath.includes(":")) {
    notifyInvalidPath(path, "不允许包含冒号(:)")
    return undefined
  }

  const parts = normalizedPath.split("/")
  if (parts.some((part) => part.length === 0 || part === "." || part === "..")) {
    notifyInvalidPath(path, "禁止使用 . 或 .. 路径段")
    return undefined
  }

  return parts.join("/")
}

function notifyInvalidPath(path: string, reason: string): void {
  const key = `${path}::${reason}`
  if (invalidPathNotified.has(key)) {
    return
  }
  invalidPathNotified.add(key)
  showGlobalMessage("error", `资源路径不合法: ${path || "(空)"}，${reason}`)
}

export function buildResourceUrl(path: string): string | undefined {
  const normalizedPath = normalizeRootRelativePath(path)
  if (!normalizedPath) {
    return undefined
  }

  if (normalizedPath === "resource" || normalizedPath.startsWith("resource/")) {
    return `/${normalizedPath}`
  }

  return `/api/file?path=${encodeURIComponent(normalizedPath)}`
}

export function resolveInterfaceText(value?: string | null, fallback = ""): string {
  if (value === null || value === undefined) {
    return fallback
  }

  if (value.startsWith("$")) {
    return fallback
  }

  return value
}

export function resolveInterfaceAssetUrl(value?: string | null): string | undefined {
  const resolvedValue = resolveInterfaceText(value).trim()
  if (!resolvedValue) {
    return undefined
  }
  if (isExternalUrl(resolvedValue)) {
    return resolvedValue
  }
  return buildResourceUrl(resolvedValue)
}

export async function resolveInterfaceDocumentContent(value?: string | null): Promise<string> {
  const resolvedValue = resolveInterfaceText(value)
  const trimmedValue = resolvedValue.trim()
  if (!trimmedValue) {
    return ""
  }

  if (isExternalUrl(trimmedValue)) {
    return resolvedValue
  }

  if (!textFilePattern.test(trimmedValue)) {
    return resolvedValue
  }

  const url = buildResourceUrl(trimmedValue)
  if (!url) {
    return resolvedValue
  }

  const [response, fetchErr] = await tryCatch(() => fetch(url))
  if (fetchErr || !response?.ok) {
    return resolvedValue
  }

  const [text, textErr] = await tryCatch(() => response.text())
  if (textErr) {
    return resolvedValue
  }
  return text
}
