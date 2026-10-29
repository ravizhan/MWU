<template>
  <div class="space-y-4">
    <div class="overflow-x-auto">
      <NDataTable
        :columns="columns"
        :data="rows"
        size="small"
        :bordered="false"
        :single-line="false"
      />
    </div>

    <div
      v-if="telemetryVisible"
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.about.telemetry") }}
      </label>
      <div class="space-y-1">
        <NSwitch
          :value="telemetryStatus?.enabled ?? false"
          :aria-label="t('settings.about.telemetry')"
          :disabled="telemetryDisabled"
          @update:value="handleTelemetryChange"
        />
        <div v-if="telemetryDisabled" class="text-xs opacity-60">
          {{ t("settings.about.telemetryDisabledDev") }}
        </div>
        <div class="text-xs opacity-60">
          {{ t("settings.about.telemetryDesc") }}
        </div>
      </div>
    </div>

    <NDivider />

    <NButton type="warning" size="small" @click="handleResetSettings">
      {{ t("settings.about.reset") }}
    </NButton>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, type Component } from "vue"
import { useI18n } from "vue-i18n"
import { NButton, NIcon } from "naive-ui"
import type { DataTableColumns } from "naive-ui"
import { BugOutline, LogoGithub } from "@vicons/ionicons5"
import { getTelemetryStatusApi, type TelemetryStatus } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useInterfaceStore, useSettingsStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"

interface AboutRow {
  label: string
  value: string
  href?: string
  icon?: Component
}

const DEFAULT_GITHUB = "https://github.com/ravizhan/MWU"

/** interface.json 的 `github` 是仓库 URL；作者取 `owner/repo` 的 owner。 */
function githubOwner(github: string): string {
  const segments = github.replace(/\/+$/, "").split("/")
  return segments.length >= 2 ? segments[segments.length - 2] : ""
}

const { t } = useI18n()
const interfaceStore = useInterfaceStore()
const settingsStore = useSettingsStore()
const telemetryStatus = ref<TelemetryStatus | null>(null)

const telemetryVisible = computed(
  () => telemetryStatus.value !== null && telemetryStatus.value.blocked_reason !== "no_dsn",
)

const telemetryDisabled = computed(
  () =>
    telemetryStatus.value?.blocked_reason === "dev_build" ||
    telemetryStatus.value?.blocked_reason === "debug_resource",
)

/** 开关反映后端实际初始化状态；同意已持久化但初始化失败时显示为关闭。 */
async function refreshTelemetryStatus() {
  const [data, err] = await tryCatch(() => getTelemetryStatusApi())
  if (err) return
  telemetryStatus.value = data
}

onMounted(refreshTelemetryStatus)

const rows = computed<AboutRow[]>(() => {
  const model = interfaceStore.interface
  const github = (model.github || DEFAULT_GITHUB).replace(/\/+$/, "")
  const author = githubOwner(github)

  const result: AboutRow[] = [
    {
      label: t("settings.about.version"),
      value: model.version || t("common.unknown"),
    },
    {
      label: t("settings.about.author"),
      value: author || t("common.unknown"),
      href: author ? `https://github.com/${author}` : undefined,
      icon: LogoGithub,
    },
    {
      label: t("settings.about.license"),
      value: model.license || "MIT",
    },
    {
      label: t("settings.about.homepage"),
      value: github,
      href: github,
      icon: LogoGithub,
    },
    {
      label: t("settings.about.issue"),
      value: t("settings.about.githubIssues"),
      href: `${github}/issues`,
      icon: BugOutline,
    },
  ]

  if (model.contact) {
    result.push({
      label: t("settings.about.contact"),
      value: model.contact,
    })
  }

  result.push({
    label: t("settings.about.description"),
    value: model.description || t("settings.about.defaultDescription"),
  })

  return result
})

const columns = computed<DataTableColumns<AboutRow>>(() => [
  {
    key: "label",
    title: "",
    width: 140,
    render: (row) => h("span", { class: "font-medium" }, row.label),
  },
  {
    key: "value",
    title: "",
    render: (row) => {
      if (!row.href) {
        return row.value
      }

      return h(
        NButton,
        {
          text: true,
          type: "primary",
          tag: "a",
          href: row.href,
          target: "_blank",
          rel: "noopener noreferrer",
        },
        {
          icon: () => h(NIcon, { size: 18 }, { default: () => h(row.icon ?? LogoGithub) }),
          default: () => row.value,
        },
      )
    },
  },
])

function handleResetSettings() {
  if (confirm(t("settings.about.resetConfirm"))) {
    void settingsStore.resetSettings().then((success) => {
      if (success) {
        void refreshTelemetryStatus()
        showGlobalMessage("success", t("settings.about.resetSuccess"))
      }
    })
  }
}

function handleTelemetryChange(value: boolean) {
  void settingsStore.updateSetting("telemetry", "helpImproveSoftware", value).then((success) => {
    if (success) {
      void refreshTelemetryStatus()
    }
  })
}
</script>
