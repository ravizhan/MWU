import { describe, expect, it, beforeEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"

vi.mock("@/services/api", () => ({
  getSchedulerTasks: vi.fn<() => void>(),
  createSchedulerTask: vi.fn<() => void>(),
  updateSchedulerTask: vi.fn<() => void>(),
  deleteSchedulerTask: vi.fn<() => void>(),
  pauseSchedulerTask: vi.fn<() => void>(),
  resumeSchedulerTask: vi.fn<() => void>(),
  getSchedulerExecutions: vi.fn<() => void>(),
}))

import { useSchedulerStore } from "@/stores/scheduler/scheduler"
import * as api from "@/services/api"
import type { ScheduledTask, TaskExecution } from "@/types/schedulerModel"

const mockTask = (id: string, enabled: boolean): ScheduledTask => ({
  task_identity: "name",
  id,
  name: `task-${id}`,
  enabled,
  task_list: [],
  task_options: {},
  preTasks: [],
  wakeup_enabled: false,
  trigger_config: { type: "cron", cron: "* * * * *" },
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
})

describe("useSchedulerStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("has correct initial state", () => {
    const store = useSchedulerStore()
    expect(store.tasks).toEqual([])
    expect(store.executions).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  describe("enabledTasks getter", () => {
    it("filters only enabled tasks", () => {
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true), mockTask("2", false), mockTask("3", true)]
      expect(store.enabledTasks).toHaveLength(2)
      expect(store.enabledTasks.map((t) => t.id)).toEqual(["1", "3"])
    })
  })

  describe("fetchTasks", () => {
    it("sets tasks on success", async () => {
      vi.mocked(api.getSchedulerTasks).mockResolvedValue({
        status: "success",
        tasks: [mockTask("1", true)],
      })
      const store = useSchedulerStore()
      await store.fetchTasks()
      expect(store.tasks).toHaveLength(1)
      expect(store.error).toBeNull()
    })

    it("sets error on failure response", async () => {
      vi.mocked(api.getSchedulerTasks).mockResolvedValue({
        status: "failed",
        message: "load failed",
      })
      const store = useSchedulerStore()
      await store.fetchTasks()
      expect(store.tasks).toEqual([])
      expect(store.error).toBe("load failed")
    })

    it("sets network error on exception", async () => {
      vi.mocked(api.getSchedulerTasks).mockRejectedValue(new Error("network"))
      const store = useSchedulerStore()
      await store.fetchTasks()
      expect(store.error).toBe("网络错误，请稍后重试")
    })
  })

  describe("createTask", () => {
    it("pushes task and returns the created task on success", async () => {
      const created = mockTask("new", true)
      vi.mocked(api.createSchedulerTask).mockResolvedValue({
        status: "success",
        task: created,
      })
      const store = useSchedulerStore()
      const result = await store.createTask({
        task_identity: "name",
        name: "new",
        enabled: true,
        wakeup_enabled: false,
        task_list: [],
        task_options: {},
        preTasks: [],
        trigger_config: { type: "cron", cron: "* * * * *" },
      })
      expect(result).toEqual(created)
      expect(store.tasks).toContainEqual(created)
    })

    it("sets error and returns null on failure", async () => {
      vi.mocked(api.createSchedulerTask).mockResolvedValue({
        status: "failed",
        message: "create failed",
      })
      const store = useSchedulerStore()
      const result = await store.createTask({
        task_identity: "name",
        name: "new",
        enabled: true,
        wakeup_enabled: false,
        task_list: [],
        task_options: {},
        preTasks: [],
        trigger_config: { type: "cron", cron: "* * * * *" },
      })
      expect(result).toBeNull()
      expect(store.error).toBe("create failed")
    })
  })

  describe("updateTask", () => {
    it("updates task in list and returns true on success", async () => {
      const original = mockTask("1", true)
      const updated = { ...original, name: "updated" }
      const store = useSchedulerStore()
      store.tasks = [original]
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "success",
        task: updated,
      })
      const result = await store.updateTask("1", { task_identity: "name", name: "updated" })
      expect(result).toBe(true)
      expect(store.tasks[0].name).toBe("updated")
    })

    it("returns false on failure", async () => {
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "failed",
        message: "update failed",
      })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true)]
      const result = await store.updateTask("1", { task_identity: "name", name: "updated" })
      expect(result).toBe(false)
      expect(store.error).toBe("update failed")
    })
  })

  describe("deleteTask", () => {
    it("removes task and returns true on success", async () => {
      vi.mocked(api.deleteSchedulerTask).mockResolvedValue({ status: "success" })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true), mockTask("2", true)]
      const result = await store.deleteTask("1")
      expect(result).toBe(true)
      expect(store.tasks.map((t) => t.id)).toEqual(["2"])
    })

    it("returns false on failure", async () => {
      vi.mocked(api.deleteSchedulerTask).mockResolvedValue({
        status: "failed",
        message: "delete failed",
      })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true)]
      const result = await store.deleteTask("1")
      expect(result).toBe(false)
      expect(store.error).toBe("delete failed")
    })
  })

  describe("toggleTask", () => {
    it("enables task by calling resumeSchedulerTask", async () => {
      vi.mocked(api.resumeSchedulerTask).mockResolvedValue({ status: "success" })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", false)]
      const result = await store.toggleTask("1", true)
      expect(api.resumeSchedulerTask).toHaveBeenCalledWith("1")
      expect(result).toBe(true)
      expect(store.tasks[0].enabled).toBe(true)
    })

    it("disables task by calling pauseSchedulerTask", async () => {
      vi.mocked(api.pauseSchedulerTask).mockResolvedValue({ status: "success" })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true)]
      const result = await store.toggleTask("1", false)
      expect(api.pauseSchedulerTask).toHaveBeenCalledWith("1")
      expect(result).toBe(true)
      expect(store.tasks[0].enabled).toBe(false)
    })
  })

  describe("fetchExecutions", () => {
    it("sets executions on success", async () => {
      const executions: TaskExecution[] = [
        {
          id: "e1",
          task_id: "1",
          task_name: "task-1",
          origin: "in_app",
          occurrence_id: null,
          blocker_task_name: null,
          started_at: "2024-01-01T00:00:00Z",
          status: "success",
        },
      ]
      vi.mocked(api.getSchedulerExecutions).mockResolvedValue({
        status: "success",
        executions,
      })
      const store = useSchedulerStore()
      await store.fetchExecutions(10)
      expect(api.getSchedulerExecutions).toHaveBeenCalledWith(10)
      expect(store.executions).toEqual(executions)
    })

    it("sets error on failure", async () => {
      vi.mocked(api.getSchedulerExecutions).mockResolvedValue({
        status: "failed",
        message: "history failed",
      })
      const store = useSchedulerStore()
      await store.fetchExecutions()
      expect(store.error).toBe("history failed")
    })
  })
})
