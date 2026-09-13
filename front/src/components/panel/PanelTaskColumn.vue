<template>
  <div class="space-y-3">
    <TaskOptionPanel
      :current-task-id="selectedTaskId"
      :options="configStore.options"
      :controller-name="deviceStore.selectedControllerName"
      :resource-name="deviceStore.resource"
      :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
      :no-options-text="t('settings.scheduler.dialog.noOptions')"
    />
    <TaskDescriptionCard />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import TaskDescriptionCard from "@/components/panel/task/TaskDescriptionCard.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import { useDeviceConnectionStore, useIndexStore, useTaskConfigStore } from "@/stores"

const { t } = useI18n()
const indexStore = useIndexStore()
const configStore = useTaskConfigStore()
const deviceStore = useDeviceConnectionStore()
const selectedTaskId = computed(() => indexStore.SelectedTaskID)
</script>
