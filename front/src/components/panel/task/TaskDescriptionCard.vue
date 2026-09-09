<template>
  <NCard :bordered="false" content-style="padding: 0.5rem">
    <div class="markdown-body min-h-20 max-h-52 overflow-y-auto" v-html="htmlContent" />
  </NCard>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import DOMPurify from "dompurify"
import { marked } from "marked"
import { useIndexStore, useInterfaceStore } from "@/stores"
import type { Task } from "@/types/interfaceModel"
import { resolveInterfaceDocumentContent } from "@/utils/interface/content"

const { t, locale } = useI18n()
const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const documentContent = ref("")
const selectedTaskId = computed(() => indexStore.SelectedTaskID)

function getTaskDocumentSource(task: Task | null): string {
  if (!task) {
    return ""
  }
  if (task.description) {
    return task.description
  }
  if (typeof task.desc === "string") {
    return task.desc
  }
  if (Array.isArray(task.desc)) {
    return task.desc.join("\n\n")
  }
  if (typeof task.doc === "string") {
    return task.doc
  }
  if (Array.isArray(task.doc)) {
    return task.doc.join("\n\n")
  }
  return ""
}

watch(
  [selectedTaskId, () => interfaceStore.interface, locale],
  async () => {
    const task = interfaceStore.getTaskByName(selectedTaskId.value)
    documentContent.value = await resolveInterfaceDocumentContent(
      interfaceStore.interface,
      locale.value,
      getTaskDocumentSource(task),
    )
  },
  { immediate: true },
)

const htmlContent = computed(() => {
  const source = documentContent.value?.trim() ? documentContent.value : t("panel.empty")
  const parsed = marked.parse(source || "", { gfm: true })
  return DOMPurify.sanitize(typeof parsed === "string" ? parsed : "")
})
</script>
