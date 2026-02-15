import {
  defineConfig,
  presetIcons,
  presetTypography,
  transformerDirectives,
  transformerVariantGroup,
} from "unocss"
import presetWind4 from "@unocss/preset-wind4"

export default defineConfig({
  presets: [
    presetIcons({
      collections: {
        mdi: () => import("@iconify-json/mdi").then((i) => i.default),
      },
    }),
    presetWind4(),
    presetTypography({
      cssExtend: {
        h1: {
          margin: "1em 0 .5em",
        },
        h2: {
          margin: ".75em 0 .5em",
        },
        h3: {
          margin: ".5em 0 .5em",
        },
        p: {
          margin: ".5em 0",
        },
      },
    }),
  ],
  transformers: [transformerDirectives(), transformerVariantGroup()],
  rules: [["shadow-3xl", { "box-shadow": "0 0 20px 10px rgba(0, 0, 0, 0.15)" }]],
})
