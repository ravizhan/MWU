<template>
  <div class="flex flex-col gap-3 flex-1 min-h-0">
    <TaskOptionPanel
      class="flex-1 min-h-0"
      :current-task-id="selectedTaskId"
      :options="configStore.options"
      :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
      :no-options-text="t('settings.scheduler.dialog.noOptions')"
      scrollbar-class="flex-1 min-h-0 overflow-y-auto rounded-xl"
    />
    <TaskDescriptionCard class="shrink-0" />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import TaskDescriptionCard from "@/components/panel/task/TaskDescriptionCard.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import { useIndexStore, useTaskConfigStore } from "@/stores"

const { t } = useI18n()
const indexStore = useIndexStore()
const configStore = useTaskConfigStore()
const selectedTaskId = computed(() => indexStore.SelectedTaskID)
</script>
