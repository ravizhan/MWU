import { h } from "vue"
import type { SelectRenderLabel } from "naive-ui"
import { resolveInterfaceAssetUrl } from "@/utils/interface/content"

/** NSelect `render-label`：选项带 interface `icon` 时在文字前渲染图标（下拉项与已选值共用）。 */
export const renderIconLabel: SelectRenderLabel = (option) => {
  const label = typeof option.label === "string" ? option.label : ""
  const src = typeof option.icon === "string" ? resolveInterfaceAssetUrl(option.icon) : undefined
  if (!src) return label
  return h("span", { class: "inline-flex min-w-0 items-center gap-1.5" }, [
    h("img", { src, alt: "", class: "h-6 w-6 shrink-0 object-contain" }),
    h("span", { class: "truncate" }, label),
  ])
}
