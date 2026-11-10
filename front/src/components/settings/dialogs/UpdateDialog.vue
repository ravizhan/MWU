<template>
  <NModal
    v-model:show="showDialog"
    preset="card"
    :title="dialogTitle"
    :closable="false"
    :mask-closable="true"
    style="max-width: min(480px, calc(100vw - 32px))"
  >
    <template v-if="updateState === 'available'">
      <NAlert type="info" class="mb-4">
        <template #icon>
          <NIcon size="24"><ArrowUpCircleOutline /></NIcon>
        </template>
        {{ version_info }}
        <div class="mt-1 text-xs">{{ packageInfo }}</div>
      </NAlert>
      <NCard size="small" :bordered="false" content-style="padding: 12px">
        <template #header>
          <span class="text-sm font-semibold">{{ t("settings.update.updateLog") }}</span>
        </template>
        <div class="markdown-body max-h-64 overflow-y-auto" v-html="renderedMarkdown" />
      </NCard>
    </template>

    <div v-else-if="isUpdating" class="space-y-3">
      <NAlert :type="updateState === 'failed' ? 'error' : 'info'">
        {{ statusMessage }}
      </NAlert>
      <NProgress
        v-if="updateState !== 'failed' && updateState !== 'success'"
        type="line"
        :percentage="0"
        :show-indicator="false"
        processing
      />
    </div>

    <NAlert v-else-if="updateState === 'success'" type="success">
      {{ t("settings.update.updateSuccess") }}
    </NAlert>

    <NAlert v-else-if="updateState === 'failed'" type="error">
      <div class="font-bold">{{ t("settings.update.updateFailed") }}</div>
      <div>{{ statusMessage }}</div>
    </NAlert>

    <template #action>
      <NSpace justify="end">
        <NButton
          v-if="updateState === 'available'"
          quaternary
          :disabled="isUpdating"
          @click="handleClose"
        >
          {{ t("settings.update.later") }}
        </NButton>
        <NButton
          v-if="updateState === 'available'"
          type="primary"
          :loading="isUpdating"
          :disabled="isUpdating"
          @click="handleUpdate"
        >
          {{ t("settings.update.updateNow") }}
        </NButton>
        <NButton v-if="updateState === 'failed'" type="primary" @click="handleClose">
          {{ t("common.confirm") }}
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from "vue"
import { useI18n } from "vue-i18n"
import { ArrowUpCircleOutline } from "@vicons/ionicons5"
import { marked } from "marked"
import {
  performUpdateApi,
  getUpdateStatusApi,
  isBackendReachable,
  type UpdateInfo,
} from "@/services/api"
import DOMPurify from "dompurify"
import { tryCatch } from "@/utils/tryCatch"

const { show, updateInfo } = defineProps<Props>()

const emit = defineEmits<{
  (e: "update:show", value: boolean): void
}>()

const { t } = useI18n()

interface Props {
  show: boolean
  updateInfo: UpdateInfo | null
}

const version_info = computed(() => {
  return (
    t("settings.update.currentVersion") +
    ": " +
    (updateInfo?.current_version || "-") +
    " | " +
    t("settings.update.latestVersion") +
    ": " +
    (updateInfo?.latest_version || "-")
  )
})

const showDialog = computed({
  get: () => show,
  set: (value) => emit("update:show", value),
})

const packageInfo = computed(() => {
  if (!updateInfo) return ""
  if (updateInfo.package_type === "resource") return t("settings.update.packageResource")
  if (updateInfo.package_type === "incremental") return t("settings.update.packageIncremental")
  if (
    updateInfo.client_version &&
    updateInfo.client_version !== updateInfo.current_client_version
  ) {
    return t("settings.update.packageFullWithClient", { version: updateInfo.client_version })
  }
  return t("settings.update.packageFull")
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
  const notes = updateInfo?.release_notes
  if (!notes) {
    return "<p>" + t("panel.empty") + "</p>"
  }
  const raw = marked.parse(notes)
  return typeof raw === "string" ? DOMPurify.sanitize(raw) : ""
})

let pollTimer: number | null = null

const pollUpdateStatus = async () => {
  const [status, err] = await tryCatch(() => getUpdateStatusApi())
  if (err) {
    console.error("Failed to poll update status:", err)
    return
  }

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
      waitForBackendRestart()
      break
    case "failed":
      updateState.value = "failed"
      stopPolling()
      break
    case "idle":
      break
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = window.setInterval(() => {
    void pollUpdateStatus()
  }, 1000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const waitForBackendRestart = () => {
  statusMessage.value = t("settings.update.waitingRestart")
  let retries = 0
  const maxRetries = 60

  const checkBackend = async () => {
    if (!(await isBackendReachable())) {
      return false
    }
    statusMessage.value = t("settings.update.restarting")
    setTimeout(() => {
      window.location.reload()
    }, 1000)
    return true
  }

  const pollBackend = async () => {
    while (retries < maxRetries) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      retries++

      if (await checkBackend()) {
        return
      }
    }

    window.location.reload()
  }

  void pollBackend()
}

const handleUpdate = async () => {
  updateState.value = "downloading"
  statusMessage.value = t("settings.update.downloading")

  const [result, err] = await tryCatch(() => performUpdateApi())
  if (err) {
    updateState.value = "failed"
    statusMessage.value = String(err)
    console.error("Failed to perform update:", err)
    return
  }

  if (result.status === "success") {
    startPolling()
    return
  }
  updateState.value = "failed"
  statusMessage.value = result.message || t("settings.update.updateFailed")
}

const handleClose = () => {
  showDialog.value = false
  stopPolling()
}

watch(
  () => show,
  (newShow) => {
    if (newShow) {
      updateState.value = "available"
      statusMessage.value = ""
      return
    }
    stopPolling()
  },
)

onUnmounted(() => {
  stopPolling()
})
</script>
