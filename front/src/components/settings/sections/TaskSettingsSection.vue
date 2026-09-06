<template>
  <NCollapse :default-expanded-names="defaultExpandedNames" arrow-placement="right">
    <NCollapseItem v-for="section in sections" :key="section.name" :name="section.name">
      <template #header>
        <div class="flex min-w-0 items-center gap-2">
          <img
            v-if="resolveSectionIcon(section.icon)"
            :src="resolveSectionIcon(section.icon)"
            alt=""
            class="h-5 w-5 shrink-0 object-contain"
          />
          <div class="min-w-0">
            <div class="font-medium">{{ resolveSectionLabel(section) }}</div>
            <div v-if="section.description" class="text-xs opacity-60">
              {{ resolveSectionDescription(section.description) }}
            </div>
          </div>
        </div>
      </template>

      <NEl
        v-if="availableOptionNames(section).length > 0"
        tag="div"
        class="overflow-hidden rounded-lg border border-solid"
        style="border-color: var(--divider-color)"
      >
        <TaskSettingOptionRow
          v-for="optionName in availableOptionNames(section)"
          :key="optionName"
          :name="optionName"
        />
      </NEl>
      <div v-else class="py-6 text-center text-sm opacity-50">
        {{ t("settings.taskSettings.empty") }}
      </div>
    </NCollapseItem>
    <NCollapseItem v-if="uncoveredOptionNames.length > 0" name="__uncovered__">
      <template #header>
        <div class="flex min-w-0 items-center gap-2">
          <div class="min-w-0">
            <div class="font-medium">{{ t("settings.taskSettings.uncovered") }}</div>
            <div class="text-xs opacity-60">
              {{ t("settings.taskSettings.uncoveredDescription") }}
            </div>
          </div>
        </div>
      </template>

      <NEl
        tag="div"
        class="overflow-hidden rounded-lg border border-solid"
        style="border-color: var(--divider-color)"
      >
        <TaskSettingOptionRow
          v-for="optionName in uncoveredOptionNames"
          :key="optionName"
          :name="optionName"
        />
      </NEl>
    </NCollapseItem>
  </NCollapse>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "@/stores"
import type { SettingSection } from "@/types/interfaceModel"
import { resolveInterfaceAssetUrl, resolveInterfaceText } from "@/utils/interface/content"
import TaskSettingOptionRow from "@/components/settings/sections/TaskSettingOptionRow.vue"

const { locale, t } = useI18n()
const interfaceStore = useInterfaceStore()
const sections = computed(() => interfaceStore.getSettingSections)
// 未被任何 setting 分区覆盖的全局/资源/控制器级 option 编辑入口
const uncoveredOptionNames = computed<string[]>(() => {
  const model = interfaceStore.interface
  if (!model) {
    return []
  }
  const covered = new Set<string>()
  for (const section of model.setting ?? []) {
    for (const optionName of section.option ?? []) {
      covered.add(optionName)
    }
  }
  const candidates = [
    ...(model.global_option ?? []),
    ...(model.resource ?? []).flatMap((item) => item.option ?? []),
    ...(model.controller ?? []).flatMap((item) => item.option ?? []),
  ]
  const seen = new Set<string>()
  const result: string[] = []
  for (const optionName of candidates) {
    if (
      covered.has(optionName) ||
      seen.has(optionName) ||
      model.option?.[optionName] === undefined
    ) {
      continue
    }
    seen.add(optionName)
    result.push(optionName)
  }
  return result
})
const defaultExpandedNames = computed(() =>
  sections.value
    .filter((section) => section.default_expand !== false)
    .map((section) => section.name),
)

function availableOptionNames(section: SettingSection): string[] {
  return (section.option || []).filter(
    (optionName) => interfaceStore.interface.option?.[optionName] !== undefined,
  )
}

function resolveSectionLabel(section: SettingSection): string {
  return resolveInterfaceText(interfaceStore.interface, locale.value, section.label, section.name)
}

function resolveSectionDescription(description: string): string {
  return resolveInterfaceText(interfaceStore.interface, locale.value, description, description)
}

function resolveSectionIcon(icon: string | undefined): string | undefined {
  return resolveInterfaceAssetUrl(interfaceStore.interface, locale.value, icon)
}
</script>
