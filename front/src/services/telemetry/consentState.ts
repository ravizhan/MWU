import { ref } from "vue"

/**
 * 遥测授权弹窗可见性（跨组件共享）。
 * App.vue 用来暂缓欢迎页：弹窗顺序为 运行 modal → 遥测授权 → 欢迎页。
 */
export const telemetryConsentVisible = ref(false)
