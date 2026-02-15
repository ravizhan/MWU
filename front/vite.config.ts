import UnoCSS from "unocss/vite"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

import AutoImport from "unplugin-auto-import/vite"
import { NaiveUiResolver } from "unplugin-vue-components/resolvers"
import Components from "unplugin-vue-components/vite"

export default defineConfig({
  plugins: [
    vue(),
    UnoCSS(),
    AutoImport({
      imports: ["vue"],
    }),
    Components({
      resolvers: [NaiveUiResolver()],
    }),
  ],
  build: {
    outDir: "../page",
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:55666",
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
