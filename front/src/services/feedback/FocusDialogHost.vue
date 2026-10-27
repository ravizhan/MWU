<template>
  <NModal
    v-for="prompt in active ? [active] : []"
    :key="`${prompt.kind}:${prompt.id}`"
    :show="true"
    preset="dialog"
    :type="prompt.level"
    :title="prompt.kind === 'modal' ? t('focus.modalTitle') : t('focus.dialogTitle')"
    :closable="prompt.kind === 'dialog'"
    :show-mask="prompt.kind === 'modal'"
    :block-scroll="prompt.kind === 'modal'"
    :auto-focus="prompt.kind === 'modal'"
    :trap-focus="prompt.kind === 'modal'"
    :close-on-esc="false"
    :mask-closable="false"
    style="
      display: flex;
      flex-direction: column;
      width: 32rem;
      max-width: calc(100vw - 2rem);
      max-height: calc(100dvh - 2rem);
    "
    title-style="flex-shrink: 0"
    content-style="
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    "
    action-style="flex-shrink: 0"
    @update:show="!$event && prompt.kind === 'dialog' && focusStore.dismissDialog(prompt.id)"
    @keydown.esc="prompt.kind === 'dialog' && focusStore.dismissDialog(prompt.id)"
  >
    {{ prompt.message }}
    <template #action>
      <template v-if="prompt.kind === 'modal'">
        <NButton :disabled="focusStore.busy" @click="handleStop">
          {{ t("focus.stopTask") }}
        </NButton>
        <NButton
          type="primary"
          :disabled="focusStore.busy"
          :loading="focusStore.busy"
          @click="handleConfirm(prompt.id)"
        >
          {{ t("focus.confirmAndContinue") }}
        </NButton>
      </template>
      <NButton v-else @click="focusStore.dismissDialog(prompt.id)">
        {{ t("focus.close") }}
      </NButton>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { showGlobalMessage } from "@/services/feedback/message"
import { useFocusStore } from "@/stores/focus/focus"

const { t } = useI18n()
const focusStore = useFocusStore()
const active = computed(() => focusStore.active)

async function handleConfirm(id: string): Promise<void> {
  const success = await focusStore.confirmModal(id)
  if (success) return
  showGlobalMessage("error", t("focus.confirmFailed"))
}

function handleStop(): void {
  void focusStore.stopTaskFromModal()
}
</script>
