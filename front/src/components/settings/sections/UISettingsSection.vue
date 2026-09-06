<template>
  <div class="space-y-0">
    <div class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4">
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.ui.language") }}
      </label>
      <NSelect
        :value="locale"
        class="w-full md:w-auto"
        :options="languageOptions"
        @update:value="handleLocaleChange"
      />
    </div>

    <div class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4">
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.ui.darkMode") }}
      </label>
      <NSelect
        :value="String(settings.ui.darkMode)"
        class="w-full md:w-auto"
        :options="darkModeOptions"
        @update:value="handleDarkModeChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { darkModeSchema, localeSchema } from "@/validation/settings"
import { useSettingsStore } from "@/stores"
import type { SettingsModel } from "@/types/settingsModel"

const { t, locale } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

const languageOptions = computed(() => [
  { label: t("settings.ui.languages.zhCN"), value: "zh-CN" },
  { label: t("settings.ui.languages.enUS"), value: "en-US" },
])

const darkModeOptions = computed(() => [
  { label: t("settings.ui.darkModeOptions.auto"), value: "auto" },
  { label: t("settings.ui.darkModeOptions.off"), value: "false" },
  { label: t("settings.ui.darkModeOptions.on"), value: "true" },
])

type EditableCategory = Exclude<keyof SettingsModel, "about">

async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: SettingsModel[K][P],
) {
  await settingsStore.updateSetting(category, key, value)
}

function handleLocaleChange(val: string | number | null) {
  if (typeof val !== "string") return
  const parseResult = localeSchema.safeParse(val)
  if (!parseResult.success) return
  const target = parseResult.data
  localStorage.setItem("locale", target)
  locale.value = target
  void handleSettingChange("ui", "language", target)
}

function handleDarkModeChange(val: string | number | null) {
  if (typeof val !== "string") return
  const parseResult = darkModeSchema.safeParse(val === "auto" ? "auto" : val === "true")
  if (!parseResult.success) return
  void handleSettingChange("ui", "darkMode", parseResult.data)
}
</script>
