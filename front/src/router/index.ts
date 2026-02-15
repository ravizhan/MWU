import { createRouter, createWebHistory } from "vue-router"
import PanelView from "../views/PanelView.vue"

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      name: "panel",
      component: PanelView,
      meta: { transition: "slide-right" },
    },
    {
      path: "/setting",
      name: "setting",
      component: () => import("../views/SettingView.vue"),
      meta: { transition: "slide-left" },
    },
  ],
})

export default router
