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
        <FocusDialogHost />
        <NEl
          tag="div"
          class="min-h-screen transition-colors duration-300 overflow-x-hidden"
          style="background-color: var(--body-color)"
        >
          <!-- Navbar -->
          <AppNavbar
            :name="name"
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

          <!-- Welcome dialog -->
          <WelcomeDialog
            v-model:show="showWelcomeDialog"
            :contents="welcomeContents"
            @confirm="confirmWelcome"
          />
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
import WelcomeDialog from "@/components/common/WelcomeDialog.vue"
import UpdateDialog from "@/components/settings/dialogs/UpdateDialog.vue"
import { checkUpdateApi, type UpdateInfo } from "@/services/api"
import FeedbackBridge from "@/services/feedback/FeedbackBridge.vue"
import FocusDialogHost from "@/services/feedback/FocusDialogHost.vue"
import { useNaiveTheme } from "@/app/theme"
import { useInterfaceStore, useSettingsStore, useTaskConfigStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"
import {
  resolveInterfaceAssetUrl,
  resolveInterfaceDocumentContent,
  resolveInterfaceText,
  setInterfaceTranslations,
} from "@/utils/interface/content"
import { welcomeFingerprint } from "@/utils/interface/welcome"

const { t, locale: uiLocale } = useI18n()
const route = useRoute()
const router = useRouter()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const settingsStore = useSettingsStore()
const iface = computed(() => interfaceStore.interface)
const name = computed(() => resolveInterfaceText(iface.value.label, iface.value.name || "MWU"))

watchEffect(() => {
  setInterfaceTranslations(interfaceStore.interface.translations, uiLocale.value)
})

watchEffect(() => {
  const title = resolveInterfaceText(iface.value.title)
  document.title = title || [name.value, iface.value.version].filter(Boolean).join(" ")
})

watchEffect(() => {
  const href = resolveInterfaceAssetUrl(iface.value.icon)
  if (!href) return
  const iconLink = document.querySelector<HTMLLinkElement>("link[rel='icon']")
  if (iconLink) iconLink.href = href
})

const { theme, themeOverrides, locale, dateLocale } = useNaiveTheme()

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
const showWelcomeDialog = ref(false)
const welcomeContents = ref<string[]>([])

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

const confirmWelcome = () => {
  localStorage.setItem("mwu.welcome.ack", welcomeFingerprint(welcomeContents.value))
  showWelcomeDialog.value = false
  void checkForUpdatesOnLoad()
}

onMounted(async () => {
  settingsStore.initSystemThemeListener()
  await interfaceStore.setInterface()
  await configStore.loadConfig()
  if (!settingsStore.initialized) {
    await settingsStore.fetchSettings()
  }

  const welcome = interfaceStore.interface.welcome
  const welcomeEntries = typeof welcome === "string" ? [welcome] : (welcome ?? [])
  const contents = (
    await Promise.all(welcomeEntries.map((entry) => resolveInterfaceDocumentContent(entry)))
  ).filter((content) => content.trim())
  if (
    contents.length > 0 &&
    localStorage.getItem("mwu.welcome.ack") !== welcomeFingerprint(contents)
  ) {
    welcomeContents.value = contents
    showWelcomeDialog.value = true
    return
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
