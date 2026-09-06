<template>
  <NModal
    v-model:show="visible"
    :mask-closable="false"
    :close-on-esc="false"
    preset="dialog"
    :title="title"
    positive-text="继续"
    negative-text="停止任务"
    @positive-click="onAcknowledge"
    @negative-click="onCancel"
  >
    <div class="whitespace-pre-wrap">{{ current?.content }}</div>
  </NModal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useFocusInteractionStore } from "@/stores/focus/focusInteraction"

/**
 * 焦点交互桥：pending modal 阻塞后端流水线时的确认/取消 UI。
 * 必须挂在 NDialogProvider 内。一次只显示最早的 pending 项。
 */
const store = useFocusInteractionStore()
const { t } = useI18n()

const visible = ref(false)

const current = computed(() => {
  const modals = store.pending.filter((item) => item.mode === "modal")
  return modals.length > 0 ? modals[0] : null
})

const title = computed(() => t("focus.interaction.title"))

watch(
  current,
  (value) => {
    visible.value = value !== null
  },
  { immediate: true },
)

function onAcknowledge(): void {
  if (current.value) {
    void store.acknowledge(current.value.id)
  }
  visible.value = false
}

function onCancel(): void {
  if (current.value) {
    void store.cancel(current.value.id)
  }
  visible.value = false
}
</script>
