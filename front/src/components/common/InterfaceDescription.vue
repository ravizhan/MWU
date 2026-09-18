<template>
  <div v-if="htmlContent" class="markdown-body text-xs opacity-60" v-html="htmlContent" />
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import DOMPurify from "dompurify"
import { marked } from "marked"
import { useInterfaceStore } from "@/stores"
import { resolveInterfaceDocumentContent } from "@/utils/interface/content"

const { text } = defineProps<{
  text?: string
}>()

const interfaceStore = useInterfaceStore()
const documentContent = ref("")

watch(
  () => text,
  async (value) => {
    documentContent.value = await resolveInterfaceDocumentContent(
      interfaceStore.interface,
      "",
      value,
    )
  },
  { immediate: true },
)

const htmlContent = computed(() => {
  const source = documentContent.value.trim()
  if (!source) return ""
  const parsed = marked.parse(source, { gfm: true })
  return DOMPurify.sanitize(typeof parsed === "string" ? parsed : "")
})
</script>

<style scoped>
/* 说明文字是列表行内的紧凑提示，压掉 markdown 段落的默认外边距。 */
.markdown-body :deep(> :first-child) {
  margin-top: 0;
}

.markdown-body :deep(> :last-child) {
  margin-bottom: 0;
}
</style>
