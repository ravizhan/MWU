<template>
  <NModal
    :show="show"
    preset="card"
    :title="
      kind === 'file' ? t('option.pathPicker.fileTitle') : t('option.pathPicker.directoryTitle')
    "
    :style="{ width: 'min(92vw, 36rem)' }"
    @update:show="emit('update:show', $event)"
  >
    <NSpin :show="loading">
      <div class="max-h-[60vh] min-h-32 overflow-y-auto">
        <NTree
          v-if="nodes.length > 0"
          block-line
          :data="nodes"
          :selected-keys="selectedKeys"
          :on-load="loadChildren"
          :override-default-node-click-behavior="clickBehavior"
          @update:selected-keys="selectedKeys = $event"
        />
        <NEl v-else-if="!loading" tag="div" class="py-6 text-center text-sm opacity-50">
          {{ t("panel.empty") }}
        </NEl>
      </div>
    </NSpin>
    <template #action>
      <div class="flex items-center justify-between gap-3">
        <span class="min-w-0 truncate text-xs opacity-60">{{ selectedPath }}</span>
        <NSpace justify="end" :wrap="false">
          <NButton @click="emit('update:show', false)">{{ t("common.cancel") }}</NButton>
          <NButton type="primary" :disabled="!selectedPath" @click="confirm">
            {{ t("common.confirm") }}
          </NButton>
        </NSpace>
      </div>
    </template>
  </NModal>
</template>

<script setup lang="ts">
import { computed, h, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { NIcon, type TreeOption, type TreeOverrideNodeClickBehavior } from "naive-ui"
import { DocumentOutline, FolderOutline } from "@vicons/ionicons5"
import { listProjectDir, type ProjectEntry } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"

const { show, kind } = defineProps<{
  show: boolean
  kind: "file" | "directory"
}>()

const emit = defineEmits<{
  (event: "update:show", value: boolean): void
  (event: "select", path: string): void
}>()

const { t } = useI18n()

const nodes = ref<TreeOption[]>([])
const selectedKeys = ref<string[]>([])
const loading = ref(false)

const selectedPath = computed(() => selectedKeys.value[0] ?? "")

function toNode(entry: ProjectEntry): TreeOption {
  return {
    key: entry.path,
    label: entry.name,
    // Unloaded directories (isLeaf false, no children) are expanded lazily via on-load.
    isLeaf: !entry.is_dir,
    prefix: () =>
      h(NIcon, null, { default: () => h(entry.is_dir ? FolderOutline : DocumentOutline) }),
  }
}

async function fetchNodes(path: string): Promise<TreeOption[] | null> {
  const [entries, error] = await tryCatch(() => listProjectDir(path))
  if (error) {
    showGlobalMessage("error", t("option.pathPicker.loadFailed", { message: error.message }))
    return null
  }
  return entries.filter((entry) => kind === "file" || entry.is_dir).map(toNode)
}

async function loadChildren(node: TreeOption): Promise<boolean> {
  const children = await fetchNodes(String(node.key))
  if (!children) return false
  node.children = children
  return true
}

const clickBehavior: TreeOverrideNodeClickBehavior = ({ option }) =>
  kind === "file" && !option.isLeaf ? "toggleExpand" : "default"

function confirm(): void {
  emit("select", selectedPath.value)
  emit("update:show", false)
}

watch(
  () => show,
  async (visible) => {
    if (!visible) return
    selectedKeys.value = []
    nodes.value = []
    loading.value = true
    nodes.value = (await fetchNodes("")) ?? []
    loading.value = false
  },
)
</script>
