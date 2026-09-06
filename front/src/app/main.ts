import "@/app.css"
import "@/app/styles/main.css"
import { createApp } from "vue"
import { createPinia } from "pinia"
import App from "@/app/App.vue"
import router from "@/app/router"
import i18n from "@/app/i18n"
import { useIndexStore, useSettingsStore } from "@/stores"
import { useFocusInteractionStore } from "@/stores/focus/focusInteraction"
import { sse } from "@/services/realtime/sse"
import { dispatchRealtimeEvent } from "@/services/realtime/dispatcher"
import type { RealtimeEventName } from "@/types/realtimeModel"

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(i18n)

// naive-ui style anchor: keeps naive styles injected before Tailwind preflight
const meta = document.createElement("meta")
meta.name = "naive-ui-style"
document.head.appendChild(meta)

const indexStore = useIndexStore(pinia)
const settingsStore = useSettingsStore(pinia)
const focusInteractionStore = useFocusInteractionStore(pinia)

const stores = { indexStore, settingsStore, focusInteractionStore }

// 打开页面时拉取可能已存在的 pending 交互（SSE 之前的漏网）
void focusInteractionStore.hydrate()

/**
 * All SSE event types. The dispatcher routes each event by type,
 * applying common handling (log + notify channels) plus type-specific
 * side effects (e.g. task lifecycle → store state updates).
 */
;(
  [
    "log",
    "focus.display",
    "focus.interaction",
    "task.started",
    "task.completed",
    "task.failed",
    "notification.test",
  ] as const
).forEach((eventName: RealtimeEventName) => {
  sse.addEventListener(eventName, (event) => dispatchRealtimeEvent(event, stores))
})

app.mount("#app")
