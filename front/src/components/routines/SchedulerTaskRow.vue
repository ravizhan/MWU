<template>
  <NCard
    :bordered="false"
    size="small"
    class="shadow-sm hover:shadow-md transition-shadow"
    content-style="padding: 12px"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="flex items-center gap-3 flex-1 min-w-0">
        <NSwitch
          :value="task.enabled"
          size="small"
          :aria-label="task.name"
          @update:value="handleToggle"
        />
        <div class="min-w-0">
          <div class="font-medium truncate">
            {{ task.name }}
            <NIcon
              v-if="task.wakeup_enabled"
              size="16"
              class="ml-1 inline-block align-[-2px] opacity-70"
              aria-hidden="true"
              :title="t('settings.scheduler.list.runsWhenClosed')"
            >
              <MoonOutline />
            </NIcon>
          </div>
          <div class="text-xs opacity-60">{{ task.description }}</div>
          <div class="flex flex-wrap items-center gap-x-3 text-xs opacity-50 mt-1">
            <span>
              {{ t("settings.scheduler.trigger") }}{{ t("common.colon") }}
              {{ formatTriggerText(task.trigger_config) }}
            </span>
            <span>
              {{ t("settings.scheduler.nextRun") }}{{ t("common.colon") }}
              {{ formatDateTimeText(task.next_run_time) }}
            </span>
          </div>
        </div>
      </div>
      <div class="flex gap-1 shrink-0">
        <NButton quaternary size="tiny" @click="emit('edit', task)">
          <template #icon>
            <NIcon size="14"><CreateOutline /></NIcon>
          </template>
          {{ t("common.edit") }}
        </NButton>
        <NButton quaternary size="tiny" type="error" @click="emit('delete', task.id)">
          <template #icon>
            <NIcon size="14"><TrashOutline /></NIcon>
          </template>
          {{ t("common.delete") }}
        </NButton>
      </div>
    </div>
  </NCard>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { CreateOutline, MoonOutline, TrashOutline } from "@vicons/ionicons5"
import { formatDateTime, formatTrigger } from "@/utils/scheduler/display"
import type { ScheduledTask, TriggerConfig } from "@/types/schedulerModel"

const { task } = defineProps<{
  task: ScheduledTask
}>()

const emit = defineEmits<{
  (e: "toggle", taskId: string, enabled: boolean): void
  (e: "edit", task: ScheduledTask): void
  (e: "delete", taskId: string): void
}>()

const { t, locale } = useI18n()

function formatTriggerText(triggerConfig: TriggerConfig): string {
  return formatTrigger(t, locale.value, triggerConfig)
}

function formatDateTimeText(dateStr?: string): string {
  return formatDateTime(t, locale.value, dateStr)
}

function handleToggle(enabled: boolean) {
  emit("toggle", task.id, enabled)
}
</script>
