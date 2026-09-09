import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  buildResourceUrl,
  isExternalUrl,
  resolveInterfaceAssetUrl,
  resolveInterfaceDocumentContent,
  resolveInterfaceText,
} from "@/utils/interface/content"
import type { InterfaceModel } from "@/types/interfaceModel"

describe("isExternalUrl", () => {
  it("detects https:// URLs", () => {
    expect(isExternalUrl("https://example.com/file.md")).toBe(true)
  })

  it("detects protocol-relative URLs", () => {
    expect(isExternalUrl("//cdn.example.com/file.md")).toBe(true)
  })

  it("detects data: URLs", () => {
    expect(isExternalUrl("data:text/plain,hello")).toBe(true)
  })

  it("detects blob: URLs", () => {
    expect(isExternalUrl("blob:uuid-here")).toBe(true)
  })

  it("returns false for relative paths", () => {
    expect(isExternalUrl("resource/config.yaml")).toBe(false)
  })
})

describe("buildResourceUrl", () => {
  it("returns /resource/ path for resource/ prefix", () => {
    expect(buildResourceUrl("resource/config.yaml")).toBe("/resource/config.yaml")
  })

  it("returns /resource for exact resource path", () => {
    expect(buildResourceUrl("resource")).toBe("/resource")
  })

  it("returns /api/file for non-resource paths", () => {
    const result = buildResourceUrl("images/icon.png")
    expect(result).toBe("/api/file?path=images%2Ficon.png")
  })

  it("returns undefined for empty path", () => {
    expect(buildResourceUrl("  ")).toBeUndefined()
  })

  it("returns undefined for UNC paths", () => {
    expect(buildResourceUrl("//server/share")).toBeUndefined()
  })

  it("returns undefined for absolute paths", () => {
    expect(buildResourceUrl("/etc/passwd")).toBeUndefined()
  })

  it("returns undefined for Windows drive paths", () => {
    expect(buildResourceUrl("C:\\Users\\test")).toBeUndefined()
  })

  it("returns undefined for paths containing ..", () => {
    expect(buildResourceUrl("../escape")).toBeUndefined()
  })

  it("returns undefined for paths containing . segments", () => {
    expect(buildResourceUrl("./relative")).toBeUndefined()
  })

  it("returns undefined for paths with colon", () => {
    expect(buildResourceUrl("bad:path")).toBeUndefined()
  })

  it("normalizes backslashes to forward slashes", () => {
    expect(buildResourceUrl("resource\\tools\\cfg.yaml")).toBe("/resource/tools/cfg.yaml")
  })

  it("trims surrounding whitespace", () => {
    expect(buildResourceUrl("  resource/logo.png  ")).toBe("/resource/logo.png")
  })
})

describe("resolveInterfaceText", () => {
  it("returns the value when provided", () => {
    expect(resolveInterfaceText(null, "en", "hello")).toBe("hello")
  })

  it("returns fallback for null value", () => {
    expect(resolveInterfaceText(null, "en", null, "fallback")).toBe("fallback")
  })

  it("returns fallback for $ prefixed translation tokens", () => {
    expect(resolveInterfaceText(null, "en", "$dynamic", "fallback")).toBe("fallback")
  })

  it("resolves $key via nested translation path", () => {
    const model = {
      translations: {
        "zh-CN": { docs: { main: "主文档" } },
      },
      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    } as Partial<InterfaceModel>
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(resolveInterfaceText(model as InterfaceModel, "zh-CN", "$docs.main")).toBe("主文档")
  })

  it("resolves $key via flat single key", () => {
    const model = {
      translations: {
        "en-US": { "task.main.title": "Main Task" },
      },
      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    } as Partial<InterfaceModel>
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(resolveInterfaceText(model as InterfaceModel, "en-US", "$task.main.title")).toBe(
      "Main Task",
    )
  })

  it("falls back when translation key is missing in all locales", () => {
    const model = {
      translations: { "zh-CN": { other: "其他" } },
      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    } as Partial<InterfaceModel>
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    expect(resolveInterfaceText(model as InterfaceModel, "zh-CN", "$missing", "fb")).toBe("fb")
  })
})

describe("resolveInterfaceAssetUrl", () => {
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  const mockModel = {} as InterfaceModel

  it("returns external URL as-is", () => {
    const result = resolveInterfaceAssetUrl(mockModel, "en", "https://example.com/logo.png")
    expect(result).toBe("https://example.com/logo.png")
  })

  it("returns built resource URL for relative paths", () => {
    const result = resolveInterfaceAssetUrl(mockModel, "en", "resource/logo.png")
    expect(result).toBe("/resource/logo.png")
  })

  it("returns undefined for null/missing values", () => {
    expect(resolveInterfaceAssetUrl(mockModel, "en", null)).toBeUndefined()
  })

  it("trims whitespace before checking", () => {
    expect(resolveInterfaceAssetUrl(mockModel, "en", "  ")).toBeUndefined()
  })
})

describe("resolveInterfaceDocumentContent", () => {
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  const mockModel = {} as InterfaceModel

  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("returns empty string for empty value", async () => {
    const result = await resolveInterfaceDocumentContent(mockModel, "en", "")
    expect(result).toBe("")
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it("posts to the document API with source and locale", async () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: "success", content: "# Hello" }),
    } as Response)

    const result = await resolveInterfaceDocumentContent(mockModel, "zh-CN", "readme.md")
    expect(result).toBe("# Hello")
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/interface/document", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "readme.md", locale: "zh-CN" }),
    })
  })

  it("returns resolved value when API responds 404 (unknown source)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
      { ok: false, status: 404 } as Response,
    )

    const result = await resolveInterfaceDocumentContent(
      mockModel,
      "en",
      "https://example.com/doc.md",
    )
    expect(result).toBe("https://example.com/doc.md")
    // 404 响应体不解析，直接回退原值
  })

  it("returns resolved value when API returns failed status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: "failed", message: "未知文档来源" }),
      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    } as Response)

    const result = await resolveInterfaceDocumentContent(mockModel, "en", "script.py")
    expect(result).toBe("script.py")
  })

  it("returns original value when network fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"))

    const result = await resolveInterfaceDocumentContent(mockModel, "en", "doc.txt")
    expect(result).toBe("doc.txt")
  })

  it("resolves $translation keys before posting", async () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const translatedModel = {
      translations: {
        "zh-CN": { docs: { main: "指南" } },
      },
    } as Partial<InterfaceModel>
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: "success", content: "内容" }),
    } as Response)

    const result = await resolveInterfaceDocumentContent(
      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
      translatedModel as InterfaceModel,
      "zh-CN",
      "$docs.main",
    )
    expect(result).toBe("内容")
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/interface/document", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "指南", locale: "zh-CN" }),
    })
  })

  it("trims whitespace before checking", async () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: "success", content: "trimmed content" }),
    } as Response)

    const result = await resolveInterfaceDocumentContent(mockModel, "en", "  readme.md  ")
    expect(result).toBe("trimmed content")
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/interface/document", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: "readme.md", locale: "en" }),
    })
  })
})
