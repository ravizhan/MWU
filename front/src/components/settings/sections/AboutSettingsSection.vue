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

    <NDivider />

    <NButton type="warning" size="small" @click="handleResetSettings">
      {{ t("settings.about.reset") }}
    </NButton>
  </div>
</template>

<script setup lang="ts">
import { computed, h, type Component } from "vue"
import { useI18n } from "vue-i18n"
import { NButton, NIcon } from "naive-ui"
import type { DataTableColumns } from "naive-ui"
import { BugOutline, LogoGithub } from "@vicons/ionicons5"
import { showGlobalMessage } from "@/services/feedback/message"
import { useInterfaceStore, useSettingsStore } from "@/stores"

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
        showGlobalMessage("success", t("settings.about.resetSuccess"))
      }
    })
  }
}
</script>
