import { defineConfig, mergeConfig } from "vitest/config"
import viteConfig from "./vite.config.ts"

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/tests/setup.ts"],
      css: true,
      restoreMocks: true,
      clearMocks: true,
      // windows-2025 runner 上文件内首个用例的冷启动（jsdom、MSW、Intl）偶尔超过默认 5s
      testTimeout: 20000,
    },
  }),
)
