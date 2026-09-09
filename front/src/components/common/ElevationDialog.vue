<template>
  <NModal
    :show="deviceStore.showElevationPrompt"
    :mask-closable="false"
    preset="dialog"
    type="warning"
    :title="t('privilege.title')"
    positive-text=""
    negative-text=""
  >
    <div class="space-y-2 text-sm">
      <p>{{ t("privilege.description") }}</p>
      <p class="text-xs opacity-60">{{ t("privilege.lanNote") }}</p>
    </div>
    <template #action>
      <div class="flex justify-end gap-2">
        <NButton size="small" @click="decline">{{ t("common.cancel") }}</NButton>
        <NButton size="small" type="warning" :loading="restarting" @click="confirmRestart">
          {{ t("privilege.restart") }}
        </NButton>
      </div>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"
import { useDeviceConnectionStore } from "@/stores"
import { postRestartElevated } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"

/**
 * 管理员权限重启确认（permission_required）。
 * 用户拒绝/系统拒绝 → 本次准备失败；确认 → 后端停止运行、取消 modal、
 * 有限遥测收尾后以管理员权限重启。不自动重放任务。
 */
const { t } = useI18n()
const deviceStore = useDeviceConnectionStore()
const restarting = ref(false)

function decline(): void {
  deviceStore.showElevationPrompt = false
}

async function confirmRestart(): Promise<void> {
  restarting.value = true
  const result = await postRestartElevated()
  restarting.value = false
  if (result.success) {
    deviceStore.showElevationPrompt = false
    showGlobalMessage("success", result.message)
    return
  }
  showGlobalMessage("error", result.message)
}
</script>
