<template>
  <NButton
    v-if="resolved.kind === 'url'"
    text
    type="primary"
    tag="a"
    :href="resolved.text"
    target="_blank"
    rel="noopener noreferrer"
    class="break-all"
  >
    {{ resolved.text }}
  </NButton>
  <template v-else-if="resolved.kind === 'file'">
    <NButton text type="primary" class="break-all" @click="showContent = true">
      {{ resolved.text }}
    </NButton>
    <NModal
      v-model:show="showContent"
      preset="card"
      :title="title"
      style="max-width: min(720px, calc(100vw - 32px))"
    >
      <div class="markdown-body max-h-[70vh] overflow-y-auto" v-html="renderedContent" />
    </NModal>
  </template>
  <span v-else-if="resolved.kind === 'text'" class="whitespace-pre-wrap break-all">
    {{ resolved.text }}
  </span>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import DOMPurify from "dompurify"
import { marked } from "marked"
import {
  resolveInterfaceLinkedContent,
  resolveInterfaceText,
  type InterfaceLinkedContent,
} from "@/utils/interface/content"

const { value, title } = defineProps<{
  value?: string
  title: string
}>()

const resolved = ref<InterfaceLinkedContent>({ kind: "empty" })
const showContent = ref(false)

// 依赖解析后的文本，切换界面语言时 `$key` 会重新解析
watch(
  () => resolveInterfaceText(value),
  async (_text, _previous, onCleanup) => {
    let stale = false
    onCleanup(() => {
      stale = true
    })
    const result = await resolveInterfaceLinkedContent(value)
    if (!stale) {
      resolved.value = result
    }
  },
  { immediate: true },
)

const renderedContent = computed(() => {
  if (resolved.value.kind !== "file") return ""
  const parsed = marked.parse(resolved.value.content, { gfm: true })
  return DOMPurify.sanitize(typeof parsed === "string" ? parsed : "")
})
</script>
