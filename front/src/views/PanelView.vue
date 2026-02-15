<template>
  <n-layout class="px-1 pt-3 h-[85vh] xl:h-[80vh]">
    <n-grid x-gap="20" cols="1 m:3" class="px-2" responsive="screen">
      <n-grid-item>
        <LeftPanel></LeftPanel>
      </n-grid-item>
      <n-grid-item>
        <MediumPanel></MediumPanel>
      </n-grid-item>
      <n-grid-item>
        <RightPanel></RightPanel>
      </n-grid-item>
    </n-grid>
  </n-layout>
</template>
<script setup lang="ts">
import LeftPanel from "../components/LeftPanel.vue"
import MediumPanel from "../components/MediumPanel.vue"
import RightPanel from "../components/RightPanel.vue"
import { onMounted } from "vue"
onMounted(() => {
  if (Notification.permission !== "granted") {
    Notification.requestPermission()
  }
})
</script>
