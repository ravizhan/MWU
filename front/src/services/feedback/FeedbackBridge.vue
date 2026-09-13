<template>
  <slot />
</template>

<script setup lang="ts">
import { useMessage } from "naive-ui"
import { useDialog } from "naive-ui"
import { registerDialogApi, registerMessageApi } from "./message"

registerMessageApi(useMessage())
registerDialogApi(useDialog())
</script>
