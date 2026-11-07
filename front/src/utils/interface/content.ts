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

type RootRelativePathCheck = { path: string } | { reason: string }

function checkRootRelativePath(path: string): RootRelativePathCheck {
  const normalizedPath = path.trim().replace(/\\/g, "/")
  if (!normalizedPath) {
    return { reason: "路径不能为空" }
  }

  if (normalizedPath.startsWith("//")) {
    return { reason: "不允许使用 UNC 或双斜杠开头路径" }
  }

  if (normalizedPath.startsWith("/")) {
    return { reason: "不允许使用绝对路径" }
  }

  if (windowsDrivePattern.test(normalizedPath)) {
    return { reason: "不允许使用 Windows 盘符路径" }
  }

  if (normalizedPath.includes(":")) {
    return { reason: "不允许包含冒号(:)" }
  }

  // "./a/b" 与 "a/b" 等价；".." 与空段（"a//b"）仍拒绝
  const parts = normalizedPath.split("/").filter((part) => part !== ".")
  if (parts.length === 0) {
    return { reason: "路径不能为空" }
  }
  if (parts.some((part) => part.length === 0 || part === "..")) {
    return { reason: "禁止使用 .. 或空路径段" }
  }

  return { path: parts.join("/") }
}

function notifyInvalidPath(path: string, reason: string): void {
  const key = `${path}::${reason}`
  if (invalidPathNotified.has(key)) {
    return
  }
  invalidPathNotified.add(key)
  showGlobalMessage("error", `资源路径不合法: ${path || "(空)"}，${reason}`)
}

function toResourceUrl(normalizedPath: string): string {
  if (normalizedPath === "resource" || normalizedPath.startsWith("resource/")) {
    return `/${normalizedPath}`
  }

  return `/api/file?path=${encodeURIComponent(normalizedPath)}`
}

export function buildResourceUrl(path: string): string | undefined {
  const check = checkRootRelativePath(path)
  if ("reason" in check) {
    notifyInvalidPath(path, check.reason)
    return undefined
  }
  return toResourceUrl(check.path)
}

async function fetchText(url: string): Promise<string | undefined> {
  const [response, fetchErr] = await tryCatch(() => fetch(url))
  if (fetchErr || !response?.ok) {
    return undefined
  }
  const [text, textErr] = await tryCatch(() => response.text())
  return textErr ? undefined : text
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

  return (await fetchText(url)) ?? resolvedValue
}

export type InterfaceLinkedContent =
  | { kind: "empty" }
  | { kind: "url"; text: string }
  | { kind: "file"; text: string; content: string }
  | { kind: "text"; text: string }

/**
 * 解析可为文件路径、URL 或纯文本的字段（如 license/contact）：先按项目根相对路径读取文件，
 * 读取不到再当纯文本。纯文本常含冒号等非法路径字符，因此这里不弹路径错误提示。
 */
export async function resolveInterfaceLinkedContent(
  value?: string | null,
): Promise<InterfaceLinkedContent> {
  const text = resolveInterfaceText(value).trim()
  if (!text) {
    return { kind: "empty" }
  }
  if (isExternalUrl(text)) {
    return { kind: "url", text }
  }

  const check = checkRootRelativePath(text)
  if ("reason" in check) {
    return { kind: "text", text }
  }
  const content = await fetchText(toResourceUrl(check.path))
  if (content === undefined) {
    return { kind: "text", text }
  }
  return { kind: "file", text, content }
}
