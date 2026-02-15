<template>
  <n-config-provider
    :theme="naiveTheme"
    :theme-overrides="themeOverrides"
    :locale="naiveLocale"
    :date-locale="naiveDateLocale"
    class="h-full xl:flex xl:flex-col xl:justify-center bg-gray-50 dark:bg-gray-900 transition-colors duration-300"
  >
    <n-message-provider>
      <n-dialog-provider>
        <div>
          <n-layout
            class="xl:shadow-3xl xl:w-[80vw] w-full mx-auto pt-0 xl:rounded-xl transition-all duration-300"
          >
            <n-layout-header bordered class="backdrop-blur-sm bg-opacity-90 h-[10vh] xl:h-auto">
              <div class="text-center text-2xl font-bold tracking-wide">{{ name }}</div>
              <n-menu mode="horizontal" class="justify-between" :options="menuOptions" />
            </n-layout-header>
            <n-layout>
              <router-view v-slot="{ Component, route }">
                <transition :name="route.meta.transition || 'fade'" mode="out-in">
                  <component :is="Component" />
                </transition>
              </router-view>
            </n-layout>
            <n-layout-footer
              bordered
              class="text-center xl:py-4 py-2 h-[5vh] xl:h-auto text-gray-500"
            >
              <a
                href="https://github.com/ravizhan/MWU"
                target="_blank"
                class="hover:text-blue-500 transition-colors"
              >
                Powered by MWU
              </a>
            </n-layout-footer>
          </n-layout>
        </div>
      </n-dialog-provider>
    </n-message-provider>
    <n-global-style />

    <!-- Update Dialog -->
    <UpdateDialog v-model:show="showUpdateDialog" :update-info="updateInfo" />
  </n-config-provider>
</template>

<script setup lang="ts">
import { NIcon, zhCN, dateZhCN } from "naive-ui"
import { h, ref, onMounted, watch, computed, watchEffect } from "vue"
import { RouterLink } from "vue-router"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "./stores/interface.ts"
import { useTaskConfigStore } from "./stores/taskConfig.ts"
import { useSettingsStore } from "./stores/settings"
import { darkTheme } from "naive-ui"
import { lightThemeOverrides, darkThemeOverrides } from "./theme"
import { checkUpdateApi, type UpdateInfo } from "./script/api"
import UpdateDialog from "./components/UpdateDialog.vue"

import githubMarkdownAutoUrl from "github-markdown-css/github-markdown.css?url"
import githubMarkdownLightUrl from "github-markdown-css/github-markdown-light.css?url"
import githubMarkdownDarkUrl from "github-markdown-css/github-markdown-dark.css?url"

function renderIcon(icon: string) {
  return () => h(NIcon, null, { default: () => h("div", { class: icon }) })
}
const { t, locale } = useI18n()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const settingsStore = useSettingsStore()
const name = computed(() => interfaceStore.interface?.name || "")
const offset = ref(0)
const screenWidth = ref(window.innerWidth)

const naiveTheme = computed(() => (settingsStore.isDarkMode ? darkTheme : null))
const themeOverrides = computed(() =>
  settingsStore.isDarkMode ? darkThemeOverrides : lightThemeOverrides,
)

const naiveLocale = computed(() => (locale.value === "zh-CN" ? zhCN : null))
const naiveDateLocale = computed(() => (locale.value === "zh-CN" ? dateZhCN : null))

const markdownCssHref = computed(() => {
  const mode = settingsStore.settings.ui.darkMode
  if (mode === "auto") return githubMarkdownAutoUrl
  return mode ? githubMarkdownDarkUrl : githubMarkdownLightUrl
})

const showUpdateDialog = ref(false)
const updateInfo = ref<UpdateInfo | null>(null)

function ensureMarkdownStylesheet(href: string) {
  const id = "github-markdown-theme"
  let el = document.getElementById(id) as HTMLLinkElement | null
  if (!el) {
    el = document.createElement("link")
    el.id = id
    el.rel = "stylesheet"
    document.head.appendChild(el)
  }
  if (el.href !== href) {
    el.href = href
  }
}

const handleResize = () => {
  screenWidth.value = window.innerWidth
}

const checkForUpdatesOnLoad = async () => {
  // Wait for settings to be loaded
  if (!settingsStore.settings.update) {
    return
  }

  // Only check if auto-update is enabled
  if (!settingsStore.settings.update.autoUpdate) {
    return
  }

  try {
    const result = await checkUpdateApi()
    if (result.status === "success" && result.update_info?.is_update_available) {
      updateInfo.value = result.update_info
      showUpdateDialog.value = true
    }
  } catch (error) {
    console.error("Failed to check for updates on load:", error)
  }
}

onMounted(async () => {
  settingsStore.initSystemThemeListener()
  await interfaceStore.setInterface()
  await configStore.loadConfig()
  if (!settingsStore.initialized) {
    await settingsStore.fetchSettings()
  }

  // Check for updates after settings are loaded
  checkForUpdatesOnLoad()

  window.addEventListener("resize", handleResize)
})

watchEffect(() => {
  ensureMarkdownStylesheet(markdownCssHref.value)
  if (settingsStore.isDarkMode) {
    document.documentElement.classList.add("dark")
  } else {
    document.documentElement.classList.remove("dark")
  }
})
watch(screenWidth, (newValue) => {
  if (newValue < 450) {
    offset.value = 0
  } else if (newValue >= 450 && newValue < 600) {
    offset.value = 1
  } else {
    offset.value = 3
  }
})

const menuOptions = computed(() => [
  {
    label: () =>
      h(
        RouterLink,
        {
          to: {
            name: "panel",
          },
        },
        { default: () => t("menu.home") },
      ),
    key: "panel",
    icon: renderIcon("i-mdi-home"),
  },
  {
    label: () =>
      h(
        RouterLink,
        {
          to: {
            name: "setting",
          },
        },
        { default: () => t("menu.settings") },
      ),
    key: "setting",
    icon: renderIcon("i-mdi-cog"),
  },
])
</script>
