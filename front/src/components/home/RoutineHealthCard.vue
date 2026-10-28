<template>
  <div class="space-y-3">
    <div v-if="schedulerStore.tasks.length === 0" class="text-center py-6 opacity-50">
      <NIcon size="30" class="mx-auto mb-2" style="color: var(--text-color-3)">
        <TimeOutline />
      </NIcon>
      <p class="text-sm">{{ t("settings.scheduler.noTasks") }}</p>
    </div>
    <div v-else class="space-y-2">
      <div
        v-for="task in schedulerStore.tasks.slice(0, 5)"
        :key="task.id"
        class="flex items-center gap-3 p-2 rounded-lg"
        style="background: var(--card-color)"
      >
        <div
          class="w-2 h-2 rounded-full shrink-0"
          :style="{
            backgroundColor: task.enabled ? 'var(--success-color)' : 'var(--text-color-3)',
          }"
        />
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium truncate">{{ task.name }}</div>
          <div class="text-xs opacity-60">
            {{ formatTriggerText(task.trigger_config) }}
          </div>
        </div>
        <div class="text-xs opacity-60 shrink-0">
          {{ task.enabled ? formatDateTimeText(task.next_run_time) : t("panel.health.paused") }}
        </div>
      </div>
    </div>

    <RouterLink :to="{ name: 'routines' }">
      <NButton secondary type="primary" size="small" block>
        <template #icon>
          <NIcon size="16"><AddCircleOutline /></NIcon>
        </template>
        {{ t("settings.scheduler.create") }}
      </NButton>
    </RouterLink>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { AddCircleOutline, TimeOutline } from "@vicons/ionicons5"
import { useSchedulerStore } from "@/stores"
import { formatDateTime, formatTrigger } from "@/utils/scheduler/display"
import type { TriggerConfig } from "@/types/schedulerModel"

const { t, locale } = useI18n()
const schedulerStore = useSchedulerStore()

function formatTriggerText(triggerConfig: TriggerConfig): string {
  return formatTrigger(t, locale.value, triggerConfig)
}

function formatDateTimeText(dateStr?: string): string {
  return formatDateTime(t, locale.value, dateStr)
}
</script>
