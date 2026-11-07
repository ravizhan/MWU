<template>
  <div class="space-y-6">
    <!-- Channels + test -->
    <section class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex min-w-0 items-center gap-2">
          <NIcon size="18" aria-hidden="true">
            <NotificationsOutline />
          </NIcon>
          <h3 class="text-sm font-semibold">{{ t("settings.notification.sections.channels") }}</h3>
        </div>
        <NButton
          type="primary"
          size="small"
          :disabled="isTestNotificationDisabled"
          :title="t('settings.notification.test')"
          :aria-label="t('settings.notification.test')"
          @click="testNotification"
        >
          <template #icon>
            <NIcon size="18" aria-hidden="true"><NotificationsOutline /></NIcon>
          </template>
          {{ t("settings.notification.test") }}
        </NButton>
      </div>

      <div class="flex flex-wrap gap-2">
        <NCheckbox
          class="rounded-lg px-3 py-2 transition-colors"
          :class="{ 'bg-primary/5': settings.notification.systemNotification }"
          :checked="settings.notification.systemNotification"
          @update:checked="handleSettingChange('notification', 'systemNotification', $event)"
        >
          <span class="flex items-center gap-2">
            <NIcon size="18" aria-hidden="true">
              <DesktopOutline />
            </NIcon>
            <span class="text-sm">{{ t("settings.notification.system") }}</span>
          </span>
        </NCheckbox>

        <NCheckbox
          class="rounded-lg px-3 py-2 transition-colors"
          :class="{ 'bg-primary/5': settings.notification.browserNotification }"
          :checked="settings.notification.browserNotification"
          @update:checked="handleBrowserNotificationChange"
        >
          <span class="flex items-center gap-2">
            <NIcon size="18" aria-hidden="true">
              <GlobeOutline />
            </NIcon>
            <span class="text-sm">{{ t("settings.notification.browser") }}</span>
          </span>
        </NCheckbox>

        <NCheckbox
          class="rounded-lg px-3 py-2 transition-colors"
          :class="{ 'bg-primary/5': settings.notification.externalNotification }"
          :checked="settings.notification.externalNotification"
          @update:checked="handleSettingChange('notification', 'externalNotification', $event)"
        >
          <span class="flex items-center gap-2">
            <NIcon size="18" aria-hidden="true">
              <LinkOutline />
            </NIcon>
            <span class="text-sm">{{ t("settings.notification.external") }}</span>
          </span>
        </NCheckbox>
      </div>
    </section>

    <!-- External channels (collapses when off) -->
    <section v-if="settings.notification.externalNotification" class="space-y-4 pt-5">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <NIcon size="18" aria-hidden="true">
            <LinkOutline />
          </NIcon>
          <h3 class="text-sm font-semibold">
            {{ t("settings.notification.sections.external") }}
          </h3>
        </div>
        <NDropdown trigger="click" :options="addChannelOptions" @select="addChannel">
          <NButton size="small">
            <template #icon>
              <NIcon><AddOutline /></NIcon>
            </template>
            {{ t("settings.notification.addChannel") }}
          </NButton>
        </NDropdown>
      </div>

      <p v-if="!settings.notification.channels.length" class="text-sm opacity-60">
        {{ t("settings.notification.noChannels") }}
      </p>
      <NotificationChannelCard
        v-for="channel in settings.notification.channels"
        :key="channel.id"
        :channel="channel"
        :definition="definitions[channel.type]"
        @update="updateChannel"
        @delete="removeChannel(channel.id)"
      />
    </section>

    <!-- Trigger timing -->
    <section class="space-y-1 pt-5">
      <div class="mb-3 flex items-center gap-2">
        <NBadge dot>
          <NIcon size="18" aria-hidden="true">
            <NotificationsOutline />
          </NIcon>
        </NBadge>
        <h3 class="text-sm font-semibold">{{ t("settings.notification.sections.triggers") }}</h3>
      </div>

      <div class="grid grid-cols-1 items-center gap-2 py-3 md:grid-cols-[1fr_auto] md:gap-4">
        <label class="text-sm" for="notify-on-complete">
          {{ t("settings.notification.onComplete") }}
        </label>
        <NSwitch
          id="notify-on-complete"
          :value="settings.notification.notifyOnComplete"
          :aria-label="t('settings.notification.onComplete')"
          @update:value="handleSettingChange('notification', 'notifyOnComplete', $event)"
        />
      </div>

      <div class="grid grid-cols-1 items-center gap-2 py-3 md:grid-cols-[1fr_auto] md:gap-4">
        <label class="text-sm" for="notify-on-error">
          {{ t("settings.notification.onError") }}
        </label>
        <NSwitch
          id="notify-on-error"
          :value="settings.notification.notifyOnError"
          :aria-label="t('settings.notification.onError')"
          @update:value="handleSettingChange('notification', 'notifyOnError', $event)"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import {
  AddOutline,
  DesktopOutline,
  GlobeOutline,
  LinkOutline,
  NotificationsOutline,
} from "@vicons/ionicons5"
import NotificationChannelCard from "@/components/settings/notification/NotificationChannelCard.vue"
import {
  CHANNEL_TYPES,
  channelDefinitions,
  findChannelType,
} from "@/components/settings/notification/channels"
import { testNotificationApi } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useSettingsStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"
import type { NotificationChannel, SettingsModel } from "@/types/settingsModel"

