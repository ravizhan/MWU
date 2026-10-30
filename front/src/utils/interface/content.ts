import { shallowRef } from "vue"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"

const textFilePattern = /^(?:\.\/)?(?:[^/]+[/])*[^/]+\.(?:md|markdown|txt|html?)$/i
const invalidPathNotified = new Set<string>()
const windowsDrivePattern = /^[A-Za-z]:/
const activeTranslations = shallowRef<Record<string, unknown>>({})

export function setInterfaceTranslations(
  translations: Record<string, Record<string, unknown>> | undefined,
  locale: string,
): void {
  const localeKey = locale.replace("-", "_").toLowerCase()
  const entry = translations
    ? Object.entries(translations).find(
        ([key]) => key.replace("-", "_").toLowerCase() === localeKey,
      )
    : undefined
  activeTranslations.value = entry ? entry[1] : {}
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null
}

function lookupTranslation(key: string): string | undefined {
  const translations = activeTranslations.value
  const flatValue = translations[key]
  if (typeof flatValue === "string") {
    return flatValue
  }

  let current: unknown = translations
  for (const segment of key.split(".")) {
    if (!isRecord(current)) {
      return undefined
    }
    current = current[segment]
  }
  return typeof current === "string" ? current : undefined
}

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
    return lookupTranslation(value.slice(1)) ?? fallback
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
