import { ref, type Ref } from "vue"
import { useI18n } from "vue-i18n"
import { useSchedulerStore, useTaskConfigStore } from "@/stores"
import { schedulerTaskFormSchema } from "@/validation/scheduler"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"
import type { ZodIssue } from "zod"
import type { ScheduledTask } from "@/types/schedulerModel"
import type { SchedulerTaskFormData } from "./useSchedulerTaskForm"

export type DialogSection = "basic" | "schedule" | "environment" | "content"
export type ContentTab = "task-list" | "task-settings" | "pre-tasks"

interface SaveCallbacks {
  focusSection: (section: DialogSection, tab?: ContentTab) => void
  close: () => void
  saved: () => void
  reset: () => void
}

export interface SchedulerTaskSave {
  loading: Ref<boolean>
  handleSave: () => Promise<void>
}

function triggerRuleMessage(issue: ZodIssue): string {
  if (issue.path[1] === "cron") return "settings.scheduler.rules.cronInvalid"
  if (issue.path[1] === "run_date") {
    return issue.message.includes("future")
      ? "settings.scheduler.rules.dateInPast"
      : "settings.scheduler.rules.dateRequired"
  }
  if (issue.path[1] === "end_date") return "settings.scheduler.rules.intervalEndBeforeStart"
  return "settings.scheduler.rules.intervalRequired"
}

/** 把 zod 校验问题路由到对应分区，并提示该分区的规则文案。 */
function reportFormIssue(
  issue: ZodIssue,
  callbacks: SaveCallbacks,
  t: (key: string) => string,
): void {
  const path = issue.path.join(".")
  if (path.startsWith("name")) {
    callbacks.focusSection("basic")
    showGlobalMessage("error", t("settings.scheduler.rules.nameRequired"))
    return
  }
  if (path.startsWith("trigger_config")) {
    callbacks.focusSection("schedule")
    showGlobalMessage("error", t(triggerRuleMessage(issue)))
    return
  }
  callbacks.focusSection("content", "task-list")
  showGlobalMessage("error", t("settings.scheduler.rules.taskListRequired"))
}

export function useSchedulerTaskSave(
  task: Ref<ScheduledTask | null | undefined>,
  formData: Ref<SchedulerTaskFormData>,
  wakeupEnabled: Ref<boolean>,
  isCronNativeEligible: Ref<boolean>,
  callbacks: SaveCallbacks,
): SchedulerTaskSave {
  const { t } = useI18n()
  const schedulerStore = useSchedulerStore()
  const configStore = useTaskConfigStore()

  const loading = ref(false)

  async function handleSave() {
    const taskPayload = {
      ...formData.value,
      wakeup_enabled:
        formData.value.trigger_config.type === "cron" && isCronNativeEligible.value
          ? wakeupEnabled.value
          : false,
      ...configStore.buildExecutionPayload(formData.value.task_list, formData.value.task_options),
      preTasks: formData.value.preTasks ?? [],
    }

    const parseResult = schedulerTaskFormSchema.safeParse(taskPayload)
    if (!parseResult.success) {
      reportFormIssue(parseResult.error.issues[0], callbacks, t)
      return
    }

    const parsedTask = {
      ...taskPayload,
      name: parseResult.data.name,
      description: taskPayload.description ?? undefined,
      preTasks: taskPayload.preTasks.map((preTask) => ({
        ...preTask,
        id: preTask.id ?? crypto.randomUUID(),
      })),
    }

    loading.value = true
    const [savedTask, err] = await tryCatch(async () => {
      const currentTask = task.value
      if (currentTask) {
        const ok = await schedulerStore.updateTask(currentTask.id, parsedTask)
        return ok ? currentTask : null
      }
      return schedulerStore.createTask(parsedTask)
    })
    loading.value = false
    if (err || !savedTask) {
      showGlobalMessage("error", schedulerStore.error || t("settings.scheduler.dialog.saveFail"))
      return
    }

    showGlobalMessage(
      "success",
      task.value
        ? t("settings.scheduler.dialog.taskUpdated")
        : t("settings.scheduler.dialog.taskCreated"),
    )
    callbacks.close()
    callbacks.saved()
    callbacks.reset()
  }

  return { loading, handleSave }
}
