<template>
  <div class="flex flex-col lg:flex-row gap-4 logs-view max-w-screen-xl mx-auto">
    <!-- Left: Monitoring (Live Preview) -->
    <div class="flex-1 min-h-0 flex items-center justify-center">
      <NCard
        :bordered="false"
        class="w-full"
        content-style="padding: 16px; display: flex; flex-direction: column"
      >
        <div class="flex flex-col gap-3 h-full">
          <LogsPreviewHeader
            :connected="connected"
            :fps="fps"
            :fps-options="fpsOptions"
            :streaming="streaming"
            @start="handleStartStream"
            @stop="handleStopStream"
            @update:fps="fps = $event"
          />
          <LogsPreviewStream
            ref="streamPreview"
            :connected="connected"
            :stream-url="streamUrl"
            :streaming="streaming"
          />
        </div>
      </NCard>
    </div>

    <!-- Right: Log Stream -->
    <NCard
      :bordered="false"
      class="h-full flex-1 min-h-0 logs-log-card"
      content-style="padding: 0; height: 100%; display: flex; flex-direction: column"
    >
      <div class="h-full flex flex-col gap-3 p-4">
        <LogsLogHeader
          :auto-scroll="autoScroll"
          :has-log="Boolean(log)"
          @copy="handleCopy"
          @download="handleDownload"
          @toggle-auto-scroll="autoScroll = !autoScroll"
        />
        <LogsLogPanel ref="logPanel" :log="log" class="flex-1 min-h-0" />
      </div>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { storeToRefs } from "pinia"
import { computed, nextTick, onMounted, onUnmounted, ref, useTemplateRef, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useDeviceConnectionStore, useIndexStore } from "@/stores"
import LogsLogHeader from "@/components/logs/LogsLogHeader.vue"
import LogsLogPanel from "@/components/logs/LogsLogPanel.vue"
import LogsPreviewHeader from "@/components/logs/LogsPreviewHeader.vue"
import LogsPreviewStream from "@/components/logs/LogsPreviewStream.vue"
import { downloadTextFile } from "@/utils/download"

type StreamPreviewRef = {
  clearStream: () => void
}
type LogPanelRef = {
  scrollToBottom: () => void
}

const { t } = useI18n()
const fpsOptions = computed(() => [
  { label: t("panel.preview-fps.fps15"), value: 15 },
  { label: t("panel.preview-fps.fps30"), value: 30 },
  { label: t("panel.preview-fps.fps60"), value: 60 },
])
const indexStore = useIndexStore()
const deviceStore = useDeviceConnectionStore()
const { Connected: connected, RunningLog: log } = storeToRefs(indexStore)
const streaming = ref(false)
const fps = ref(30)
const streamUrl = ref("")
const streamPreview = useTemplateRef<StreamPreviewRef>("streamPreview")
const logPanel = useTemplateRef<LogPanelRef>("logPanel")
const autoScroll = ref(true)

function handleStartStream() {
  if (!connected.value) {
    return
  }
  streaming.value = true
  streamUrl.value = `/api/stream/live?fps=${fps.value}`
}

function handleStopStream() {
  streamPreview.value?.clearStream()
  streaming.value = false
}

function handleCopy() {
  if (!log.value) return
  navigator.clipboard.writeText(log.value).catch(() => {})
}

function handleDownload() {
  if (!log.value) return
  downloadTextFile("mwu.log", log.value)
}

watch(connected, (newValue) => {
  if (!newValue && streaming.value) {
    handleStopStream()
  }
})

watch(
  log,
  () => {
    if (!autoScroll.value) return
    void nextTick(() => {
      logPanel.value?.scrollToBottom()
    })
  },
  { immediate: true },
)

onMounted(() => {
  deviceStore.init()
})

onUnmounted(() => {
  handleStopStream()
  deviceStore.cleanup()
})
</script>

<style scoped>
.logs-view {
  height: calc(100vh - 7rem - 1px);
}
@media (max-width: 1023px) {
  .logs-view {
    height: auto;
  }
  .logs-log-card {
    height: auto !important;
  }
}
</style>
