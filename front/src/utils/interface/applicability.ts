import type { Option } from "@/types/interfaceModel"

/**
 * option 是否适用于给定控制器/资源上下文。
 *
 * 与后端 models/interface.py:is_option_applicable 同一语义：
 * 受限而未选择对应上下文的 option 不激活（前端隐藏不适用子树，
 * 保存现有值以便切回环境恢复）。
 */
export function isOptionApplicable(
  option: Pick<Option, "controller" | "resource"> | null | undefined,
  controllerName: string | null,
  resourceName: string | null,
): boolean {
  if (!option) {
    return true
  }
  if (option.controller && option.controller.length > 0) {
    if (!controllerName || !option.controller.includes(controllerName)) {
      return false
    }
  }
  if (option.resource && option.resource.length > 0) {
    if (!resourceName || !option.resource.includes(resourceName)) {
      return false
    }
  }
  return true
}
