<template>
  <NEl
    tag="div"
    class="aspect-video w-full flex items-center justify-center rounded-xl overflow-hidden"
    style="background: var(--card-color)"
  >
    <template v-if="connected">
      <img
        v-if="streaming"
        ref="streamImage"
        :src="streamUrl"
        class="h-full w-full object-contain"
        :class="{ 'cursor-crosshair': tapEnabled }"
        alt="live preview"
        @click="handleClick"
      />
      <div v-else class="text-center opacity-50">
        <NIcon size="30" class="mx-auto mb-2" style="color: var(--text-color-3)">
          <VideocamOffOutline />
        </NIcon>
        <p>{{ t("panel.previewHint") }}</p>
      </div>
    </template>
    <div v-else class="text-center opacity-50">
      <NIcon size="30" class="mx-auto mb-2" style="color: var(--text-color-3)">
        <LinkOutline />
      </NIcon>
      <p>{{ t("panel.connectFirstHint") }}</p>
    </div>
  </NEl>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { LinkOutline, VideocamOffOutline } from "@vicons/ionicons5"
import { useTemplateRef } from "vue"
import { mapContainedPoint } from "@/utils/containedPoint"

const { connected, streaming, streamUrl, tapEnabled } = defineProps<{
  connected: boolean
  streaming: boolean
  streamUrl: string
  tapEnabled: boolean
}>()

const emit = defineEmits<{
  (e: "tap", point: { x: number; y: number }): void
}>()

const { t } = useI18n()
const streamImage = useTemplateRef<HTMLImageElement>("streamImage")

function handleClick(event: MouseEvent) {
  const img = streamImage.value
  if (!tapEnabled || !img) return
  const rect = img.getBoundingClientRect()
  const point = mapContainedPoint(
    { x: event.clientX - rect.left, y: event.clientY - rect.top },
    { width: rect.width, height: rect.height },
    { width: img.naturalWidth, height: img.naturalHeight },
  )
  if (point) emit("tap", point)
}

function clearStream() {
  const img = streamImage.value
  if (img) {
    img.src = ""
  }
}

defineExpose({ clearStream })
</script>
