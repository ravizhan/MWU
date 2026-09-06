import { computed, ref, watch } from "vue"
import type { Ref } from "vue"
import { useInterfaceStore } from "@/stores"
import { resolveInterfaceText, resolveInterfaceAssetUrl } from "@/utils/interface/content"

/**
 * PI 元数据（title / welcome / icon）的解析与展示驱动。
 *
 * - title：interface.title（翻译展开），回退 interface.name → "MWU"；
 * - welcome：interface.welcome（翻译展开），指纹 = name + locale + content 拼接，
 *   指纹变化（内容或语言变化）时再次展示；
 * - icon：interface.icon 资源 URL（翻译展开）。
 */
export function useInterfaceMetadata(locale: Ref<string>) {
  const interfaceStore = useInterfaceStore()

  const resolvedTitle = computed(() => {
    const model = interfaceStore.interface
    const title = resolveInterfaceText(model, locale.value, model?.title, "")
    if (title.trim()) {
      return title.trim()
    }
    const label = resolveInterfaceText(model, locale.value, model?.label, "")
    if (label.trim()) {
      return label.trim()
    }
    return model?.name || "MWU"
  })

  const resolvedWelcome = computed(() => {
    const model = interfaceStore.interface
    return resolveInterfaceText(model, locale.value, model?.welcome, "")
  })

  const resolvedIconUrl = computed(() => {
    const model = interfaceStore.interface
    return resolveInterfaceAssetUrl(model, locale.value, model?.icon)
  })

  const welcomeFingerprint = computed(() => {
    const model = interfaceStore.interface
    return `${model?.name || ""}::${locale.value}::${resolvedWelcome.value}`
  })

  const lastShownWelcomeFingerprint = ref("")

  const welcomeShouldShow = computed(
    () =>
      resolvedWelcome.value.trim() !== "" &&
      welcomeFingerprint.value !== lastShownWelcomeFingerprint.value,
  )

  function markWelcomeShown(): void {
    lastShownWelcomeFingerprint.value = welcomeFingerprint.value
  }

  // document.title 跟随解析标题
  watch(
    resolvedTitle,
    (title) => {
      document.title = title
    },
    { immediate: true },
  )

  return {
    resolvedTitle,
    resolvedWelcome,
    resolvedIconUrl,
    welcomeFingerprint,
    welcomeShouldShow,
    markWelcomeShown,
  }
}
