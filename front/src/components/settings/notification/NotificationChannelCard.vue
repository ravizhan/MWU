<template>
  <NEl
    tag="div"
    class="space-y-3 rounded-lg border border-solid p-3"
    :style="{ borderColor: 'var(--divider-color)', background: 'var(--card-color)' }"
  >
    <div class="flex items-center gap-2">
      <span class="flex-1 truncate text-sm font-medium">{{ definition.label }}</span>
      <NSwitch
        size="small"
        :value="channel.enabled"
        :aria-label="t('settings.notification.channelEnabled')"
        @update:value="emit('update', { ...channel, enabled: $event })"
      />
      <NButton
        quaternary
        circle
        size="tiny"
        type="error"
        :aria-label="t('common.delete')"
        @click="emit('delete')"
      >
        <template #icon>
          <NIcon size="18"><TrashOutline /></NIcon>
        </template>
      </NButton>
    </div>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div v-for="field in visibleFields" :key="field.key" :class="{ 'md:col-span-2': field.wide }">
        <label class="mb-1 block text-xs font-medium">{{ field.label }}</label>
        <NSelect
          v-if="field.kind === 'select'"
          size="small"
          :value="paramValue(field)"
          :options="field.options"
          @update:value="handleSelect(field.key, $event)"
        />
        <NInput
          v-else
          size="small"
          class="font-mono"
          :type="field.kind === 'text' ? 'text' : field.kind"
          :show-password-on="field.kind === 'password' ? 'click' : undefined"
          :autosize="field.kind === 'textarea' ? { minRows: 3 } : undefined"
          :value="paramValue(field)"
          :placeholder="field.placeholder"
          :input-props="{ autocomplete: 'off', spellcheck: false }"
          @update:value="updateParam(field.key, $event)"
        />
      </div>
    </div>
  </NEl>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { TrashOutline } from "@vicons/ionicons5"
import type { ChannelDefinition, ChannelField } from "./channels"
import type { NotificationChannel } from "@/types/settingsModel"

const { channel, definition } = defineProps<{
  channel: NotificationChannel
  definition: ChannelDefinition
}>()

const emit = defineEmits<{
  (event: "update", channel: NotificationChannel): void
  (event: "delete"): void
}>()

const { t } = useI18n()

const visibleFields = computed(() =>
  definition.fields.filter((field) => field.visible?.(channel.params) ?? true),
)

function paramValue(field: ChannelField): string {
  return channel.params[field.key] ?? field.default
}

function updateParam(key: string, value: string) {
  emit("update", { ...channel, params: { ...channel.params, [key]: value } })
}

function handleSelect(key: string, value: string | number | null) {
  if (typeof value !== "string") return
  updateParam(key, value)
}
</script>
