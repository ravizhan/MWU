<template>
  <div class="grid grid-cols-[1fr_auto] items-center gap-x-2 gap-y-1">
    <NTooltip :disabled="!pretask.description && compatible" :max-width="320">
      <template #trigger>
        <NEl
          tag="div"
          class="flex min-w-0 items-center gap-2 px-3 py-2 rounded-lg border border-solid text-sm font-medium"
          :class="{ 'opacity-50': !compatible }"
          :style="{
            borderColor: 'var(--divider-color)',
            background: 'var(--card-color)',
          }"
        >
          <InterfaceIcon :icon="pretask.icon" class="h-5 w-5" />
          <span class="truncate">{{ displayName }}</span>
        </NEl>
      </template>
      <div class="space-y-1">
        <div v-if="pretask.description">
          {{ resolveInterfaceText(pretask.description, pretask.description) }}
        </div>
        <div v-if="!compatible">
          {{ $t("panel.piPretask.incompatible") }}
        </div>
      </div>
    </NTooltip>
    <NSwitch size="small" :value="enabled" @update:value="emit('update:enabled', $event)" />
    <NEl
      v-if="enabled && pretask.option?.length"
      tag="div"
      class="col-span-2 overflow-hidden rounded-lg border border-solid"
      style="border-color: var(--divider-color)"
    >
      <TaskSettingOptionRow v-for="n in pretask.option" :key="n" :name="n" />
    </NEl>
  </div>
</template>

<script setup lang="ts">
import type { Pretask } from "@/types/interfaceModel"
import { resolveInterfaceText } from "@/utils/interface/content"
import InterfaceIcon from "@/components/common/InterfaceIcon.vue"
import TaskSettingOptionRow from "@/components/settings/sections/TaskSettingOptionRow.vue"

const { pretask, displayName, compatible, enabled } = defineProps<{
  pretask: Pretask
  displayName: string
  compatible: boolean
  enabled: boolean
}>()

const emit = defineEmits<{
  (event: "update:enabled", value: boolean): void
}>()
</script>
