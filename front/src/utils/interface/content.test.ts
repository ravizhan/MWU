import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  buildResourceUrl,
  isExternalUrl,
  resolveInterfaceAssetUrl,
  resolveInterfaceDocumentContent,
  resolveInterfaceLinkedContent,
  resolveInterfaceText,
  setInterfaceTranslations,
} from "@/utils/interface/content"

describe("isExternalUrl", () => {
  it.each([
    "https://example.com/file.md",
    "//cdn.example.com/file.md",
    "data:text/plain,x",
    "blob:uuid",
  ])("accepts %s", (url) => {
    expect(isExternalUrl(url)).toBe(true)
  })

  it("rejects relative paths", () => {
    expect(isExternalUrl("resource/config.yaml")).toBe(false)
  })
})

describe("buildResourceUrl", () => {
  it("maps resource paths to the /resource mount", () => {
    expect(buildResourceUrl("resource/config.yaml")).toBe("/resource/config.yaml")
    expect(buildResourceUrl("resource")).toBe("/resource")
  })

  it("normalizes whitespace and backslashes", () => {
    expect(buildResourceUrl("  resource/logo.png  ")).toBe("/resource/logo.png")
    expect(buildResourceUrl("resource\\tools\\cfg.yaml")).toBe("/resource/tools/cfg.yaml")
  })

  it("maps other paths through /api/file", () => {
    expect(buildResourceUrl("images/icon.png")).toBe("/api/file?path=images%2Ficon.png")
  })

  it("drops current-directory segments", () => {
    expect(buildResourceUrl("./tasks/images/a.png")).toBe("/api/file?path=tasks%2Fimages%2Fa.png")
    expect(buildResourceUrl("./resource/logo.png")).toBe("/resource/logo.png")
  })

  it.each([
    ["empty", "  "],
    ["UNC", "//server/share"],
    ["absolute", "/etc/passwd"],
    ["Windows drive", "C:\\Users\\test"],
    ["parent segment", "../escape"],
    ["only dot segments", "./."],
    ["empty segment", "a//b"],
    ["colon", "bad:path"],
  ])("rejects %s paths", (_label, path) => {
    expect(buildResourceUrl(path)).toBeUndefined()
  })
})

describe("resolveInterfaceText", () => {
  beforeEach(() => {
    setInterfaceTranslations(undefined, "zh-CN")
  })

  it("returns the value when provided", () => {
    expect(resolveInterfaceText("hello")).toBe("hello")
  })

  it("returns fallback for missing values", () => {
    expect(resolveInterfaceText(null, "fallback")).toBe("fallback")
  })

  it("resolves a flat translation key", () => {
    setInterfaceTranslations({ "zh-CN": { dynamic: "动态" } }, "zh-CN")
    expect(resolveInterfaceText("$dynamic", "fallback")).toBe("动态")
  })

  it("resolves a dotted translation key", () => {
    setInterfaceTranslations({ "zh-CN": { nested: { label: "标签" } } }, "zh-CN")
    expect(resolveInterfaceText("$nested.label", "fallback")).toBe("标签")
  })

  it("returns fallback for a missing translation key", () => {
    setInterfaceTranslations({ "zh-CN": { dynamic: "动态" } }, "zh-CN")
    expect(resolveInterfaceText("$missing", "fallback")).toBe("fallback")
  })

  it("returns fallback when no translations are set", () => {
    expect(resolveInterfaceText("$dynamic", "fallback")).toBe("fallback")
  })
})

describe("resolveInterfaceAssetUrl", () => {
  it("returns external URLs as-is", () => {
    expect(resolveInterfaceAssetUrl("https://example.com/logo.png")).toBe(
      "https://example.com/logo.png",
    )
  })

  it("builds resource URLs for relative paths", () => {
    expect(resolveInterfaceAssetUrl("resource/logo.png")).toBe("/resource/logo.png")
  })

  it("returns undefined for missing or blank values", () => {
    expect(resolveInterfaceAssetUrl(null)).toBeUndefined()
    expect(resolveInterfaceAssetUrl("  ")).toBeUndefined()
  })
})

describe("resolveInterfaceDocumentContent", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("returns empty string for empty value", async () => {
    expect(await resolveInterfaceDocumentContent("")).toBe("")
  })

  it("returns external URLs and non-text files without fetching", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")

    expect(await resolveInterfaceDocumentContent("https://example.com/doc.md")).toBe(
      "https://example.com/doc.md",
    )
    expect(await resolveInterfaceDocumentContent("script.py")).toBe("script.py")
    expect(await resolveInterfaceDocumentContent("../secret.md")).toBe("../secret.md")
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it.each([".md", ".markdown", ".txt", ".html", ".htm"])(
    "fetches text files with %s extension",
    async (ext) => {
      // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
        ok: true,
        text: () => Promise.resolve("content"),
      } as Response)

      expect(await resolveInterfaceDocumentContent(`  doc${ext}  `)).toBe("content")
    },
  )

  it("returns the original value when the fetch fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"))

    expect(await resolveInterfaceDocumentContent("doc.txt")).toBe("doc.txt")
  })

  it("returns the original value when the response is not ok", async () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      text: () => Promise.resolve(""),
    } as Response)

    expect(await resolveInterfaceDocumentContent("broken.md")).toBe("broken.md")
  })
})

describe("resolveInterfaceLinkedContent", () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("returns URLs without fetching", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
    expect(await resolveInterfaceLinkedContent("https://example.com/LICENSE")).toEqual({
      kind: "url",
      text: "https://example.com/LICENSE",
    })
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it("reads extensionless files relative to the project root", async () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      text: () => Promise.resolve("# MIT"),
    } as Response)

    expect(await resolveInterfaceLinkedContent("./LICENSE")).toEqual({
      kind: "file",
      text: "./LICENSE",
      content: "# MIT",
    })
    expect(fetchSpy).toHaveBeenCalledWith("/api/file?path=LICENSE")
  })

  it("falls back to text when the file is missing", async () => {
    // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({ ok: false } as Response)

    expect(await resolveInterfaceLinkedContent("MIT")).toEqual({ kind: "text", text: "MIT" })
  })

  it("treats invalid paths as text without fetching", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
    expect(await resolveInterfaceLinkedContent("QQ群: 123456789")).toEqual({
      kind: "text",
      text: "QQ群: 123456789",
    })
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
