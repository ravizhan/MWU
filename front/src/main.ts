import "./assets/main.css"
import { createApp } from "vue"
import App from "./App.vue"
import router from "./router"
import { createPinia } from "pinia"
import { useIndexStore } from "./stores"
import { sse } from "./script/sse"
import "virtual:uno.css"
import i18n from "./libs/i18n"

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(i18n)

const indexStore = useIndexStore(pinia)

sse.addEventListener("log", (data: { message: string }) => {
  indexStore.UpdateLog(data.message)
})

app.mount("#app")
