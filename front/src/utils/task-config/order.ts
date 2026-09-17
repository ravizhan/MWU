import type { Group, Task } from "@/types/interfaceModel"

export const UNGROUPED_SECTION_KEY = "__mwu_ungrouped__"

export interface TaskGroupSection {
  /** declared/adhoc: 分组 name；ungrouped 固定为 UNGROUPED_SECTION_KEY */
  key: string
  kind: "declared" | "adhoc" | "ungrouped"
  /** declared 时取 interface 声明（含 label/icon/description/default_expand） */
  group: Group | null
  tasks: Task[]
}

/**
 * 将任务按 interface group 声明组装成分组区段。
 * 返回 null 表示完全没有分组信息（无声明且无任何任务引用），调用方退化为平铺渲染。
 */
export function buildTaskSections(
  visibleTasks: Task[],
  declaredGroups: Group[] | undefined,
): TaskGroupSection[] | null {
  // 同名重复声明时合并，首个声明的展示属性生效
  const declaredByName = new Map<string, Group>()
  for (const group of declaredGroups ?? []) {
    if (!declaredByName.has(group.name)) {
      declaredByName.set(group.name, group)
    }
  }

  const declaredTasks = new Map<string, Task[]>()
  const adhocTasks = new Map<string, Task[]>()
  const ungroupedTasks: Task[] = []

  for (const task of visibleTasks) {
    // 多分组任务出现在它声明的每一个分组
    const groupNames = [...new Set(task.group ?? [])]
    if (groupNames.length === 0) {
      ungroupedTasks.push(task)
      continue
    }
    for (const name of groupNames) {
      // 引用未声明的名字即时建 adhoc 组；只引用未声明名字的任务不进 ungrouped
      const bucket = declaredByName.has(name) ? declaredTasks : adhocTasks
      const list = bucket.get(name) ?? []
      list.push(task)
      bucket.set(name, list)
    }
  }

  if (declaredByName.size === 0 && adhocTasks.size === 0) {
    return null
  }

  const sections: TaskGroupSection[] = []
  for (const [name, group] of declaredByName) {
    const tasks = declaredTasks.get(name)
    if (tasks && tasks.length > 0) {
      sections.push({ key: name, kind: "declared", group, tasks })
    }
  }
  for (const name of [...adhocTasks.keys()].sort()) {
    sections.push({ key: name, kind: "adhoc", group: null, tasks: adhocTasks.get(name) ?? [] })
  }
  if (ungroupedTasks.length > 0) {
    sections.push({
      key: UNGROUPED_SECTION_KEY,
      kind: "ungrouped",
      group: null,
      tasks: ungroupedTasks,
    })
  }
  return sections
}
