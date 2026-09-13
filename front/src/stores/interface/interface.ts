import { defineStore } from "pinia"
import {
  getInterface,
  rescanScanSelectOption as requestRescanScanSelectOption,
} from "@/services/api"
import type {
  InterfaceModel,
  Option,
  Preset,
  Pretask,
  SettingSection,
  Task,
} from "@/types/interfaceModel"
import type { TaskListItem } from "@/types/taskConfigModel"

export const useInterfaceStore = defineStore("interface", {
  state: (): { interface: Partial<InterfaceModel> } => ({
    interface: {},
  }),
  getters: {
    getTaskList: (state): TaskListItem[] => {
      if (!state.interface?.task) return []
      return state.interface.task.map((item, index) => ({
        id: item.name,
        name: item.name,
        order: index,
      }))
    },
    getPresetList: (state): Preset[] => state.interface?.preset || [],
    getPretasks: (state): Pretask[] => state.interface?.pretask || [],
    getSettingSections: (state): SettingSection[] => state.interface?.setting || [],
    getUncoveredOptionNames: (state): string[] => {
      const model = state.interface
      const covered = new Set<string>()
      for (const section of model.setting ?? []) {
        for (const optionName of section.option ?? []) {
          covered.add(optionName)
        }
      }

      const candidates = [
        ...(model.global_option ?? []),
        ...(model.resource ?? []).flatMap((item) => item.option ?? []),
        ...(model.controller ?? []).flatMap((item) => item.option ?? []),
      ]
      const seen = new Set<string>()
      const result: string[] = []
      for (const optionName of candidates) {
        if (
          covered.has(optionName) ||
          seen.has(optionName) ||
          model.option?.[optionName] === undefined
        ) {
          continue
        }
        seen.add(optionName)
        result.push(optionName)
      }
      return result
    },
  },
  actions: {
    async setInterface() {
      this.interface = await getInterface()
    },

    async rescanScanSelectOption(optionName: string): Promise<boolean> {
      const targetOption = this.interface?.option?.[optionName]
      if (!targetOption || targetOption.type !== "scan_select") {
        return false
      }

      const cases = await requestRescanScanSelectOption(optionName)
      const latestOption = this.interface?.option?.[optionName]
      if (!latestOption || latestOption.type !== "scan_select") {
        return false
      }
      latestOption.cases = cases
      return true
    },

    isTaskCompatible(
      task: Task | null,
      controllerName?: string | null,
      resourceName?: string | null,
    ): boolean {
      if (!task) {
        return true
      }

      if (controllerName && task.controller?.length && !task.controller.includes(controllerName)) {
        return false
      }

      return !(resourceName && task.resource?.length && !task.resource.includes(resourceName))
    },

    isTaskCompatibleByName(
      name: string,
      controllerName?: string | null,
      resourceName?: string | null,
    ): boolean {
      return this.isTaskCompatible(this.getTaskByName(name), controllerName, resourceName)
    },

    isPretaskCompatible(
      pretask: Pretask,
      controllerName?: string | null,
      resourceName?: string | null,
    ): boolean {
      if (
        controllerName &&
        pretask.controller?.length &&
        !pretask.controller.includes(controllerName)
      ) {
        return false
      }

      return !(resourceName && pretask.resource?.length && !pretask.resource.includes(resourceName))
    },

    getTaskByName(name: string): Task | null {
      return this.interface?.task?.find((task) => task.name === name) || null
    },

    getPresetByName(name: string): Preset | null {
      return this.interface?.preset?.find((preset) => preset.name === name) || null
    },

    getOptionList(taskName: string): Record<string, Option> {
      const result: Record<string, Option> = {}
      if (!this.interface?.option) return result

      const collectOptions = (optionNames: string[]) => {
        for (const optionName of optionNames) {
          if (result[optionName]) continue
          const optionValue = this.interface.option?.[optionName]
          if (optionValue === undefined) {
            continue
          }
          result[optionName] = optionValue
          if ("cases" in optionValue) {
            for (const caseItem of optionValue.cases || []) {
              if (caseItem.option) {
                collectOptions(caseItem.option)
              }
            }
          }
        }
      }

      const task = this.getTaskByName(taskName)
      if (task?.option) {
        collectOptions(task.option)
      }
      return result
    },
  },
})
