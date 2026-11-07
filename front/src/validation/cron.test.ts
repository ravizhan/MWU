import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

import { cronExpressionSchema } from "./cron"

interface CorpusCase {
  name: string
  input: string
  canonical: string | null
  valid: boolean
}

const corpusPath = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../tests/fixtures/validation_contract.json",
)
const corpus: CorpusCase[] = JSON.parse(readFileSync(corpusPath, "utf-8"))

describe("cronExpressionSchema", () => {
  for (const c of corpus) {
    it(`corpus: ${c.name}`, () => {
      const result = cronExpressionSchema.safeParse(c.input)
      expect(result.success).toBe(c.valid)
      expect(result.data ?? null).toBe(c.canonical)
    })
  }
})
