<template>
  <div class="flex w-full max-w-xs items-center gap-2">
    <NSelect v-model:value="value" size="small" class="flex-1" :options="options" />
    <NButton
      v-if="showRescan"
      quaternary
      circle
      size="small"
      :disabled="refreshing"
      @click="emit('rescan')"
    >
      <template #icon>
        <NIcon size="16" :class="{ 'animate-spin': refreshing }">
          <RefreshOutline />
        </NIcon>
      </template>
    </NButton>
  </div>
</template>

<script setup lang="ts">
import type { SelectOption } from "naive-ui"
import { RefreshOutline } from "@vicons/ionicons5"

const {
  options,
  refreshing = false,
  showRescan = false,
} = defineProps<{
  options: SelectOption[]
  refreshing?: boolean
  showRescan?: boolean
}>()

const emit = defineEmits<{
  (event: "rescan"): void
}>()

const value = defineModel<string | null>("value", { required: true })
</script>
