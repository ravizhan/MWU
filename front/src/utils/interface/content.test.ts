import { afterEach, describe, expect, it, vi } from "vitest"
import {
  buildResourceUrl,
  isExternalUrl,
  resolveInterfaceAssetUrl,
  resolveInterfaceDocumentContent,
  resolveInterfaceText,
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

  it.each([
    ["empty", "  "],
    ["UNC", "//server/share"],
    ["absolute", "/etc/passwd"],
    ["Windows drive", "C:\\Users\\test"],
    ["parent segment", "../escape"],
    ["dot segment", "./relative"],
    ["colon", "bad:path"],
  ])("rejects %s paths", (_label, path) => {
    expect(buildResourceUrl(path)).toBeUndefined()
  })
})

describe("resolveInterfaceText", () => {
  it("returns the value when provided", () => {
    expect(resolveInterfaceText("hello")).toBe("hello")
  })

  it("returns fallback for missing values", () => {
    expect(resolveInterfaceText(null, "fallback")).toBe("fallback")
  })

  it("returns fallback for $ prefixed translation tokens", () => {
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
