<template>
  <NEl
    tag="div"
    class="pre-task-row flex items-center gap-2 p-2 rounded-lg border border-solid"
    :style="{ borderColor: 'var(--divider-color)', background: 'var(--card-color)' }"
  >
    <NIcon size="20" class="pre-task-drag-handle cursor-grab"><ReorderThreeOutline /></NIcon>
    <NInput
      v-model:value="item.command"
      size="small"
      class="flex-1"
      :placeholder="$t('taskConfig.preTasks.command')"
    />
    <NInputNumber
      v-model:value="item.timeout"
      size="small"
      class="w-16"
      min="1"
      max="3600"
      :show-button="false"
    />
    <NSwitch v-model:value="item.enabled" />
    <NButton quaternary circle size="tiny" type="error" @click="emit('delete')">
      <template #icon>
        <NIcon size="20"><TrashOutline /></NIcon>
      </template>
    </NButton>
  </NEl>
</template>

<script setup lang="ts">
import { ReorderThreeOutline, TrashOutline } from "@vicons/ionicons5"
import type { PreTaskCommand } from "@/types/taskConfigModel"

const emit = defineEmits<{
  (event: "delete"): void
}>()

const item = defineModel<PreTaskCommand>("item", { required: true })
</script>

<style scoped>
.cursor-grab {
  cursor: grab;
}

.cursor-grab:active {
  cursor: grabbing;
}

.ghost {
  opacity: 0.5;
  background: oklch(85% 0.1 200);
}
</style>
