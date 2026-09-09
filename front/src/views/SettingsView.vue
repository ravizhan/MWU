<template>
  <div class="flex flex-col lg:flex-row gap-4 max-w-screen-xl mx-auto">
    <!-- Left sidebar: settings sections -->
    <div class="lg:w-64 shrink-0">
      <!-- Responsive wrappers are plain divs: naive's .n-menu/.n-tabs set their own
           display (unlayered, beats Tailwind's layered hidden/lg:block), so the
           breakpoint classes must live on the wrapper, not the naive component. -->
      <div class="hidden lg:block">
        <NMenu v-model:value="activeSection" mode="vertical" :options="menuOptions" />
      </div>
      <div class="lg:hidden">
        <NTabs v-model:value="activeSection" type="bar">
          <NTab v-for="section in sections" :key="section.id" :name="section.id">
            {{ section.label }}
          </NTab>
        </NTabs>
      </div>
    </div>

    <!-- Right: active section content -->
    <div class="flex-1 min-w-0">
      <!-- Update -->
      <NCard v-if="activeSection === 'update'">
        <template #header>
          <h2 class="flex items-center gap-2 text-lg font-semibold">
            <NIcon size="20" style="color: var(--primary-color)">
              <ArrowUpCircleOutline />
            </NIcon>
            {{ t("settings.update.title") }}
          </h2>
        </template>
        <UpdateSettingsSection @show-update="handleShowUpdate" />
      </NCard>

      <!-- PI task settings -->
      <NCard v-if="activeSection === 'taskSettings'">
        <template #header>
          <h2 class="flex items-center gap-2 text-lg font-semibold">
            <NIcon size="20" style="color: var(--primary-color)">
              <ConstructOutline />
            </NIcon>
            {{ t("settings.anchor.taskSettings") }}
          </h2>
        </template>
        <TaskSettingsSection />
      </NCard>

      <!-- Runtime -->
      <NCard v-if="activeSection === 'runtime'">
        <template #header>
          <h2 class="flex items-center gap-2 text-lg font-semibold">
            <NIcon size="20" style="color: var(--primary-color)">
              <SettingsOutline />
            </NIcon>
            {{ t("settings.runtime.title") }}
          </h2>
        </template>
        <RuntimeSettingsSection />
      </NCard>

      <!-- UI -->
      <NCard v-if="activeSection === 'ui'">
        <template #header>
          <h2 class="flex items-center gap-2 text-lg font-semibold">
            <NIcon size="20" style="color: var(--primary-color)">
              <ColorPaletteOutline />
            </NIcon>
            {{ t("settings.ui.title") }}
          </h2>
        </template>
        <UISettingsSection />
      </NCard>

      <!-- Notification -->
      <NCard v-if="activeSection === 'notification'">
        <template #header>
          <h2 class="flex items-center gap-2 text-lg font-semibold">
            <NIcon size="20" style="color: var(--primary-color)">
              <NotificationsOutline />
            </NIcon>
            {{ t("settings.notification.title") }}
          </h2>
        </template>
        <NotificationSettingsSection />
      </NCard>

      <!-- About -->
      <!-- Telemetry -->
      <NCard v-if="activeSection === 'telemetry'">
        <template #header>
          <h2 class="flex items-center gap-2 text-lg font-semibold">
            <NIcon size="20" style="color: var(--primary-color)">
              <StatsChartOutline />
            </NIcon>
            {{ t("telemetry.settings.title") }}
          </h2>
        </template>
        <TelemetrySettingsSection />
      </NCard>

      <NCard v-if="activeSection === 'about'">
        <template #header>
          <h2 class="flex items-center gap-2 text-lg font-semibold">
            <NIcon size="20" style="color: var(--primary-color)">
              <InformationCircleOutline />
            </NIcon>
            {{ t("settings.about.title") }}
          </h2>
        </template>
        <AboutSettingsSection />
      </NCard>
    </div>

    <UpdateDialog v-model:show="showUpdateDialog" :update-info="updateInfo" />
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref, type Component } from "vue"
import { useI18n } from "vue-i18n"
import { NIcon } from "naive-ui"
import type { MenuOption } from "naive-ui"
import {
  ArrowUpCircleOutline,
  ColorPaletteOutline,
  ConstructOutline,
  InformationCircleOutline,
  NotificationsOutline,
  SettingsOutline,
  StatsChartOutline,
} from "@vicons/ionicons5"
import UpdateDialog from "@/components/settings/dialogs/UpdateDialog.vue"
import AboutSettingsSection from "@/components/settings/sections/AboutSettingsSection.vue"
import NotificationSettingsSection from "@/components/settings/sections/NotificationSettingsSection.vue"
import RuntimeSettingsSection from "@/components/settings/sections/RuntimeSettingsSection.vue"
import TaskSettingsSection from "@/components/settings/sections/TaskSettingsSection.vue"
import UISettingsSection from "@/components/settings/sections/UISettingsSection.vue"
import UpdateSettingsSection from "@/components/settings/sections/UpdateSettingsSection.vue"
import TelemetrySettingsSection from "@/components/settings/sections/TelemetrySettingsSection.vue"
import type { UpdateInfo } from "@/services/api"
import { useInterfaceStore } from "@/stores"

type SettingsSectionKey =
  | "update"
  | "taskSettings"
  | "runtime"
  | "ui"
  | "notification"
  | "telemetry"
  | "about"

interface SettingsSection {
  id: SettingsSectionKey
  label: string
  icon: Component
}

const { t } = useI18n()
const interfaceStore = useInterfaceStore()
const activeSection = ref<SettingsSectionKey>("update")
const showUpdateDialog = ref(false)
const updateInfo = ref<UpdateInfo | null>(null)

const sections = computed<SettingsSection[]>(() => {
  const values: SettingsSection[] = [
    { id: "update", label: t("settings.anchor.update"), icon: ArrowUpCircleOutline },
  ]
  if (interfaceStore.getSettingSections.length > 0) {
    values.push({
      id: "taskSettings",
      label: t("settings.anchor.taskSettings"),
      icon: ConstructOutline,
    })
  }
  values.push(
    { id: "runtime", label: t("settings.anchor.runtime"), icon: SettingsOutline },
    { id: "ui", label: t("settings.anchor.ui"), icon: ColorPaletteOutline },
    {
      id: "notification",
      label: t("settings.anchor.notification"),
      icon: NotificationsOutline,
    },
    { id: "telemetry", label: t("telemetry.settings.title"), icon: StatsChartOutline },
    { id: "about", label: t("settings.anchor.about"), icon: InformationCircleOutline },
  )
  return values
})

const menuOptions = computed<MenuOption[]>(() =>
  sections.value.map((section) => ({
    key: section.id,
    label: section.label,
    icon: () => h(NIcon, { size: 18 }, { default: () => h(section.icon) }),
  })),
)

function handleShowUpdate(info: UpdateInfo) {
  updateInfo.value = info
  showUpdateDialog.value = true
}
</script>
