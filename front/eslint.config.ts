import pluginEslintComments from "@eslint-community/eslint-plugin-eslint-comments"
import pluginVueI18n from "@intlify/eslint-plugin-vue-i18n"
import skipFormatting from "@vue/eslint-config-prettier/skip-formatting"
import { vueTsConfigs, withVueTs } from "@vue/eslint-config-typescript"
import pluginOxlint from "eslint-plugin-oxlint"
import { configs as pnpmConfigs } from "eslint-plugin-pnpm"
import pluginVue from "eslint-plugin-vue"

const OXLINT_CONFIG = "./.oxlintrc.json"
const I18N_SETTINGS = {
  "vue-i18n": {
    localeDir: "./src/app/i18n/messages/*.json",
    messageSyntaxVersion: "^11.0.0",
  },
}
// Oxlint owns every rule it implements. Its type-aware pass (tsgolint) does not read `.vue`
// scripts, so ESLint keeps type-aware rules for SFCs and drops them only for plain TS files.
// withVueTs() relocates type-aware rules and keeps only `files`, so scope with `files`, not `ignores`.
const oxlintSyntaxRules = pluginOxlint.buildFromOxlintConfigFile(OXLINT_CONFIG, {
  typeAware: false,
})
const oxlintTypeAwareRules = pluginOxlint
  .buildFromOxlintConfigFile(OXLINT_CONFIG, { typeAware: true })
  .filter((config) => config.rules !== undefined)
  .map((config) => ({ ...config, files: ["**/*.ts"] }))

export default withVueTs(
  { ignores: ["auto-imports.d.ts", "components.d.ts", "env.d.ts"] },

  pluginVue.configs["flat/recommended"],
  vueTsConfigs.recommendedTypeChecked,
  ...pluginVueI18n.configs.base,

  // The vue-i18n base config parses JSON/YAML too; they carry no type information.
  {
    name: "mwu/data-files",
    files: ["**/*.{json,json5,jsonc,yaml,yml}"],
    extends: [vueTsConfigs.disableTypeChecked],
  },

  {
    name: "mwu/vue",
    files: ["src/**/*.vue"],
    rules: {
      "vue/block-lang": ["error", { script: { lang: "ts" } }],
      "vue/component-api-style": ["error", ["script-setup"]],
      "vue/multi-word-component-names": ["error", { ignores: ["App", "Layout"] }],
      "vue/component-name-in-template-casing": ["error", "PascalCase"],
      "vue/custom-event-name-casing": ["error", "kebab-case"],
      "vue/define-macros-order": "error",
      "vue/no-unused-emit-declarations": "error",
      "vue/no-unused-properties": [
        "error",
        { groups: ["props", "data", "computed", "methods", "setup"] },
      ],
      "vue/no-unused-refs": "error",
      "vue/no-ref-object-reactivity-loss": "error",
      "vue/no-useless-mustaches": "error",
      "vue/no-useless-v-bind": "error",
      "vue/prefer-use-template-ref": "error",
      "vue/max-template-depth": ["error", { maxDepth: 8 }],
      // Optional props get their defaults from props destructuring.
      "vue/require-default-prop": "off",
      // Every v-html renders markdown that went through DOMPurify.sanitize.
      "vue/no-v-html": "off",

      "@typescript-eslint/no-deprecated": "error",
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "@typescript-eslint/no-unnecessary-type-conversion": "error",
    },
  },

  {
    name: "mwu/style",
    files: ["src/**/*.{ts,vue}"],
    rules: {
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

  {
    name: "mwu/i18n",
    files: ["src/**/*.{ts,vue}"],
    settings: I18N_SETTINGS,
    plugins: { "@eslint-community/eslint-comments": pluginEslintComments },
    rules: {
      "@intlify/vue-i18n/no-raw-text": "error",
      "@intlify/vue-i18n/no-missing-keys": "error",
      "@intlify/vue-i18n/no-dynamic-keys": "error",
      "@intlify/vue-i18n/no-deprecated-tc": "error",
      "@intlify/vue-i18n/no-v-html": "error",
      "@eslint-community/eslint-comments/no-restricted-disable": ["error", "@intlify/vue-i18n/*"],
    },
  },
  {
    name: "mwu/i18n-messages",
    files: ["src/app/i18n/messages/*.json"],
    settings: I18N_SETTINGS,
    rules: {
      "@intlify/vue-i18n/no-missing-keys-in-other-locales": "error",
      "@intlify/vue-i18n/no-unused-keys": ["error", { src: "./src", extensions: [".ts", ".vue"] }],
      "@intlify/vue-i18n/no-duplicate-keys-in-locale": "error",
      "@intlify/vue-i18n/no-html-messages": "error",
      "@intlify/vue-i18n/valid-message-syntax": "error",
    },
  },

  ...oxlintSyntaxRules,
  ...oxlintTypeAwareRules,

  ...pnpmConfigs.recommended,

  skipFormatting,
)
