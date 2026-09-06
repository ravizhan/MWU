<template>
  <NModal
    v-model:show="telemetryConsentVisible"
    :mask-closable="false"
    :close-on-esc="false"
    preset="card"
    :title="t('telemetry.consent.title')"
    class="max-w-xl"
  >
    <div class="space-y-3 text-sm">
      <p>{{ t("telemetry.consent.purpose") }}</p>

      <div
        v-if="status?.recipient"
        class="rounded-lg border border-solid p-3"
        style="border-color: var(--divider-color)"
      >
        <div class="font-medium">{{ t("telemetry.consent.recipient") }}</div>
        <div class="text-xs opacity-70 mt-1">
          {{ status.recipient.project }} · {{ status.recipient.host }}/{{
            status.recipient.project_id
          }}
        </div>
      </div>

      <div class="text-xs opacity-70">
        {{ t("telemetry.consent.scope") }}
      </div>

      <div class="rounded-lg border border-solid p-3" style="border-color: var(--divider-color)">
        <div class="flex items-start gap-3">
          <NCheckbox
            class="shrink-0"
            :checked="failureAttachments"
            @update:checked="failureAttachments = $event"
          />
          <div class="min-w-0">
            <div class="font-medium">{{ t("telemetry.consent.attachments") }}</div>
            <div class="text-xs opacity-70 mt-1">
              {{ t("telemetry.consent.attachmentsNote") }}
            </div>
          </div>
        </div>
      </div>

      <div class="text-xs opacity-60">
        {{ t("telemetry.consent.withdraw") }}
      </div>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <NButton size="small" @click="submit('denied')">{{ t("telemetry.consent.deny") }}</NButton>
        <NButton size="small" type="primary" :loading="submitting" @click="submit('granted')">
          {{ t("telemetry.consent.grant") }}
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { telemetryConsentVisible } from "@/services/telemetry/consentState"
import { useI18n } from "vue-i18n"
import { getTelemetryStatus, postTelemetryConsent, type TelemetryStatus } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"

/**
 * 遥测授权弹窗：仅首次（consent=unknown 且可发送构建）显示。
 * 关闭弹窗不是同意；当前页面会话内不反复打扰。
 * 附件开关默认关闭，与主开关分别授权。
 */
const { t } = useI18n()
const submitting = ref(false)
const status = ref<TelemetryStatus | null>(null)
const failureAttachments = ref(false)

const shouldShow = computed(() => {
  const current = status.value
  return (
    current !== null && current.configured && current.buildAllowed && current.consent === "unknown"
  )
})

onMounted(async () => {
  const fetched = await getTelemetryStatus().catch(() => null)
  status.value = fetched
  if (fetched !== null && shouldShow.value) {
    telemetryConsentVisible.value = true
  }
})

async function submit(consent: "granted" | "denied"): Promise<void> {
  if (status.value === null) {
    return
  }
  submitting.value = true
  const result = await postTelemetryConsent({
    configId: status.value.configId,
    consent,
    failureAttachments: consent === "granted" ? failureAttachments.value : false,
  })
  submitting.value = false
  if (result.success) {
    status.value = result.status
    telemetryConsentVisible.value = false
    showGlobalMessage("success", result.message)
    return
  }
  if (result.staleTarget) {
    // 目标已变化：刷新状态后重新弹窗确认新目标
    const refreshed = await getTelemetryStatus().catch(() => null)
    if (refreshed !== null) {
      status.value = refreshed
      failureAttachments.value = false
    }
    showGlobalMessage("error", result.message)
    return
  }
  showGlobalMessage("error", result.message)
}
</script>
