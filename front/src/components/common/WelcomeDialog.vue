<template>
  <NModal
    v-model:show="show"
    preset="card"
    :title="t('welcome.title')"
    :closable="false"
    :mask-closable="false"
    :close-on-esc="false"
    style="max-width: min(560px, calc(100vw - 32px))"
  >
    <div class="max-h-[60vh] overflow-y-auto">
      <template v-for="(html, index) in renderedContents" :key="index">
        <NDivider v-if="index > 0" />
        <div class="markdown-body" v-html="html" />
      </template>
    </div>

    <template #action>
      <NSpace justify="end">
        <NButton type="primary" @click="emit('confirm')">
          {{ t("common.confirm") }}
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { marked } from "marked"
import DOMPurify from "dompurify"

const { t } = useI18n()

const show = defineModel<boolean>("show", { required: true })
const { contents } = defineProps<{ contents: string[] }>()
const emit = defineEmits<{ (event: "confirm"): void }>()

const renderedContents = computed(() =>
  contents.map((content) => {
    const parsed = marked.parse(content, { gfm: true })
    return DOMPurify.sanitize(typeof parsed === "string" ? parsed : "")
  }),
)
</script>
