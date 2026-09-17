import { describe, expect, it } from "vitest"
import { buildTaskSections, UNGROUPED_SECTION_KEY } from "@/utils/task-config/order"
import type { Group, Task } from "@/types/interfaceModel"

function makeTask(entry: string, group?: string[]): Task {
  return { name: entry, entry, ...(group ? { group } : {}) }
}

function makeGroup(name: string, extra?: Partial<Group>): Group {
  return { name, ...extra }
}

describe("buildTaskSections", () => {
  it("returns null when no groups are declared and no task references any group", () => {
    expect(buildTaskSections([makeTask("a"), makeTask("b")], undefined)).toBeNull()
    expect(buildTaskSections([makeTask("a")], [])).toBeNull()
  })

  it("returns null for an empty task list without declared groups", () => {
    expect(buildTaskSections([], undefined)).toBeNull()
  })

  it("keeps declaration order and omits empty declared groups", () => {
    const sections = buildTaskSections(
      [makeTask("t1", ["b"])],
      [makeGroup("a"), makeGroup("b"), makeGroup("c")],
    )
    expect(sections?.map((section) => section.key)).toEqual(["b"])
    expect(sections?.[0].kind).toBe("declared")
    expect(sections?.[0].group?.name).toBe("b")
    expect(sections?.[0].tasks.map((task) => task.entry)).toEqual(["t1"])
  })

  it("orders declared groups first, adhoc groups by name, ungrouped last", () => {
    const sections = buildTaskSections(
      [
        makeTask("t1", ["zeta"]),
        makeTask("t2", ["daily"]),
        makeTask("t3"),
        makeTask("t4", ["farm"]),
        makeTask("t5", ["alpha"]),
      ],
      [makeGroup("farm"), makeGroup("daily")],
    )
    expect(sections?.map((section) => section.key)).toEqual([
      "farm",
      "daily",
      "alpha",
      "zeta",
      UNGROUPED_SECTION_KEY,
    ])
    expect(sections?.map((section) => section.kind)).toEqual([
      "declared",
      "declared",
      "adhoc",
      "adhoc",
      "ungrouped",
    ])
  })

  it("returns adhoc sections when tasks reference undeclared groups without any declaration", () => {
    const sections = buildTaskSections([makeTask("t1", ["ghost"])], undefined)
    expect(sections?.map((section) => section.key)).toEqual(["ghost"])
    expect(sections?.[0].kind).toBe("adhoc")
    expect(sections?.[0].group).toBeNull()
  })

  it("places a task referencing only undeclared groups solely in adhoc, not ungrouped", () => {
    const sections = buildTaskSections(
      [makeTask("t1", ["ghost"]), makeTask("t2")],
      [makeGroup("declared")],
    )
    const ungrouped = sections?.find((section) => section.kind === "ungrouped")
    expect(ungrouped?.tasks.map((task) => task.entry)).toEqual(["t2"])
    expect(sections?.find((section) => section.key === "ghost")?.kind).toBe("adhoc")
  })

  it("places a multi-group task into every referenced group", () => {
    const sections = buildTaskSections(
      [makeTask("t1", ["daily", "farm"])],
      [makeGroup("daily"), makeGroup("farm")],
    )
    expect(sections?.map((section) => section.key)).toEqual(["daily", "farm"])
    for (const section of sections ?? []) {
      expect(section.tasks.map((task) => task.entry)).toEqual(["t1"])
    }
  })

  it("deduplicates repeated group names on a single task", () => {
    const sections = buildTaskSections([makeTask("t1", ["daily", "daily"])], [makeGroup("daily")])
    expect(sections?.[0].tasks).toHaveLength(1)
  })

  it("treats a task with an empty group array as ungrouped", () => {
    const sections = buildTaskSections(
      [makeTask("t1", []), makeTask("t2", ["daily"])],
      [makeGroup("daily")],
    )
    expect(sections?.map((section) => section.key)).toEqual(["daily", UNGROUPED_SECTION_KEY])
    expect(sections?.[1].tasks.map((task) => task.entry)).toEqual(["t1"])
  })

  it("merges duplicate declarations, first declaration wins for display attributes", () => {
    const sections = buildTaskSections(
      [makeTask("t1", ["daily"])],
      [makeGroup("daily", { label: "first" }), makeGroup("daily", { label: "second" })],
    )
    expect(sections).toHaveLength(1)
    expect(sections?.[0].group?.label).toBe("first")
  })

  it("returns an empty array when declared groups exist but no tasks belong anywhere", () => {
    const sections = buildTaskSections([], [makeGroup("daily")])
    expect(sections).toEqual([])
  })
})
