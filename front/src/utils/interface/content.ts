import type { InterfaceModel } from "@/types/interfaceModel"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"
import { z } from "zod"

const textFilePattern = /^(?:\.\/)?(?:[^/]+[/])*[^/]+\.(?:md|markdown|txt|html?)$/i
const invalidPathNotified = new Set<string>()
const windowsDrivePattern = /^[A-Za-z]:/

const documentResponseSchema = z.object({
  status: z.string(),
  content: z.string(),
})

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

export function resolveInterfaceText(
  model: Partial<InterfaceModel> | null | undefined,
  locale: string,
  value?: string | null,
  fallback = "",
): string {
  if (value === null || value === undefined) {
    return fallback
  }

  if (value.startsWith("$")) {
    const resolved = lookupTranslation(model, locale, value.slice(1))
    return resolved === undefined ? fallback : resolved
  }

  return value
}

/**
 * 翻译键解析 — 与后端 InterfaceContentService.resolve_i18n 的 locale 链一致：
 * 原 locale → `-`→`_` 小写 → 仅 zh 用户 zh_cn/zh-CN 互通；嵌套路径与扁平键。
 */
function lookupTranslation(
  model: Partial<InterfaceModel> | null | undefined,
  locale: string,
  key: string,
): string | undefined {
  const translations = model?.translations
  if (!translations) {
    return undefined
  }
  // 与后端 _language_candidates 对齐：原 locale → `-`→`_` 小写；仅 zh locale
  // 追加 zh 互通。非 zh 用户不回退中文表，否则 en-US 会命中 zh-CN/zh_cn。
  const chain: string[] = []
  const normalized = locale.toLowerCase().replaceAll("-", "_")
  for (const candidate of [locale, normalized]) {
    if (candidate && !chain.includes(candidate)) {
      chain.push(candidate)
    }
  }
  if (normalized === "zh_cn") {
    for (const candidate of ["zh_cn", "zh-CN"]) {
      if (!chain.includes(candidate)) {
        chain.push(candidate)
      }
    }
  }
  for (const candidate of chain) {
    const table = translations[candidate]
    if (typeof table !== "object" || table === null) {
      continue
    }
    // 1) 嵌套路径：a.b.c
    let node: unknown = table
    for (const part of key.split(".")) {
      if (typeof node !== "object" || node === null || !(part in node)) {
        node = undefined
        break
      }
      node = Object.getOwnPropertyDescriptor(node, part)?.value
    }
    const nested = node
    if (typeof nested === "string") {
      return nested
    }
    // 2) 扁平键：整个 key 作为单键
    const flat = Object.getOwnPropertyDescriptor(table, key)?.value
    if (typeof flat === "string") {
      return flat
    }
  }
  return undefined
}

export function resolveInterfaceAssetUrl(
  model: Partial<InterfaceModel> | null | undefined,
  locale: string,
  value?: string | null,
): string | undefined {
  const resolvedValue = resolveInterfaceText(model, locale, value, "").trim()
  if (!resolvedValue) {
    return undefined
  }
  if (isExternalUrl(resolvedValue)) {
    return resolvedValue
  }
  return buildResourceUrl(resolvedValue)
}

export async function resolveInterfaceDocumentContent(
  model: Partial<InterfaceModel> | null | undefined,
  locale: string,
  value?: string | null,
): Promise<string> {
  const resolvedValue = resolveInterfaceText(model, locale, value, "")
  const trimmedValue = resolvedValue.trim()
  if (!trimmedValue) {
    return ""
  }

  // 后端白名单统一处理：翻译展开、HTTP(S) 拉取、根内文件读取。
  // 白名单含原始值与 zh-CN/en-US 解析值；非白名单来源 404 → 显示原值。
  const [response, fetchErr] = await tryCatch(() =>
    fetch("/api/interface/document", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: trimmedValue, locale }),
    }),
  )
  if (fetchErr || !response?.ok) {
    return resolvedValue
  }
  const [payload, payloadErr] = await tryCatch(() => response.json())
  const parsed = documentResponseSchema.safeParse(payload)
  if (payloadErr || !parsed.success || parsed.data.status !== "success") {
    return resolvedValue
  }
  return parsed.data.content
}
