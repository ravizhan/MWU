<template>
  <NCard v-if="htmlContent" :bordered="false" content-style="padding: 0.5rem">
    <div class="markdown-body max-h-52 overflow-y-auto" v-html="htmlContent" />
  </NCard>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import DOMPurify from "dompurify"
import { marked } from "marked"
import { useIndexStore, useInterfaceStore } from "@/stores"
import type { Task } from "@/types/interfaceModel"
import { resolveInterfaceDocumentContent, resolveInterfaceText } from "@/utils/interface/content"

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
  [
    selectedTaskId,
    () => interfaceStore.interface,
    () =>
      resolveInterfaceText(
        getTaskDocumentSource(interfaceStore.getTaskByName(selectedTaskId.value)),
      ),
  ],
  async (_value, _previous, onCleanup) => {
    let stale = false
    onCleanup(() => {
      stale = true
    })
    const task = interfaceStore.getTaskByName(selectedTaskId.value)
    const content = await resolveInterfaceDocumentContent(getTaskDocumentSource(task))
    if (!stale) {
      documentContent.value = content
    }
  },
  { immediate: true },
)

// Tasks without a description render nothing; the option panel already shows the empty state.
const htmlContent = computed(() => {
  const source = documentContent.value.trim()
  if (!source) return ""
  const parsed = marked.parse(source, { gfm: true })
  return DOMPurify.sanitize(typeof parsed === "string" ? parsed : "")
})
</script>
