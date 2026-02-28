<template>
  <div class="col-name">{{ t("panel.preview") }}</div>
  <div>
    <n-card hoverable>
      <n-flex class="pb-[12px]" justify="space-around" :size="[5, 0]">
        <n-select
          v-model:value="fps"
          :placeholder="t('panel.selectFPS')"
          :options="[
            { label: '15 FPS', value: 15 },
            { label: '30 FPS', value: 30 },
            { label: '60 FPS', value: 60 },
          ]"
          class="w-40"
        />
        <n-button secondary type="info" :disabled="streaming" @click="handleStartStream">
          <template #icon>
            <n-icon><div class="i-mdi-play-circle-outline"></div></n-icon>
          </template>
          {{ t("common.start") }}
        </n-button>
        <n-button secondary type="warning" :disabled="!streaming" @click="handleStopStream">
          <template #icon>
            <n-icon><div class="i-mdi-pause-circle-outline"></div></n-icon>
          </template>
          {{ t("common.pause") }}
        </n-button>
      </n-flex>
      <div ref="streamContainer" class="flex justify-center items-center h-50 bg-gray-1/5">
        <template v-if="connected">
          <n-image v-if="streaming" :src="streamUrl" class="max-w-full h-auto" />
          <n-empty v-else :description="t('panel.previewHint')" />
        </template>
        <n-empty v-else :description="t('panel.connectFirstHint')" />
      </div>
    </n-card>
  </div>
  <div class="col-name">{{ t("panel.log") }}</div>
  <div>
    <n-card hoverable>
      <n-button id="btn" block tertiary type="info" :data-clipboard-text="log">
        {{ t("common.copy") }}
      </n-button>
      <n-log class="log" ref="logInstRef" :log="log" trim :rows="11" />
    </n-card>
  </div>
</template>
<script setup lang="ts">
import type { LogInst } from "naive-ui"
import Clipboard from "clipboard"
import { useMessage } from "naive-ui"
import { useI18n } from "vue-i18n"
import { ref, onMounted, onUnmounted, watchEffect, nextTick, watch } from "vue"
import { useIndexStore } from "../stores"
import { storeToRefs } from "pinia"

const { t } = useI18n()
const message = useMessage()
const indexStore = useIndexStore()
const { RunningLog: log, Connected: connected } = storeToRefs(indexStore)
const streaming = ref(false)
const logInstRef = ref<LogInst | null>(null)
const btnCopy = new Clipboard("#btn")
btnCopy.on("success", () => {
  message.success(t("panel.copySuccess"))
})

onMounted(() => {
  watchEffect(() => {
    if (log.value) {
      nextTick(() => {
        logInstRef.value?.scrollTo({ position: "bottom", silent: true })
      })
    }
  })
})

onUnmounted(() => {
  handleStopStream()
})

const fps = ref(30)
const streamUrl = ref("")
const streamContainer = ref<HTMLElement | null>(null)

const handleStartStream = () => {
  if (!connected.value) {
    message.error(t("panel.connectFirstHint"))
    return
  }
  streaming.value = true
  streamUrl.value = `/api/stream/live?fps=${fps.value}`
}

const handleStopStream = () => {
  const img = streamContainer.value?.querySelector("img")
  if (img) {
    img.src = ""
  }
  streaming.value = false
}

watch(connected, (newVal) => {
  if (!newVal && streaming.value) {
    handleStopStream()
  }
})
</script>
<style scoped>
.log {
  margin-top: 0.5rem;
  border: 1px solid rgba(140, 140, 140, 0.2);
  border-radius: 8px;
  padding: 0.5rem;
  transition: border-color 0.3s ease;
}
</style>
