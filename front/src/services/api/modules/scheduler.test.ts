import { describe, expect, it, beforeEach, afterEach } from "vitest"
import { http, HttpResponse } from "msw"
import { server } from "@/tests/mocks/server"
import {
  getSchedulerTasks,
  createSchedulerTask,
  updateSchedulerTask,
  deleteSchedulerTask,
  pauseSchedulerTask,
  resumeSchedulerTask,
  getSchedulerExecutions,
} from "@/services/api/modules/scheduler"
import type { ScheduledTaskCreate, ScheduledTaskUpdate } from "@/types/schedulerModel"

describe("scheduler API module", () => {
  beforeEach(() => {
    server.resetHandlers()
  })

  afterEach(() => {
    server.resetHandlers()
  })

  describe("getSchedulerTasks", () => {
    it("GET /api/scheduler/tasks and parses response", async () => {
      server.use(
        http.get("/api/scheduler/tasks", () =>
          HttpResponse.json({
            status: "success",
            tasks: [{ id: "1", name: "task-1" }],
          }),
        ),
      )
      const response = await getSchedulerTasks()
      expect(response.status).toBe("success")
      expect(response.tasks).toHaveLength(1)
      expect(response.tasks?.[0].id).toBe("1")
    })
  })

  describe("createSchedulerTask", () => {
    it("POST /api/scheduler/tasks with correct body", async () => {
      let capturedBody: Record<string, unknown> | null = null
      server.use(
        http.post("/api/scheduler/tasks", async ({ request }) => {
          // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
          capturedBody = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({ status: "success", task: { id: "new", name: "new-task" } })
        }),
      )
      const task: ScheduledTaskCreate = {
        task_identity: "name",
        name: "new-task",
        enabled: true,
        wakeup_enabled: false,
        task_list: [],
        task_options: {},
        preTasks: [],
        trigger_config: { type: "cron", cron: "0 0 * * *" },
      }
      const response = await createSchedulerTask(task)
      expect(response.status).toBe("success")
      expect(response.task?.name).toBe("new-task")
      expect(capturedBody).toEqual(task)
    })
  })

  describe("updateSchedulerTask", () => {
    it("PUT /api/scheduler/tasks/:taskId with correct body", async () => {
      let capturedBody: Record<string, unknown> | null = null
      server.use(
        http.put("/api/scheduler/tasks/1", async ({ request }) => {
          // eslint-disable-next-line @typescript-eslint/consistent-type-assertions
          capturedBody = (await request.json()) as Record<string, unknown>
          return HttpResponse.json({ status: "success", task: { id: "1", name: "updated" } })
        }),
      )
      const update: ScheduledTaskUpdate = { task_identity: "name", name: "updated" }
      const response = await updateSchedulerTask("1", update)
      expect(response.status).toBe("success")
      expect(capturedBody).toEqual(update)
    })
  })

  describe("deleteSchedulerTask", () => {
    it("DELETE /api/scheduler/tasks/:taskId", async () => {
      server.use(
        http.delete("/api/scheduler/tasks/1", () => HttpResponse.json({ status: "success" })),
      )
      const response = await deleteSchedulerTask("1")
      expect(response.status).toBe("success")
    })
  })

  describe("pauseSchedulerTask", () => {
    it("POST /api/scheduler/tasks/:taskId/pause", async () => {
      server.use(
        http.post("/api/scheduler/tasks/1/pause", () => HttpResponse.json({ status: "success" })),
      )
      const response = await pauseSchedulerTask("1")
      expect(response.status).toBe("success")
    })
  })

  describe("resumeSchedulerTask", () => {
    it("POST /api/scheduler/tasks/:taskId/resume", async () => {
      server.use(
        http.post("/api/scheduler/tasks/1/resume", () => HttpResponse.json({ status: "success" })),
      )
      const response = await resumeSchedulerTask("1")
      expect(response.status).toBe("success")
    })
  })

  describe("getSchedulerExecutions", () => {
    it("GET /api/scheduler/executions?limit=N and parses response", async () => {
      server.use(
        http.get("/api/scheduler/executions", ({ request }) => {
          const url = new URL(request.url)
          expect(url.searchParams.get("limit")).toBe("10")
          return HttpResponse.json({
            status: "success",
            executions: [{ id: "e1", task_id: "1" }],
          })
        }),
      )
      const response = await getSchedulerExecutions(10)
      expect(response.status).toBe("success")
      expect(response.executions).toHaveLength(1)
    })
  })
})
