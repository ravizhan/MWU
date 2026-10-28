<template>
  <div class="space-y-0">
    <div class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4">
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.runtime.timeout") }}
      </label>
      <div class="flex items-center gap-2">
        <NInputNumber
          :value="settings.runtime.timeout"
          class="w-32"
          :min="60"
          :max="3600"
          :step="30"
          @update:value="handleNumberChange('timeout', $event, 60, 3600)"
        />
        <span class="text-sm opacity-60">{{ t("settings.runtime.timeoutSuffix") }}</span>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4">
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.runtime.autoRetry") }}
      </label>
      <NSwitch
        :value="settings.runtime.autoRetry"
        :aria-label="t('settings.runtime.autoRetry')"
        style="justify-content: normal"
        @update:value="handleSettingChange('runtime', 'autoRetry', $event)"
      />
    </div>

    <div
      v-if="settings.runtime.autoRetry"
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.runtime.maxRetryCount") }}
      </label>
      <NInputNumber
        :value="settings.runtime.maxRetryCount"
        class="w-32"
        :min="1"
        :max="10"
        @update:value="handleNumberChange('maxRetryCount', $event, 1, 10)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { makeRuntimeNumberSchema } from "@/validation/settings"
import { useSettingsStore } from "@/stores"
import type { SettingsModel } from "@/types/settingsModel"

const { t } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

type EditableCategory = keyof SettingsModel
type MaybeNullForNumbers<T> = T extends number ? T | null : T
type RuntimeNumberKey = "timeout" | "maxRetryCount"

async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: MaybeNullForNumbers<SettingsModel[K][P]> | undefined,
) {
  if (value === null || value === undefined) return
  if (typeof value === "number" && Number.isNaN(value)) return
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  await settingsStore.updateSetting(category, key, value as SettingsModel[K][P])
}

async function handleNumberChange(
  key: RuntimeNumberKey,
  value: number | null,
  min: number,
  max: number,
) {
  if (value === null) return

  const parseResult = makeRuntimeNumberSchema(min, max).safeParse(value)
  if (!parseResult.success || parseResult.data === undefined) return

  await handleSettingChange("runtime", key, parseResult.data)
}
</script>
