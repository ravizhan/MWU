import { fileURLToPath, URL } from "node:url"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import tailwindcss from "@tailwindcss/vite"
import AutoImport from "unplugin-auto-import/vite"
import Components from "unplugin-vue-components/vite"
import { NaiveUiResolver } from "unplugin-vue-components/resolvers"

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  plugins: [
    vue(),
    tailwindcss(),
    AutoImport({
      imports: ["vue"],
    }),
    Components({
      resolvers: [NaiveUiResolver()],
    }),
  ],
  build: {
    outDir: "../page",
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: "naive-ui", test: /node_modules[\\/].*naive-ui/ },
            {
              name: "vendor-vue",
              test: /node_modules[\\/].*[\\/](vue|vue-router|pinia|vue-i18n|@vue)[\\/]/,
            },
            { name: "vendor-utils", test: /node_modules[\\/].*(zod|cron-converter)/ },
          ],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:5566",
        changeOrigin: true,
      },
    },
  },
})
