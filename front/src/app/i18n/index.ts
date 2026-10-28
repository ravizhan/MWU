import { createI18n } from "vue-i18n"
import enUS from "@/app/i18n/messages/en-US.json"
import zhCN from "@/app/i18n/messages/zh-CN.json"

type MessageSchema = typeof zhCN
type Locale = "zh-CN" | "en-US"

const DEFAULT_LOCALE = "zh-CN" as const

const savedLocale = localStorage.getItem("locale")
const locale: Locale =
  savedLocale === "zh-CN" || savedLocale === "en-US" ? savedLocale : DEFAULT_LOCALE

const i18n = createI18n<[MessageSchema], Locale>({
  legacy: false,
  globalInjection: true,
  locale,
  fallbackLocale: DEFAULT_LOCALE,
  messages: {
    "zh-CN": zhCN,
    "en-US": enUS,
  },
})

export default i18n
