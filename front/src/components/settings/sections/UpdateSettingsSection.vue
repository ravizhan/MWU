<template>
  <div class="space-y-0">
    <div class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4">
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.auto") }}
      </label>
      <div class="flex items-center justify-between gap-2">
        <NSwitch
          :value="settings.update.autoUpdate"
          :aria-label="t('settings.update.auto')"
          @update:value="handleSettingChange('update', 'autoUpdate', $event)"
        />
        <NButton type="primary" size="small" :loading="checkingUpdate" @click="checkForUpdate">
          <template #icon>
            <NIcon size="18"><ArrowUpCircleOutline /></NIcon>
          </template>
          {{ t("settings.update.check") }}
        </NButton>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4">
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.channel") }}
      </label>
      <NSelect
        :value="settings.update.updateChannel"
        class="w-full md:w-auto"
        :options="updateChannelOptions"
        @update:value="handleUpdateChannelChange"
      />
    </div>

    <div class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4">
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.proxy") }}
      </label>
      <NInput
        :value="settings.update.proxy"
        class="w-full"
        placeholder="http://127.0.0.1:7890"
        @update:value="handleSettingChange('update', 'proxy', $event)"
      />
    </div>

    <div
      v-if="hasMirrorchyan"
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.mirrorchyanCdk") }}
      </label>
      <div class="flex gap-2">
        <NInput
          type="password"
          :value="settings.update.mirrorchyanCdk"
          class="flex-1"
          :placeholder="t('settings.update.mirrorchyanCdkPlaceholder')"
          @update:value="handleSettingChange('update', 'mirrorchyanCdk', $event)"
        />
        <NButton secondary tag="a" href="https://mirrorchyan.com" target="_blank">
          {{ t("settings.update.mirrorchyanCdkHint") }}
        </NButton>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useI18n } from "vue-i18n"
import { ArrowUpCircleOutline } from "@vicons/ionicons5"
import { checkUpdateApi, type UpdateInfo } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { updateChannelSchema } from "@/validation/settings"
import { useInterfaceStore, useSettingsStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"
import type { SettingsModel } from "@/types/settingsModel"

const emit = defineEmits<{
  (e: "show-update", updateInfo: UpdateInfo): void
}>()

function isUpdateChannel(value: string): value is SettingsModel["update"]["updateChannel"] {
  return updateChannelSchema.safeParse(value).success
}

const { t } = useI18n()
const settingsStore = useSettingsStore()
const interfaceStore = useInterfaceStore()
const settings = computed(() => settingsStore.settings)
const hasMirrorchyan = computed(() => Boolean(interfaceStore.interface.mirrorchyan_rid))
const checkingUpdate = ref(false)

const updateChannelOptions = computed(() => [
  { label: t("settings.update.channelOptions.stable"), value: "stable" },
  { label: t("settings.update.channelOptions.beta"), value: "beta" },
])

type EditableCategory = Exclude<keyof SettingsModel, "about">
type MaybeNullForNumbers<T> = T extends number ? T | null : T
async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: MaybeNullForNumbers<SettingsModel[K][P]> | undefined,
) {
  if (value === null || value === undefined) return
  // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
  await settingsStore.updateSetting(category, key, value as SettingsModel[K][P])
}

function handleUpdateChannelChange(value: string | number | null) {
  if (typeof value !== "string" || !isUpdateChannel(value)) return
  void handleSettingChange("update", "updateChannel", value)
}

async function checkForUpdate() {
  checkingUpdate.value = true
  const [result, err] = await tryCatch(() => checkUpdateApi())
  if (err) {
    showGlobalMessage("error", t("settings.update.failed"))
    checkingUpdate.value = false
    return
  }

  if (result.status === "success" && result.update_info?.is_update_available) {
    emit("show-update", result.update_info)
    checkingUpdate.value = false
    return
  }
  showGlobalMessage("success", t("settings.update.latest"))
  checkingUpdate.value = false
}
</script>
