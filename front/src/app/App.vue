<template>
  <NConfigProvider
    :theme="theme"
    :theme-overrides="themeOverrides"
    :locale="locale"
    :date-locale="dateLocale"
  >
    <NMessageProvider placement="top">
      <NDialogProvider>
        <FeedbackBridge />
        <FocusInteractionBridge />
        <NEl
          tag="div"
          class="min-h-screen transition-colors duration-300 overflow-x-hidden"
          style="background-color: var(--body-color)"
        >
          <!-- Navbar -->
          <AppNavbar
            :name="resolvedTitle"
            :is-dark="settingsStore.isDarkMode"
            :menu-value="menuValue"
            :menu-options="menuOptions"
            @select="onMenuSelect"
            @toggle-dark="toggleDarkMode"
          />

          <!-- Main content -->
          <main class="pb-24 lg:pb-4 transition-all duration-300 overflow-x-hidden">
            <div class="w-full mx-auto px-3 py-4">
              <AppMain />
            </div>
          </main>

          <!-- Dock nav (mobile) -->
          <AppDock :items="navItems" :active-key="menuValue" @select="onMenuSelect" />

          <!-- Update dialog -->
          <UpdateDialog v-model:show="showUpdateDialog" :update-info="updateInfo" />

          <!-- Welcome dialog (per name+locale+content fingerprint) -->
          <NModal v-model:show="showWelcome" preset="card" :title="resolvedTitle" class="max-w-2xl">
            <div class="markdown-body whitespace-pre-wrap">{{ resolvedWelcome }}</div>
            <template #footer>
              <div class="flex justify-end">
                <NButton size="small" @click="closeWelcome">{{ t("common.confirm") }}</NButton>
              </div>
            </template>
          </NModal>

          <!-- Administrator elevation confirm (permission_required) -->
          <ElevationDialog />

          <!-- Telemetry consent (first run, per target) -->
          <TelemetryConsentDialog />
        </NEl>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watchEffect } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useI18n } from "vue-i18n"
