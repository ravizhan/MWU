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
          <div
            v-for="(item, index) in piPretasks"
            :key="`${item.pretask.exec}-${index}`"
            class="space-y-1"
          >
            <NTooltip :disabled="!item.pretask.description && item.compatible" :max-width="320">
              <template #trigger>
                <NEl
                  tag="div"
                  class="px-3 py-2 rounded-lg border border-solid text-sm font-medium"
                  :class="{ 'opacity-50': !item.compatible }"
                  :style="{
                    borderColor: 'var(--divider-color)',
                    background: 'var(--card-color)',
                  }"
                >
                  {{ item.displayName }}
                </NEl>
              </template>
              <div class="space-y-1">
                <div v-if="item.pretask.description">
                  {{ resolveInterfaceText(item.pretask.description, item.pretask.description) }}
                </div>
                <div v-if="!item.compatible">
                  {{ $t("panel.piPretask.incompatible") }}
                </div>
              </div>
            </NTooltip>
            <NEl
              v-if="item.pretask.option?.length"
              tag="div"
              class="overflow-hidden rounded-lg border border-solid"
              style="border-color: var(--divider-color)"
            >
              <TaskSettingOptionRow v-for="n in item.pretask.option" :key="n" :name="n" />
            </NEl>
          </div>

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
import { useInterfaceStore } from "@/stores"
import type { Pretask } from "@/types/interfaceModel"
import type { PreTaskCommand } from "@/types/taskConfigModel"
import PreTaskHeader from "@/components/panel/task/PreTaskHeader.vue"
import PreTaskRow from "@/components/panel/task/PreTaskRow.vue"
import PreTaskToolbar from "@/components/panel/task/PreTaskToolbar.vue"
import PreTaskWarnDialog from "@/components/panel/task/PreTaskWarnDialog.vue"
import { resolveInterfaceText } from "@/utils/interface/content"
import { hasPretaskAck, setPretaskAck } from "@/utils/pretaskWarning"

defineOptions({ inheritAttrs: false })

interface Props {
  embedded?: boolean
  controllerName?: string | null
  resourceName?: string | null
}

interface PretaskListItem {
  pretask: Pretask
  displayName: string
  compatible: boolean
}

const { embedded = false, controllerName = null, resourceName = null } = defineProps<Props>()

const modelValue = defineModel<PreTaskCommand[]>()
const interfaceStore = useInterfaceStore()
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
  interfaceStore.getPretasks.map((pretask) => ({
    pretask,
    displayName: resolveInterfaceText(pretask.label, pretask.name || pretask.exec),
    compatible: interfaceStore.isPretaskCompatible(pretask, controllerName, resourceName),
  })),
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
