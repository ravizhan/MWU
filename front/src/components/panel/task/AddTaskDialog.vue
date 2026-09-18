<template>
  <NModal
    v-model:show="showDialog"
    preset="card"
    :title="t('panel.addTask.title')"
    :style="{ width: 'min(92vw, 40rem)' }"
  >
    <div class="flex flex-col gap-3">
      <NInput
        v-model:value="query"
        size="small"
        clearable
        :placeholder="t('panel.addTask.searchPlaceholder')"
      >
        <template #prefix>
          <NIcon><SearchOutline /></NIcon>
        </template>
      </NInput>
      <div class="max-h-[60vh] overflow-y-auto">
        <NCollapse
          v-if="filteredSections && filteredSections.length > 0"
          :expanded-names="effectiveExpandedNames"
          arrow-placement="right"
          @update:expanded-names="handleExpandedUpdate"
        >
          <NCollapseItem v-for="section in filteredSections" :key="section.key" :name="section.key">
            <template #header>
              <AddTaskGroupHeader :section="section" />
            </template>
            <div class="flex flex-col gap-1.5">
              <AddTaskRow
                v-for="task in section.tasks"
                :key="task.name"
                :task="task"
                :controller-name="controllerName"
                :resource-name="resourceName"
                @add="emit('add', $event)"
              />
            </div>
          </NCollapseItem>
        </NCollapse>
        <NEl v-else-if="filteredSections" tag="div" class="py-6 text-center text-sm opacity-50">
          {{ t("panel.empty") }}
        </NEl>
        <template v-else>
          <div v-if="filteredFlatTasks.length > 0" class="flex flex-col gap-1.5">
            <AddTaskRow
              v-for="task in filteredFlatTasks"
              :key="task.name"
              :task="task"
              :controller-name="controllerName"
              :resource-name="resourceName"
              @add="emit('add', $event)"
            />
          </div>
          <NEl v-else tag="div" class="py-6 text-center text-sm opacity-50">
            {{ t("panel.empty") }}
          </NEl>
        </template>
      </div>
    </div>
  </NModal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { SearchOutline } from "@vicons/ionicons5"
import { useInterfaceStore } from "@/stores"
import type { Task } from "@/types/interfaceModel"
import { buildTaskSections } from "@/utils/task-config/order"
import { resolveInterfaceText } from "@/utils/interface/content"
import AddTaskGroupHeader from "@/components/panel/task/AddTaskGroupHeader.vue"
import AddTaskRow from "@/components/panel/task/AddTaskRow.vue"

interface Props {
  controllerName?: string | null
  resourceName?: string | null
}

interface Emits {
  (e: "add", name: string): void
}

const { controllerName = null, resourceName = null } = defineProps<Props>()
const emit = defineEmits<Emits>()
const showDialog = defineModel<boolean>("show", { required: true })

const { locale, t } = useI18n()
const interfaceStore = useInterfaceStore()

const query = ref("")
watch(showDialog, (open) => {
  if (!open) {
    query.value = ""
  }
})

const allTasks = computed(() => interfaceStore.interface.task ?? [])
const sections = computed(() => buildTaskSections(allTasks.value, interfaceStore.getGroups))

const normalizedQuery = computed(() => query.value.trim().toLowerCase())

function taskMatchesQuery(task: Task): boolean {
  const q = normalizedQuery.value
  if (!q) return true
  const label = resolveInterfaceText(interfaceStore.interface, locale.value, task.label, task.name)
  return label.toLowerCase().includes(q) || task.name.toLowerCase().includes(q)
}

// 搜索激活时过滤任务并省略空分组
const filteredSections = computed(() => {
  const base = sections.value
  if (!base) return null
  if (!normalizedQuery.value) return base
  return base
    .map((section) => ({ ...section, tasks: section.tasks.filter(taskMatchesQuery) }))
    .filter((section) => section.tasks.length > 0)
})

// 无分组信息时的平铺列表
const filteredFlatTasks = computed(() => allTasks.value.filter(taskMatchesQuery))

// 展开状态：声明组遵循 default_expand（缺省展开），未声明组与未分组默认展开；
// sections 变化时修剪失效 key、为新 key 注入默认值
const expandedNames = ref<string[]>([])
watch(
  sections,
  (newSections) => {
    if (!newSections) {
      expandedNames.value = []
      return
    }
    const validKeys = new Set(newSections.map((section) => section.key))
    const kept = expandedNames.value.filter((key) => validKeys.has(key))
    const keptSet = new Set(kept)
    for (const section of newSections) {
      if (keptSet.has(section.key)) continue
      if (section.kind !== "declared" || section.group?.default_expand !== false) {
        kept.push(section.key)
        keptSet.add(section.key)
      }
    }
    expandedNames.value = kept
  },
  { immediate: true },
)

// 搜索激活时强制展开全部分组，但不写回用户展开状态
const effectiveExpandedNames = computed(() => {
  if (normalizedQuery.value && filteredSections.value) {
    return filteredSections.value.map((section) => section.key)
  }
  return expandedNames.value
})

function handleExpandedUpdate(names: Array<string | number>) {
  if (normalizedQuery.value) return
  expandedNames.value = names.filter((name): name is string => typeof name === "string")
}
</script>
