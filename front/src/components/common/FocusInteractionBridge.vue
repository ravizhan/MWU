<template>
  <NModal
    :show="current !== null"
    :closable="false"
    :mask-closable="false"
    :close-on-esc="false"
    preset="dialog"
    :title="title"
    positive-text="继续"
    negative-text="停止任务"
    :positive-button-props="{
      disabled: submitting !== null,
      loading: submitting === 'acknowledge',
    }"
    :negative-button-props="{
      disabled: submitting !== null,
      loading: submitting === 'cancel',
    }"
    @positive-click="onAcknowledge"
    @negative-click="onCancel"
  >
    <div class="whitespace-pre-wrap">{{ current?.content }}</div>
  </NModal>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useI18n } from "vue-i18n"
import { useFocusInteractionStore } from "@/stores/focus/focusInteraction"
import { tryCatch } from "@/utils/tryCatch"

/**
 * 焦点交互桥：pending modal 阻塞后端流水线时的确认/取消 UI。
 * 必须挂在 NDialogProvider 内。一次只显示最早的 pending modal；
 * 非阻塞 dialog 由 feedback bridge 直接展示，不进入这里的 pending 状态。
 */
const store = useFocusInteractionStore()
const { t } = useI18n()
const submitting = ref<"acknowledge" | "cancel" | null>(null)

const current = computed(() => {
  return store.pending.find((item) => item.mode === "modal") ?? null
})

const title = computed(() => t("common.confirm"))

async function onAcknowledge(): Promise<boolean> {
  if (submitting.value !== null) {
    return false
  }
  const item = current.value
  if (!item) {
    return false
  }
  submitting.value = "acknowledge"
  const [result] = await tryCatch(() => store.acknowledge(item.id))
  submitting.value = null
  return result ?? false
}

async function onCancel(): Promise<boolean> {
  if (submitting.value !== null) {
    return false
  }
  const item = current.value
  if (!item) {
    return false
  }
  submitting.value = "cancel"
  const [result] = await tryCatch(() => store.cancel(item.id))
  submitting.value = null
  return result ?? false
}
</script>