import { NIcon } from "naive-ui"
import type { MenuOption } from "naive-ui"
import {
  DocumentTextOutline,
  HomeOutline,
  ListOutline,
  SettingsOutline,
  TimeOutline,
} from "@vicons/ionicons5"
import markdownAutoHref from "github-markdown-css/github-markdown.css?url"
import markdownDarkHref from "github-markdown-css/github-markdown-dark.css?url"
import markdownLightHref from "github-markdown-css/github-markdown-light.css?url"
import AppDock from "@/app/AppDock.vue"
import AppMain from "@/app/AppMain.vue"
import AppNavbar from "@/app/AppNavbar.vue"
import UpdateDialog from "@/components/settings/dialogs/UpdateDialog.vue"
import { checkUpdateApi, type UpdateInfo } from "@/services/api"
import FeedbackBridge from "@/services/feedback/FeedbackBridge.vue"
import FocusInteractionBridge from "@/components/common/FocusInteractionBridge.vue"
import ElevationDialog from "@/components/common/ElevationDialog.vue"
import TelemetryConsentDialog from "@/components/common/TelemetryConsentDialog.vue"
import { useNaiveTheme } from "@/app/theme"
import { useInterfaceStore, useSettingsStore, useTaskConfigStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"
import { telemetryConsentVisible } from "@/services/telemetry/consentState"
import { useInterfaceMetadata } from "@/app/useInterfaceMetadata"

const { t, locale: i18nLocale } = useI18n()
const route = useRoute()
const router = useRouter()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const settingsStore = useSettingsStore()

const { theme, themeOverrides, locale, dateLocale } = useNaiveTheme()
const { resolvedTitle, resolvedWelcome, resolvedIconUrl, welcomeShouldShow, markWelcomeShown } =
  useInterfaceMetadata(i18nLocale)
const showWelcome = ref(false)

function closeWelcome(): void {
  showWelcome.value = false
  markWelcomeShown()
}

// 界面水合后：指纹变化时展示欢迎页。
// 弹窗顺序：运行 modal（阻塞流水线，必须最上层）→ 遥测授权 → 欢迎页；
// 授权未关闭前暂缓欢迎页，授权关闭后 watchEffect 重新触发。
watchEffect(() => {
  if (welcomeShouldShow.value && !telemetryConsentVisible.value) {
    showWelcome.value = true
  }
})

// favicon 跟随 PI icon（解析后资源 URL）；未配置时保留默认
watchEffect(() => {
  const iconUrl = resolvedIconUrl.value
  if (!iconUrl) {
    return
  }
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (!link) {
    link = document.createElement("link")
    link.rel = "icon"
    document.head.appendChild(link)
  }
  if (link.href !== new URL(iconUrl, document.baseURI).href) {
    link.href = iconUrl
  }
})

const navItems = computed(() => [
  { key: "home", label: t("nav.home"), iconComponent: HomeOutline },
  { key: "tasks", label: t("nav.tasks"), iconComponent: ListOutline },
  {
    key: "logs",
    label: t("nav.logs"),
    iconComponent: DocumentTextOutline,
  },
  {
    key: "routines",
    label: t("nav.routines"),
    iconComponent: TimeOutline,
  },
  {
    key: "settings",
    label: t("nav.settings"),
    iconComponent: SettingsOutline,
  },
])

const menuValue = computed(() => (typeof route.name === "string" ? route.name : ""))

const menuOptions = computed<MenuOption[]>(() =>
  navItems.value.map((item) => ({
    label: item.label,
    key: item.key,
    icon: () => h(NIcon, null, { default: () => h(item.iconComponent) }),
  })),
)

function onMenuSelect(key: string) {
  void router.push({ name: key })
}

function toggleDarkMode() {
  const newValue = !settingsStore.isDarkMode
  void settingsStore.updateSetting("ui", "darkMode", newValue)
}

const showUpdateDialog = ref(false)
const updateInfo = ref<UpdateInfo | null>(null)

function ensureMarkdownStylesheet(href: string) {
  const id = "github-markdown-theme"
  const existing = document.getElementById(id)
  const link = existing instanceof HTMLLinkElement ? existing : document.createElement("link")
  if (link.id !== id) link.id = id
  if (link.rel !== "stylesheet") link.rel = "stylesheet"
  if (!link.parentNode) document.head.appendChild(link)
  if (link.href !== href) link.href = href
}

const checkForUpdatesOnLoad = async () => {
  if (sessionStorage.getItem("mwu-update-checked")) {
    return
  }

  if (!settingsStore.settings.update || !settingsStore.settings.update.autoUpdate) {
    return
  }

  const [result, err] = await tryCatch(() => checkUpdateApi())
  if (err) {
    console.error("Failed to check for updates on load:", err)
    return
  }
  sessionStorage.setItem("mwu-update-checked", "true")
  if (result.status === "success" && result.update_info?.is_update_available) {
    updateInfo.value = result.update_info
    showUpdateDialog.value = true
  }
}

onMounted(async () => {
  settingsStore.initSystemThemeListener()
  await interfaceStore.setInterface()
  await configStore.loadConfig()
  if (!settingsStore.initialized) {
    await settingsStore.fetchSettings()
  }
  // 服务端 ui.language 为权威：水合后同步 vue-i18n locale
  const serverLanguage = settingsStore.settings.ui.language
  if (serverLanguage === "zh-CN" || serverLanguage === "en-US") {
    i18nLocale.value = serverLanguage
    localStorage.setItem("locale", serverLanguage)
  }

  void checkForUpdatesOnLoad()
})

function markdownHref(mode: boolean | "auto"): string {
  if (mode === "auto") {
    return markdownAutoHref
  }
  if (mode) {
    return markdownDarkHref
  }
  return markdownLightHref
}

watchEffect(() => {
  const mode = settingsStore.settings.ui.darkMode
  ensureMarkdownStylesheet(markdownHref(mode))
})
</script>
