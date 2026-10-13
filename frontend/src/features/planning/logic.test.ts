import { describe, expect, it } from "vitest";

import {
  addEdge,
  addTask,
  coverageRows,
  crossings,
  diffPlans,
  groupTree,
  layout,
  localProblems,
  nextTaskId,
  removeEdge,
  removeTask,
  samePlan,
  stepStatus,
  updateTask,
  wouldCycle,
} from "./logic";
import type { PlanTask, TaskGraph } from "./types";

function t(id: string, deps: string[] = [], extra: Partial<PlanTask> = {}): PlanTask {
  return {
    id, title: `Step ${id}`, description: "", agent_capability: "code.implement", requirement_ids: [], acceptance_criteria: ["ok"],
    depends_on: deps, priority: "normal", est_effort: 1, phase: "implement", research_questions: [], ...extra,
  };
}

function graph(tasks: PlanTask[], coverage: Record<string, string[]> = {}): TaskGraph {
  return { project_id: "P", version: 1, tasks, roadmap: { phases: [], milestones: [], markdown: null }, coverage_matrix: coverage };
}

describe("layout", () => {
  it("puts dependencies to the left and keeps every node", () => {
    const g = [t("a"), t("b", ["a"]), t("c", ["a"]), t("d", ["b", "c"])];
    const placed = layout(g);
    const at = Object.fromEntries(placed.map((p) => [p.id, p]));
    expect(placed).toHaveLength(4);
    expect(at.a!.layer).toBe(0);
    expect(at.b!.layer).toBe(1);
    expect(at.d!.layer).toBe(2);
    expect(at.d!.x).toBeGreaterThan(at.b!.x);
  });

  it("reduces crossings with barycenter sweeps", () => {
    // two chains drawn crossed in input order: a1 -> b2, a2 -> b1
    const g = [t("a1"), t("a2"), t("b2", ["a1"]), t("b1", ["a2"]), t("c", ["b1", "b2"])];
    expect(crossings(g, layout(g))).toBe(0);
  });

  it("survives a cycle in an unsaved edit", () => {
    expect(layout([t("a", ["b"]), t("b", ["a"])])).toHaveLength(2);
  });
});

describe("edits", () => {
  it("adds, updates and removes steps without touching the original", () => {
    const g = graph([t("T1"), t("T2", ["T1"]), t("T3", ["T2"])], { R1: ["T2"] });
    const { graph: added, id } = addTask(g, " New step ", "test", "test.run");
    expect(id).toBe("T4");
    expect(added.tasks.at(-1)).toMatchObject({ id: "T4", title: "New step", phase: "test", agent_capability: "test.run" });
    expect(g.tasks).toHaveLength(3);
    const renamed = updateTask(g, "T1", { title: "Renamed", id: "X" } as Partial<PlanTask>);
    expect(renamed.tasks[0]).toMatchObject({ id: "T1", title: "Renamed" });
    const removed = removeTask(g, "T2");
    expect(removed.tasks.map((x) => x.id)).toEqual(["T1", "T3"]);
    expect(removed.tasks[1]!.depends_on).toEqual(["T1"]); // inherits the removed step's dependencies
    expect(removed.coverage_matrix.R1).toEqual([]);
    expect(nextTaskId(graph([t("research"), t("T9")]))).toBe("T10");
  });

  it("adds and removes edges and refuses loops", () => {
    const g = graph([t("A"), t("B", ["A"]), t("C", ["B"])]);
    expect(wouldCycle(g, "C", "A")).toBe(true);
    expect(wouldCycle(g, "A", "C")).toBe(false);
    expect(addEdge(g, "A", "C").tasks[2]!.depends_on).toEqual(["B", "A"]);
    expect(addEdge(g, "A", "A")).toBe(g);
    expect(removeEdge(g, "B", "C").tasks[2]!.depends_on).toEqual([]);
    expect(samePlan(g, removeEdge(g, "X", "C"))).toBe(true);
  });

  it("finds local problems before saving", () => {
    const g = graph([t("A", ["C"]), t("B", ["A", "ghost"], { title: " " }), t("C", ["B"])]);
    const problems = localProblems(g);
    expect(problems.some((p) => p.includes("B needs a title"))).toBe(true);
    expect(problems.some((p) => p.includes("ghost"))).toBe(true);
    expect(problems.some((p) => p.includes("loop"))).toBe(true);
    expect(localProblems(graph([t("A"), t("B", ["A"])]))).toEqual([]);
  });
});

describe("versions, coverage and groups", () => {
  it("diffs two versions", () => {
    const a = graph([t("A"), t("B", ["A"]), t("C", ["A"])]);
    const b = graph([t("A"), t("B", ["A"], { title: "Changed" }), t("D", ["B"])]);
    expect(diffPlans(a, b)).toEqual({ added: ["D"], removed: ["C"], changed: ["B"], edgesAdded: ["B → D"], edgesRemoved: ["A → C"] });
  });

  it("builds coverage rows from the current (maybe unsaved) steps", () => {
    const g = graph([t("T1", [], { requirement_ids: ["R1"] }), t("review", ["T1"], { phase: "review", requirement_ids: ["R2"] })],
      { R1: ["T1"], R2: [], R10: [], R3: [] });
    const rows = coverageRows(g, { R3: "needs a person" });
    expect(rows.map((r) => r.requirementId)).toEqual(["R1", "R2", "R3", "R10"]);
    expect(rows.map((r) => r.status)).toEqual(["covered", "missing", "flagged", "missing"]); // review does not count
    expect(rows[2]!.reason).toBe("needs a person");
  });

  it("nests groups at most three levels deep", () => {
    const tree = groupTree([
      { id: "g-implement", name: "Build", task_ids: [], parent_id: null },
      { id: "g-implement-p1", name: "Part A", task_ids: [], parent_id: "g-implement" },
      { id: "g-implement-p1-x", name: "Messaging", task_ids: ["T1"], parent_id: "g-implement-p1" },
      { id: "g-test", name: "Test", task_ids: ["T2"], parent_id: null },
    ]);
    expect(tree.map((n) => n.group.name)).toEqual(["Build", "Test"]);
    expect(tree[0]!.children[0]!.children[0]!.group.task_ids).toEqual(["T1"]);
  });

  it("describes step states in words", () => {
    expect(stepStatus("COMPLETED")).toEqual({ tone: "success", label: "Done" });
    expect(stepStatus("RUNNING").label).toBe("Working");
    expect(stepStatus(undefined).label).toBe("Not started");
    expect(stepStatus("BLOCKED").tone).toBe("danger");
  });
});
