<template>
  <div class="flex items-center justify-between shrink-0">
    <h2 class="text-base font-semibold flex items-center gap-2">
      <NIcon size="20" style="color: var(--primary-color)">
        <DesktopOutline />
      </NIcon>
      {{ t("panel.preview") }}
    </h2>
    <div class="flex gap-2">
      <NButton
        quaternary
        circle
        size="small"
        :type="tapEnabled ? 'primary' : 'default'"
        :disabled="!streaming"
        :aria-label="t('panel.previewTap')"
        :title="t('panel.previewTap')"
        @click="emit('toggle-tap')"
      >
        <template #icon>
          <NIcon size="18"><HandLeftOutline /></NIcon>
        </template>
      </NButton>
      <NButton
        quaternary
        circle
        size="small"
        :disabled="!connected || capturing"
        :aria-label="t('panel.screenshotSave')"
        :title="t('panel.screenshotSave')"
        @click="emit('save-screenshot')"
      >
        <template #icon>
          <NIcon size="18"><CameraOutline /></NIcon>
        </template>
      </NButton>
      <NButton
        quaternary
        circle
        size="small"
        :disabled="!connected || capturing"
        :aria-label="t('panel.screenshotCopy')"
        :title="t('panel.screenshotCopy')"
        @click="emit('copy-screenshot')"
      >
        <template #icon>
          <NIcon size="18"><CopyOutline /></NIcon>
        </template>
      </NButton>
      <NSelect
        :value="fps"
        :options="fpsOptions"
        size="small"
        style="width: 110px"
        @update:value="handleFpsUpdate"
      />
      <NButton
        type="primary"
        size="small"
        circle
        :disabled="streaming || !connected"
        @click="emit('start')"
      >
        <template #icon>
          <NIcon size="20"><PlayCircleOutline /></NIcon>
        </template>
      </NButton>
      <NButton type="warning" size="small" circle :disabled="!streaming" @click="emit('stop')">
        <template #icon>
          <NIcon size="20"><PauseCircleOutline /></NIcon>
        </template>
      </NButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import {
  CameraOutline,
  CopyOutline,
  DesktopOutline,
  HandLeftOutline,
  PauseCircleOutline,
  PlayCircleOutline,
} from "@vicons/ionicons5"

const { capturing, connected, fps, fpsOptions, streaming, tapEnabled } = defineProps<{
  capturing: boolean
  connected: boolean
  fps: number
  fpsOptions: Array<{ label: string; value: number }>
  streaming: boolean
  tapEnabled: boolean
}>()

const emit = defineEmits<{
  (e: "copy-screenshot"): void
  (e: "save-screenshot"): void
  (e: "start"): void
  (e: "stop"): void
  (e: "toggle-tap"): void
  (e: "update:fps", value: number): void
}>()

const { t } = useI18n()

function handleFpsUpdate(value: number | null) {
  if (value === null) return
  emit("update:fps", value)
}
</script>
