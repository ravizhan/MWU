<template>
  <div class="space-y-4">
    <div
      v-if="status && !status.configured"
      class="rounded-lg border border-solid p-3 text-sm"
      style="border-color: var(--divider-color)"
    >
      {{ t("telemetry.settings.notConfigured") }}
    </div>
    <div
      v-else-if="status && !status.buildAllowed"
      class="rounded-lg border border-solid p-3 text-sm"
      style="border-color: var(--divider-color)"
    >
      {{ t("telemetry.settings.notBuildAllowed") }}
    </div>

    <template v-else-if="status">
      <NDivider />

      <div class="grid grid-cols-1 md:grid-cols-[160px_1fr] gap-2 md:gap-4 items-center py-2">
        <label class="text-sm font-medium md:text-right">
          {{ t("telemetry.settings.consent") }}
        </label>
        <div class="flex items-center gap-3">
          <NSwitch
            :value="status.consent === 'granted'"
            :loading="submitting"
            @update:value="handleConsentSwitch"
          />
          <span class="text-sm">
            {{
              status.consent === "granted"
                ? t("telemetry.settings.active")
                : t("telemetry.settings.inactive")
            }}
          </span>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-[160px_1fr] gap-2 md:gap-4 items-center py-2">
        <label class="text-sm font-medium md:text-right">
          {{ t("telemetry.settings.attachments") }}
        </label>
        <div class="flex items-center gap-3">
          <NSwitch
            :value="status.failureAttachments && status.consent === 'granted'"
            :disabled="status.consent !== 'granted'"
            :loading="submitting"
            @update:value="handleAttachmentsSwitch"
          />
          <span class="text-xs opacity-70">{{ t("telemetry.settings.attachmentsNote") }}</span>
        </div>
      </div>

      <div v-if="status.recipient" class="text-xs opacity-60">
        {{ t("telemetry.settings.recipient") }}: {{ status.recipient.project }} ·
        {{ status.recipient.host }}/{{ status.recipient.project_id }}
      </div>
    </template>

    <div v-else class="py-4 text-center text-sm opacity-50">
      {{ t("telemetry.settings.loading") }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useI18n } from "vue-i18n"
import { getTelemetryStatus, postTelemetryConsent, type TelemetryStatus } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"

/**
 * 遥测设置区：主开关 + 独立附件开关。
 * 源码/无 DSN 显示禁用原因，不伪造可发送状态。
 */
const { t } = useI18n()
const status = ref<TelemetryStatus | null>(null)
const submitting = ref(false)

onMounted(refresh)

async function refresh(): Promise<void> {
  status.value = await getTelemetryStatus().catch(() => null)
}

async function submitConsent(consent: "granted" | "denied", attachments: boolean): Promise<void> {
  if (status.value === null) {
    return
  }
  submitting.value = true
  const result = await postTelemetryConsent({
    configId: status.value.configId,
    consent,
    failureAttachments: consent === "granted" ? attachments : false,
  })
  submitting.value = false
  if (result.success) {
    status.value = result.status
    return
  }
  showGlobalMessage("error", result.message)
  if (result.staleTarget) {
    await refresh()
  }
}

function handleConsentSwitch(value: boolean): void {
  const current = status.value
  if (current === null) {
    return
  }
  void submitConsent(value ? "granted" : "denied", current.failureAttachments)
}

function handleAttachmentsSwitch(value: boolean): void {
  const current = status.value
  if (current === null || current.consent !== "granted") {
    return
  }
  void submitConsent("granted", value)
}
</script>
