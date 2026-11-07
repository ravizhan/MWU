<template>
  <NCard
    :bordered="false"
    size="small"
    class="cursor-pointer recipe-card"
    content-style="padding: 12px"
    @click="emit('apply', preset.name)"
  >
    <h3 class="text-sm font-semibold flex items-center gap-1.5">
      <InterfaceIcon :icon="preset.icon" class="h-5 w-5" />
      <span class="truncate">{{ preset.label }}</span>
    </h3>
    <p class="text-xs opacity-70 line-clamp-2">{{ preset.description }}</p>
    <div class="flex justify-end mt-2">
      <NTag type="primary" size="small">
        {{ preset.taskCount }} {{ t("panel.preset.taskCount") }}
      </NTag>
    </div>
  </NCard>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import InterfaceIcon from "@/components/common/InterfaceIcon.vue"

interface RecipeCardPreset {
  name: string
  label: string
  description: string
  icon?: string
  taskCount: number
}

const { preset } = defineProps<{ preset: RecipeCardPreset }>()
const emit = defineEmits<{
  (e: "apply", name: string): void
}>()
const { t } = useI18n()
</script>

<style scoped>
/* Match the navbar menu pill: single background-color change on hover. */
.recipe-card {
  transition: background-color 0.2s ease;
}
.recipe-card:hover {
  background-color: var(--hover-color);
}
</style>
