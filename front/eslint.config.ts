import pluginEslintComments from "@eslint-community/eslint-plugin-eslint-comments"
import pluginVueI18n from "@intlify/eslint-plugin-vue-i18n"
import skipFormatting from "@vue/eslint-config-prettier/skip-formatting"
import { defineConfigWithVueTs, vueTsConfigs } from "@vue/eslint-config-typescript"
import pluginOxlint from "eslint-plugin-oxlint"
import { configs as pnpmConfigs } from "eslint-plugin-pnpm"
import pluginVue from "eslint-plugin-vue"

export default defineConfigWithVueTs(
  { ignores: ["**/dist/**", "**/coverage/**", "**/node_modules/**"] },

  pluginVue.configs["flat/essential"],
  vueTsConfigs.recommendedTypeChecked,

  // Disable type-checked rules for JSON files (jsonc-eslint-parser lacks type info)
  {
    files: ["**/*.json", "**/*.json5", "**/*.jsonc"],
    ...(Array.isArray(vueTsConfigs.disableTypeChecked)
      ? vueTsConfigs.disableTypeChecked[0]
      : vueTsConfigs.disableTypeChecked),
  },

  // Vue component rules
  {
    files: ["src/**/*.vue"],
    rules: {
      "vue/multi-word-component-names": ["error", { ignores: ["App", "Layout"] }],
      "vue/component-name-in-template-casing": ["error", "PascalCase"],
      "vue/prop-name-casing": ["error", "camelCase"],
      "vue/custom-event-name-casing": ["error", "kebab-case"],
      "vue/no-unused-properties": ["error", { groups: ["props", "data", "computed", "methods"] }],
      "vue/no-unused-refs": "error",
      "vue/define-props-destructuring": "error",
      "vue/prefer-use-template-ref": "error",
      "vue/max-template-depth": ["error", { maxDepth: 8 }],
    },
  },

  // TypeScript style guide
  {
    files: ["src/**/*.{ts,vue}"],
    rules: {
      complexity: ["warn", { max: 10 }],
      "no-nested-ternary": "error",
      "@typescript-eslint/consistent-type-assertions": ["error", { assertionStyle: "never" }],
      "no-restricted-syntax": [
        "error",
        { selector: "TSEnumDeclaration", message: "Use literal unions instead of enums." },
        {
          selector: "IfStatement > :not(IfStatement).alternate",
          message: "Avoid else. Use early returns.",
        },
        { selector: "TryStatement", message: "Use tryCatch() instead of try/catch." },
      ],
    },
  },

  // i18n rules
  {
    files: ["src/**/*.vue"],
    plugins: { "@intlify/vue-i18n": pluginVueI18n },
    rules: {
      "@intlify/vue-i18n/no-raw-text": ["error", {/* config */}],
    },
  },

  // Prevent disabling i18n rules
  {
    files: ["src/**/*.vue"],
    plugins: { "@eslint-community/eslint-comments": pluginEslintComments },
    rules: {
      "@eslint-community/eslint-comments/no-restricted-disable": ["error", "@intlify/vue-i18n/*"],
    },
  },

  // Disable rules handled by Oxlint
  ...pluginOxlint.buildFromOxlintConfigFile("./.oxlintrc.json"),

  // pnpm catalog enforcement
  ...pnpmConfigs.recommended,

  skipFormatting,
)
