<template>
  <NModal
    v-model:show="showDialog"
    preset="dialog"
    type="warning"
    :title="t('settings.scheduler.conflict.title')"
    :content="conflictContent"
    :mask-closable="true"
    @close="handleClose"
  >
    <template #action>
      <NSpace justify="end">
        <NButton
          v-if="conflict && conflict.code !== 'update_in_progress'"
          type="warning"
          @click="handleStopRestart"
        >
          {{ t("settings.scheduler.conflict.stopAndRestart") }}
        </NButton>
        <NButton @click="handleClose">
          {{ t("common.cancel") }}
        </NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import { useDeviceConnectionStore } from "@/stores/device/deviceConnection"

const { t } = useI18n()
const router = useRouter()
const deviceStore = useDeviceConnectionStore()

const conflict = computed(() => deviceStore.startConflict)
const showDialog = computed({
  get: () => Boolean(conflict.value),
  set: (value: boolean) => {
    if (!value) {
      handleClose()
    }
  },
})
const conflictContent = computed(() => {
  if (conflict.value?.code === "update_in_progress") {
    return t("settings.scheduler.conflict.updateInProgress")
  }
  if (conflict.value) {
    return t("settings.scheduler.conflict.busyMessage", {
      name: conflict.value.active_task_name,
    })
  }
  return ""
})

function handleClose() {
  deviceStore.clearStartConflict()
}

async function handleStopRestart() {
  const success = await deviceStore.stopActiveAndRestart()
  if (success) {
    void router.push({ name: "logs" })
  }
}
</script>