const { t } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

const definitions = computed(() => channelDefinitions(t))

const addChannelOptions = computed(() =>
  CHANNEL_TYPES.map((type) => ({ key: type, label: definitions.value[type].label })),
)

const isTestNotificationDisabled = computed(() => {
  const notification = settings.value.notification
  const hasEnabledChannel =
    notification.systemNotification ||
    notification.browserNotification ||
    notification.externalNotification

  if (!hasEnabledChannel) {
    return true
  }

  return (
    notification.externalNotification &&
    !notification.channels.some((channel) => channel.enabled) &&
    !notification.systemNotification &&
    !notification.browserNotification
  )
})

type EditableCategory = Exclude<keyof SettingsModel, "about">

async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: SettingsModel[K][P],
) {
  await settingsStore.updateSetting(category, key, value)
}

function saveChannels(channels: NotificationChannel[]) {
  void handleSettingChange("notification", "channels", channels)
}

function addChannel(key: string | number) {
  const type = findChannelType(key)
  if (!type) return
  const params = Object.fromEntries(
    definitions.value[type].fields.map((field) => [field.key, field.default]),
  )
  saveChannels([
    ...settings.value.notification.channels,
    { id: crypto.randomUUID(), type, enabled: true, params },
  ])
}

function updateChannel(updated: NotificationChannel) {
  saveChannels(
    settings.value.notification.channels.map((channel) =>
      channel.id === updated.id ? updated : channel,
    ),
  )
}

function removeChannel(id: string) {
  saveChannels(settings.value.notification.channels.filter((channel) => channel.id !== id))
}

async function handleBrowserNotificationChange(enabled: boolean) {
  if (!enabled) {
    await handleSettingChange("notification", "browserNotification", false)
    return
  }

  if (typeof Notification === "undefined") {
    showGlobalMessage("error", t("settings.notification.browserUnsupported"))
    return
  }

  let permission = Notification.permission
  if (permission !== "granted") {
    permission = await Notification.requestPermission()
  }

  if (permission !== "granted") {
    showGlobalMessage("warning", t("settings.notification.browserPermissionDenied"))
    return
  }

  await handleSettingChange("notification", "browserNotification", true)
}

async function testNotification() {
  showGlobalMessage("info", t("settings.notification.testSending"))
  const [result, err] = await tryCatch(() => testNotificationApi())
  if (err) {
    showGlobalMessage("error", t("settings.notification.testError"))
    console.error(err)
    return
  }
  if (result.status !== "success") {
    showGlobalMessage("error", t("settings.notification.testResult", { message: result.message }))
  }
}
</script>
