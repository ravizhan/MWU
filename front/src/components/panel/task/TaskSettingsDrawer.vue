<template>
  <NDrawer
    v-model:show="drawerVisible"
    placement="bottom"
    height="80%"
    :mask-closable="true"
    @mask-click="indexStore.closeTaskSettingsDrawer()"
  >
    <NDrawerContent :native-scrollbar="false">
      <div class="p-4">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-lg font-bold">{{ drawerTitle }}</h3>
          <NButton quaternary circle size="small" @click="indexStore.closeTaskSettingsDrawer()">
            <template #icon>
              <NIcon size="16"><CloseOutline /></NIcon>
            </template>
          </NButton>
        </div>
        <div class="space-y-4">
          <TaskOptionPanel
            :current-task-id="selectedTaskId"
            :options="configStore.options"
            :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
            :no-options-text="t('settings.scheduler.dialog.noOptions')"
          />
          <TaskDescriptionCard />
        </div>
      </div>
    </NDrawerContent>
  </NDrawer>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { CloseOutline } from "@vicons/ionicons5"
import TaskDescriptionCard from "@/components/panel/task/TaskDescriptionCard.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import { useIndexStore, useInterfaceStore, useTaskConfigStore } from "@/stores"
import { resolveInterfaceText } from "@/utils/interface/content"

const { t, locale } = useI18n()
const configStore = useTaskConfigStore()
const indexStore = useIndexStore()
const interfaceStore = useInterfaceStore()

const selectedTaskId = computed(() => indexStore.SelectedTaskID || null)
const drawerVisible = computed({
  get: () => indexStore.TaskSettingsDrawerVisible,
  set: (visible: boolean) => indexStore.setTaskSettingsDrawerVisible(visible),
})
const drawerTitle = computed(() => {
  const task = selectedTaskId.value ? interfaceStore.getTaskByName(selectedTaskId.value) : null
  if (!task) {
    return t("panel.taskSettings")
  }

  const taskName = resolveInterfaceText(
    interfaceStore.interface,
    locale.value,
    task.label,
    task.name,
  )
  return `${t("panel.taskSettings")} · ${taskName}`
})
</script>
