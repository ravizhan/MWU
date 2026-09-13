<template>
  <NEl
    tag="div"
    class="task-select-row flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors"
    :class="{
      'border-b border-solid last:border-b-0': bordered,
      'cursor-grab': showDragHandle,
    }"
    :style="{ borderColor: 'var(--divider-color)', background: 'var(--card-color)' }"
    @click="handleClick"
  >
    <NIcon
      v-if="showDragHandle"
      size="20"
      class="cursor-grab active:cursor-grabbing shrink-0"
      :aria-hidden="true"
    >
      <ReorderThreeOutline />
    </NIcon>
    <NCheckbox
      class="shrink-0"
      :checked="checked"
      size="large"
      :aria-label="label"
      @click.stop
      @update:checked="emit('update:checked', $event)"
    />
    <span class="flex-1 text-base truncate select-none">{{ label }}</span>
    <NButton quaternary circle size="small" class="shrink-0" @click.stop="emit('config')">
      <template #icon>
        <NIcon size="20"><SettingsOutline /></NIcon>
      </template>
    </NButton>
  </NEl>
</template>

<script setup lang="ts">
import { ReorderThreeOutline, SettingsOutline } from "@vicons/ionicons5"

defineProps<{
  label: string
  checked: boolean
  showDragHandle?: boolean
  /** Flat view rows are separated by a divider; group rows are not. */
  bordered?: boolean
}>()

const emit = defineEmits<{
  (e: "click"): void
  (e: "update:checked", value: boolean): void
  (e: "config"): void
}>()

function handleClick(): void {
  emit("click")
}
</script>

<style scoped>
.cursor-grab {
  cursor: grab;
}
.cursor-grab:active {
  cursor: grabbing;
}
</style>
