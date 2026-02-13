<template>
  <n-modal
    v-model:show="showModal"
    preset="dialog"
    :title="dialogTitle"
    :closable="!isUpdating"
    :mask-closable="!isUpdating"
    :close-on-esc="!isUpdating"
  >
    <div class="update-dialog-content">
      <div v-if="updateState === 'available'">
        <n-space vertical>
          <n-alert :title="version_info" type="info">
            <template #icon>
              <n-icon>
                <div class="i-mdi-update" />
              </n-icon>
            </template>
          </n-alert>

          <n-alert
            v-if="props.updateInfo?.error_code && props.updateInfo?.error_message"
            :title="t('settings.update.cdkError.title')"
            type="warning"
          >
            {{ getCdkErrorMessage(props.updateInfo.error_code, props.updateInfo.error_message) }}
          </n-alert>

          <n-alert v-if="!props.updateInfo?.download_url" type="warning">
            {{ t("settings.update.cdkPlaceholder") }}
          </n-alert>

          <n-card :title="t('settings.update.updateLog')" size="small">
            <div class="markdown-body max-h-100 overflow-y-auto" v-html="renderedMarkdown"></div>
          </n-card>
        </n-space>
      </div>

      <div v-else-if="isUpdating">
        <n-space vertical>
          <n-alert :type="updateState === 'failed' ? 'error' : 'info'">
            {{ statusMessage }}
          </n-alert>
          <n-progress
            v-if="updateState !== 'failed' && updateState !== 'success'"
            type="line"
            :percentage="100"
            :show-indicator="false"
            status="default"
            processing
          />
        </n-space>
      </div>

      <!-- Success state -->
      <div v-else-if="updateState === 'success'">
        <n-alert type="success">
          {{ t("settings.update.updateSuccess") }}
        </n-alert>
      </div>

      <!-- Failed state -->
      <div v-else-if="updateState === 'failed'">
        <n-alert type="error" :title="t('settings.update.updateFailed')">
          {{ statusMessage }}
        </n-alert>
      </div>
    </div>

    <template #action>
      <n-space>
        <n-button v-if="updateState === 'available'" @click="handleClose" :disabled="isUpdating">
          {{ t("settings.update.later") }}
        </n-button>
        <n-button
          v-if="updateState === 'available'"
          type="primary"
          @click="handleUpdate"
          :loading="isUpdating"
          :disabled="!canUpdate || isUpdating"
        >
          {{ canUpdate ? t("settings.update.updateNow") : t("settings.update.cdkPlaceholder") }}
        </n-button>
        <n-button v-if="updateState === 'failed'" @click="handleClose">
          {{ t("common.confirm") }}
        </n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from "vue"
import { useI18n } from "vue-i18n"
import { marked } from "marked"
import { performUpdateApi, getUpdateStatusApi, type UpdateInfo } from "../script/api"
import DOMPurify from "dompurify"

const { t } = useI18n()

interface Props {
  show: boolean
  updateInfo: UpdateInfo | null
}
const version_info = computed(() => {
  return (
    t("settings.update.currentVersion") +
    ": " +
    (props.updateInfo?.current_version || "-") +
    " | " +
    t("settings.update.latestVersion") +
    ": " +
    (props.updateInfo?.latest_version || "-")
  )
})
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: "update:show", value: boolean): void
}>()

const showModal = computed({
  get: () => props.show,
  set: (value) => emit("update:show", value),
})

const updateState = ref<"available" | "downloading" | "updating" | "success" | "failed">(
  "available",
)
const statusMessage = ref("")
const isUpdating = computed(
  () => updateState.value === "downloading" || updateState.value === "updating",
)

const dialogTitle = computed(() => {
  switch (updateState.value) {
    case "available":
      return t("settings.update.newVersion")
    case "downloading":
      return t("settings.update.downloading")
    case "updating":
      return t("settings.update.updating")
    case "success":
      return t("settings.update.updateSuccess")
    case "failed":
      return t("settings.update.updateFailed")
    default:
      return t("settings.update.newVersion")
  }
})

const renderedMarkdown = computed(() => {
  if (!props.updateInfo?.release_notes) {
    return "<p>" + t("panel.empty") + "</p>"
  }
  return DOMPurify.sanitize(marked.parse(props.updateInfo.release_notes) as string)
})

const getCdkErrorMessage = (errorCode: number, errorMsg: string): string => {
  // MirrorChyan error codes
  switch (errorCode) {
    case 7001:
      return t("settings.update.cdkError.expired")
    case 7002:
      return t("settings.update.cdkError.invalid")
    case 7003:
      return t("settings.update.cdkError.quotaExhausted")
    case 7004:
      return t("settings.update.cdkError.mismatched")
    case 7005:
      return t("settings.update.cdkError.blocked")
    default:
      return errorMsg
  }
}

const canUpdate = computed(() => {
  return props.updateInfo?.download_url && props.updateInfo?.download_url.length > 0
})

let pollTimer: number | null = null

const pollUpdateStatus = async () => {
  try {
    const status = await getUpdateStatusApi()
    statusMessage.value = status.message

    switch (status.status) {
      case "downloading":
        updateState.value = "downloading"
        break
      case "updating":
        updateState.value = "updating"
        break
      case "success":
        updateState.value = "success"
        stopPolling()
        // Wait for backend to restart and refresh page
        waitForBackendRestart()
        break
      case "failed":
        updateState.value = "failed"
        stopPolling()
        break
      case "idle":
        // If idle, continue polling as update might still be processing
        break
    }
  } catch (error) {
    console.error("Failed to poll update status:", error)
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = window.setInterval(pollUpdateStatus, 1000) // Poll every 1 second
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const waitForBackendRestart = async () => {
  statusMessage.value = t("settings.update.waitingRestart")
  let retries = 0
  const maxRetries = 60 // Wait up to 60 seconds

  const checkBackend = async () => {
    try {
      const response = await fetch("/api/settings", { method: "GET" })
      if (response.ok) {
        statusMessage.value = t("settings.update.restarting")
        // Backend is back online, refresh the page
        setTimeout(() => {
          window.location.reload()
        }, 1000)
        return true
      }
    } catch (error) {
      // Backend not ready yet
    }
    return false
  }

  const pollBackend = async () => {
    while (retries < maxRetries) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      retries++

      if (await checkBackend()) {
        return
      }
    }

    // If backend doesn't come back, just try to reload anyway
    window.location.reload()
  }

  pollBackend()
}

const handleUpdate = async () => {
  try {
    updateState.value = "downloading"
    statusMessage.value = t("settings.update.downloading")

    const result = await performUpdateApi()

    if (result.status === "success") {
      startPolling()
    } else {
      updateState.value = "failed"
      statusMessage.value = result.message || t("settings.update.updateFailed")
    }
  } catch (error) {
    updateState.value = "failed"
    statusMessage.value = String(error)
    console.error("Failed to perform update:", error)
  }
}

const handleClose = () => {
  showModal.value = false
  stopPolling()
}

watch(
  () => props.show,
  (newShow) => {
    if (newShow) {
      updateState.value = "available"
      statusMessage.value = ""
    } else {
      stopPolling()
    }
  },
)

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.update-dialog-content {
  min-width: 400px;
  max-width: 600px;
}

@media (max-width: 768px) {
  .update-dialog-content {
    min-width: 300px;
  }
}
</style>
