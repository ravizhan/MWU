import { ref, type Ref } from "vue"
import { useI18n } from "vue-i18n"
import { useSchedulerStore, useTaskConfigStore } from "@/stores"
import { schedulerTaskFormSchema } from "@/validation/scheduler"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"
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
    const executionPayload = configStore.buildExecutionPayload(
      formData.value.task_list,
      formData.value.task_options,
    )
    const taskPayload = {
      ...formData.value,
      wakeup_enabled:
        formData.value.trigger_config.type === "cron" && isCronNativeEligible.value
          ? wakeupEnabled.value
          : false,
      ...executionPayload,
      task_list: [...new Set(formData.value.task_list)],
      preTasks: formData.value.preTasks ?? [],
      task_identity: "name",
    }

    const parseResult = schedulerTaskFormSchema.safeParse(taskPayload)
    if (!parseResult.success) {
      const firstIssue = parseResult.error.issues[0]
      const path = firstIssue.path.join(".")
      // Route to correct section based on issue path
      if (path.startsWith("name")) {
        callbacks.focusSection("basic")
        showGlobalMessage("error", t("settings.scheduler.rules.nameRequired"))
        return
      }
      if (path.startsWith("trigger_config.cron")) {
        callbacks.focusSection("schedule")
        showGlobalMessage("error", t("settings.scheduler.rules.cronInvalid"))
        return
      }
      if (path.startsWith("trigger_config.run_date")) {
        callbacks.focusSection("schedule")
        const msg = firstIssue.message.includes("future")
          ? t("settings.scheduler.rules.dateInPast")
          : t("settings.scheduler.rules.dateRequired")
        showGlobalMessage("error", msg)
        return
      }
      if (!path || path.startsWith("trigger_config")) {
        callbacks.focusSection("schedule")
        showGlobalMessage("error", t("settings.scheduler.rules.intervalRequired"))
        return
      }
      if (path.startsWith("task_list")) {
        callbacks.focusSection("content", "task-list")
        showGlobalMessage("error", t("settings.scheduler.rules.taskListRequired"))
        return
      }
      showGlobalMessage("error", firstIssue.message)
      return
    }

    const parsedTask = {
      ...parseResult.data,
      description: parseResult.data.description ?? undefined,
      preTasks: parseResult.data.preTasks.map((preTask) => ({
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
