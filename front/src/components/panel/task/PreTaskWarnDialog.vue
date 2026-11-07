<template>
  <NModal
    v-model:show="show"
    preset="dialog"
    type="warning"
    :title="t('taskConfig.preTasks.warnTitle')"
    :mask-closable="true"
    @close="handleCancel"
  >
    <div class="space-y-3">
      <p class="text-sm leading-6">
        {{ t("taskConfig.preTasks.warnContent") }}
      </p>
      <NCheckbox v-model:checked="dontRemind">
        {{ t("taskConfig.preTasks.dontRemind") }}
      </NCheckbox>
    </div>

    <template #action>
      <NSpace justify="end">
        <NButton @click="handleCancel">
          {{ t("common.cancel") }}
        </NButton>
        <NButton type="warning" @click="handleConfirm">
          {{ t("common.confirm") }}
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { ref, watch } from "vue"
import { useI18n } from "vue-i18n"

const emit = defineEmits<{
  (event: "confirm", dontRemind: boolean): void
}>()
const show = defineModel<boolean>("show", { required: true })
const { t } = useI18n()
const dontRemind = ref(false)

watch(show, (visible) => {
  if (!visible) {
    dontRemind.value = false
  }
})

function handleCancel() {
  show.value = false
  dontRemind.value = false
}

function handleConfirm() {
  const shouldRemember = dontRemind.value
  show.value = false
  dontRemind.value = false
  emit("confirm", shouldRemember)
}
</script>
