<template>
  <img v-if="src" :src="src" alt="" class="shrink-0 object-contain" />
</template>

<script setup lang="ts">
import { computed } from "vue"
import { resolveInterfaceAssetUrl } from "@/utils/interface/content"

const { icon } = defineProps<{ icon?: string | null }>()

const src = computed(() => resolveInterfaceAssetUrl(icon))
</script>
