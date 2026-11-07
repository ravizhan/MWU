<template>
  <NCard v-bind="$attrs" size="small" content-style="padding: 0">
    <NCollapse v-model:expanded-names="expandedNames" arrow-placement="right">
      <NCollapseItem name="pre-tasks">
        <template #header>
          <PreTaskHeader />
        </template>
        <div class="px-3 pb-3 space-y-2">
          <div v-if="piPretasks.length > 0" class="text-xs font-medium opacity-60">
            {{ $t("panel.piPretask.title") }}
          </div>
          <PiPretaskRow
            v-for="(item, index) in piPretasks"
            :key="`${item.key}-${index}`"
            :pretask="item.pretask"
            :display-name="item.displayName"
            :compatible="item.compatible"
            :enabled="item.enabled"
            @update:enabled="settingsStore.setPretaskEnabled(item.key, $event)"
          />

          <div v-if="piPretasks.length > 0" class="flex items-center gap-2 py-1">
            <span class="h-px flex-1" style="background: var(--divider-color)" />
            <span class="text-xs opacity-50">{{ $t("panel.piPretask.userSection") }}</span>
            <span class="h-px flex-1" style="background: var(--divider-color)" />
          </div>

          <PreTaskToolbar @add="handleAdd" />

          <VueDraggable
            v-if="preTasks.length > 0"
            v-model="preTasks"
            class="space-y-1.5"
            :animation="150"
            handle=".pre-task-drag-handle"
            :delay="120"
            :delay-on-touch-only="true"
            ghost-class="ghost"
          >
            <PreTaskRow
              v-for="(item, index) in preTasks"
              :key="item.id"
              :item="item"
              @delete="handleDelete(index)"
            />
          </VueDraggable>

          <NEl
            v-else
            tag="div"
            class="text-center py-4 opacity-50 rounded-lg"
            style="background: var(--card-color)"
          >
            <NIcon size="30" class="mx-auto mb-1"><FileTrayOutline /></NIcon>
            <p class="text-sm">{{ $t("taskConfig.preTasks.empty") }}</p>
          </NEl>
        </div>
      </NCollapseItem>
    </NCollapse>
    <PreTaskWarnDialog v-model:show="showWarn" @confirm="handleWarnConfirm" />
  </NCard>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import { FileTrayOutline } from "@vicons/ionicons5"
import { useInterfaceStore, useSettingsStore } from "@/stores"
import { pretaskKey } from "@/stores/interface/interface"
import type { Pretask } from "@/types/interfaceModel"
import type { PreTaskCommand } from "@/types/taskConfigModel"
import PreTaskHeader from "@/components/panel/task/PreTaskHeader.vue"
import PiPretaskRow from "@/components/panel/task/PiPretaskRow.vue"
import PreTaskRow from "@/components/panel/task/PreTaskRow.vue"
import PreTaskToolbar from "@/components/panel/task/PreTaskToolbar.vue"
import PreTaskWarnDialog from "@/components/panel/task/PreTaskWarnDialog.vue"
import { resolveInterfaceText } from "@/utils/interface/content"
import { hasPretaskAck, setPretaskAck } from "@/utils/pretaskWarning"

const { embedded = false, controllerName = null, resourceName = null } = defineProps<Props>()

defineOptions({ inheritAttrs: false })

interface Props {
  embedded?: boolean
  controllerName?: string | null
  resourceName?: string | null
}

interface PretaskListItem {
  pretask: Pretask
  key: string
  displayName: string
  compatible: boolean
  enabled: boolean
}

const modelValue = defineModel<PreTaskCommand[]>()
const interfaceStore = useInterfaceStore()
const settingsStore = useSettingsStore()
const showWarn = ref(false)

const expanded = ref(embedded)
const expandedNames = computed<string[]>({
  get: () => (expanded.value ? ["pre-tasks"] : []),
  set: (names) => {
    expanded.value = names.includes("pre-tasks")
  },
})

const preTasks = computed<PreTaskCommand[]>({
  get: () => modelValue.value || [],
  set: (value) => (modelValue.value = value),
})

const piPretasks = computed<PretaskListItem[]>(() =>
  interfaceStore.getPretasks.map((pretask) => {
    const key = pretaskKey(pretask)
    return {
      pretask,
      key,
      displayName: resolveInterfaceText(pretask.label, pretask.name || pretask.exec),
      compatible: interfaceStore.isPretaskCompatible(pretask, controllerName, resourceName),
      enabled: settingsStore.settings.pretaskEnabled[key] !== false,
    }
  }),
)

function addPreTask() {
  preTasks.value = [
    ...preTasks.value,
    {
      id: crypto.randomUUID(),
      command: "",
      enabled: true,
      timeout: 30,
    },
  ]
}

function handleAdd() {
  if (hasPretaskAck()) {
    addPreTask()
    return
  }
  showWarn.value = true
}

function handleWarnConfirm(dontRemind: boolean) {
  if (dontRemind) {
    setPretaskAck()
  }
  addPreTask()
}

function handleDelete(index: number) {
  preTasks.value = preTasks.value.filter((_, i) => i !== index)
}
</script>
