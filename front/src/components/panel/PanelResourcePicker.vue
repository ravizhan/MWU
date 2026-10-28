<template>
  <NSelect
    :value="resource"
    :options="resourcesList"
    :placeholder="t('panel.selectResource')"
    :disabled="disabled"
    class="w-full"
    @update:value="emit('update:resource', $event)"
  />
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"

defineProps<{
  resource: string | null
  resourcesList: Array<{ label: string; value: string }>
  disabled: boolean
}>()

const emit = defineEmits<{
  (e: "update:resource", value: string | null): void
}>()

const { t } = useI18n()
</script>
