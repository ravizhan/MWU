<template>
  <NSelect
    :value="resource"
    :options="options"
    :render-label="renderIconLabel"
    :placeholder="t('panel.selectResource')"
    :disabled="disabled"
    class="w-full"
    @update:value="emit('update:resource', $event)"
  />
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { resolveInterfaceText } from "@/utils/interface/content"
import { renderIconLabel } from "@/utils/interface/iconLabel"

const { resourcesList } = defineProps<{
  resource: string | null
  resourcesList: Array<{ label: string; value: string; icon?: string | null }>
  disabled: boolean
}>()

const emit = defineEmits<{
  (e: "update:resource", value: string | null): void
}>()

const { t } = useI18n()

const options = computed(() =>
  resourcesList.map((item) => ({
    label: resolveInterfaceText(item.label, item.value),
    value: item.value,
    icon: item.icon,
  })),
)
</script>
