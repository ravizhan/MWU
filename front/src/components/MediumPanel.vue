<template>
  <div class="col-name">{{ t("panel.taskSettings") }}</div>
  <n-card hoverable content-style="padding: 0;" class="transition-all duration-300 overflow-hidden">
    <TaskOptionPanel
      :current-task-id="selectedTaskId"
      :options="configStore.options"
      :scrollbar-class="scrollbarClass"
    />
  </n-card>

  <div class="col-name">{{ t("panel.taskDescription") }}</div>
  <n-card hoverable content-style="padding: 0.5rem 1rem;" class="transition-all duration-300">
    <n-scrollbar trigger="none">
      <div ref="mdContainer" class="markdown-body min-h-50 max-h-65" v-html="md"></div>
    </n-scrollbar>
  </n-card>
  <!-- 隐藏的 n-image 用于预览 -->
  <n-image ref="previewImageRef" :src="previewSrc" :show-toolbar="true" style="display: none" />
</template>
<script setup lang="ts">
import { marked } from "marked"
import type { Tokens } from "marked"
import { ref, watch, nextTick, computed } from "vue"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "../stores/interface.ts"
import { useIndexStore } from "../stores"
import { useTaskConfigStore } from "../stores/taskConfig"
import { NImage } from "naive-ui"
import TaskOptionPanel from "./TaskOptionPanel.vue"
import DOMPurify from "dompurify"

const { t } = useI18n()
const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const configStore = useTaskConfigStore()
const md = ref("")
const scrollbarClass = "max-h-65 !rounded-[12px]"

const mdContainer = ref<HTMLElement | null>(null)
const previewImageRef = ref<InstanceType<typeof NImage> | null>(null)
const previewSrc = ref("")
const render = new marked.Renderer()

render.image = function ({ href, title, text }: Tokens.Image) {
  const safeHref = href || ""
  const titleAttr = title ? ` title="${title}"` : ""
  const altAttr = text ? ` alt="${text}"` : ""
  return `<img src="${safeHref}"${titleAttr}${altAttr} class="preview-image" style="max-width: 100%; object-fit: contain; cursor: pointer;" />`
}

function setupImagePreview() {
  if (!mdContainer.value) return
  const images = mdContainer.value.querySelectorAll("img.preview-image")
  images.forEach((img) => {
    ;(img as HTMLImageElement).onclick = () => {
      previewSrc.value = (img as HTMLImageElement).src
      nextTick(() => {
        previewImageRef.value?.click()
      })
    }
  })
}

marked.setOptions({
  renderer: render,
  gfm: true,
  pedantic: false,
})

// 获取当前选中的任务ID
const selectedTaskId = computed(() => indexStore.SelectedTaskID)

watch(
  () => indexStore.SelectedTaskID,
  async (newTaskId) => {
    const interface_task = interfaceStore.interface?.task
    if (!interface_task || interface_task.length === 0) {
      return
    }
    for (const i of interface_task!) {
      if (i.entry === newTaskId) {
        if (i.description) {
          md.value = DOMPurify.sanitize(marked.parse(i.description) as string)
        } else {
          md.value = marked(t("panel.empty")) as string
        }

        nextTick(() => {
          setupImagePreview()
        })
        break
      }
    }
  },
  { immediate: true },
)
</script>
