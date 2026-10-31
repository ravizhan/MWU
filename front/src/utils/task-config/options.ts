import type {
  HotkeyOption,
  InputOption,
  Option,
  ScanSelectOption,
  SelectOption,
  SwitchOption,
} from "@/types/interfaceModel"
import type { TaskOptionValue } from "@/types/schedulerModel"

export function buildOrderedCheckboxValue(option: Extract<Option, { type: "checkbox" }>): string[] {
  const selectedSet = new Set(option.default_case || [])
  return option.cases.filter((item) => selectedSet.has(item.name)).map((item) => item.name)
}

function normalizeObjectValue(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {}
  }

  const normalized: Record<string, string> = {}
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === "string") {
      normalized[key] = item
    }
  }
  return normalized
}

// 与后端 _build_option_defaults 一致：default_case 不属于 cases 时回退到第一个 case
function buildSingleCaseDefault(option: SelectOption | ScanSelectOption | SwitchOption): string {
  const defaultCase = option.default_case
  if (typeof defaultCase === "string" && option.cases.some((item) => item.name === defaultCase)) {
    return defaultCase
  }
  return option.cases[0]?.name ?? ""
}

function buildInputDefault(option: InputOption): Record<string, string> {
  const inputDefaults: Record<string, string> = {}
  for (const input of option.inputs) {
    inputDefaults[input.name] = input.default ?? ""
  }
  return inputDefaults
}

function buildHotkeyDefault(option: HotkeyOption): Record<string, string> {
  const hotkeyDefaults: Record<string, string> = {}
  for (const hotkey of option.hotkeys) {
    hotkeyDefaults[hotkey.name] = hotkey.default ?? ""
  }
  return hotkeyDefaults
}

// 根据选项定义生成默认值
export function buildDefaultsFromOptionMap(
  optionMap: Record<string, Option>,
): Record<string, TaskOptionValue> {
  const options: Record<string, TaskOptionValue> = {}
  for (const key in optionMap) {
    const option = optionMap[key]

    if (option.type === "select" || option.type === "scan_select" || option.type === "switch") {
      options[key] = buildSingleCaseDefault(option)
      continue
    }

    if (option.type === "input") {
      options[key] = buildInputDefault(option)
      continue
    }

    if (option.type === "hotkey") {
      options[key] = buildHotkeyDefault(option)
      continue
    }

    if (option.type === "checkbox") {
      options[key] = buildOrderedCheckboxValue(option)
    }
  }

  return options
}

// 仅在提交边界进行兼容转换，内部状态可保留 null 表示“未设置”
export function normalizeOptionValueForBoundary(
  value: TaskOptionValue | null | undefined,
): TaskOptionValue | undefined {
  if (value === undefined) {
    return undefined
  }
  if (value === null) {
    return ""
  }
  if (typeof value === "string") {
    return value
  }
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string")
  }
  return normalizeObjectValue(value)
}
