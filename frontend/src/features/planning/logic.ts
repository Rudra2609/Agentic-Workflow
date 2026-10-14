/**
 * Pure helpers for the Plan panel (unit-tested in logic.test.ts): the layered graph layout with crossing reduction,
 * immutable plan edits, a quick local check before saving (the server is the judge), version diffs, the coverage
 * matrix and the group tree.
 */
import type { PlanGroup, PlanPhase, PlanTask, TaskGraph } from "./types";

export const PHASES: PlanPhase[] = ["research", "design", "implement", "test", "document", "review"];
export const PHASE_LABEL: Record<PlanPhase, string> = {
  research: "Research", design: "Design", implement: "Build", test: "Test", document: "Document", review: "Review",
};
export const PRIORITY_LABEL: Record<string, string> = { urgent: "Urgent", high: "High", normal: "Normal", low: "Low" };

// ------------------------------------------------------------------ layout

export const NODE_W = 220;
export const NODE_H = 78;
const GAP_X = 70;
const GAP_Y = 22;

export interface Placed {
  id: string;
  x: number;
  y: number;
  layer: number;
}

/** Longest-path layers (dependencies to the left), then a few barycenter sweeps to reduce edge crossings. */
export function layout(tasks: readonly Pick<PlanTask, "id" | "depends_on">[]): Placed[] {
  const ids = new Set(tasks.map((t) => t.id));
  const deps = new Map(tasks.map((t) => [t.id, t.depends_on.filter((d) => ids.has(d) && d !== t.id)]));
  const layer = new Map<string, number>();
  const visiting = new Set<string>();
  const depth = (id: string): number => {
    const known = layer.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0; // a cycle (only in an unsaved edit): draw it, the server will refuse it
    visiting.add(id);
    const d = Math.max(-1, ...(deps.get(id) ?? []).map(depth)) + 1;
    visiting.delete(id);
    layer.set(id, d);
    return d;
  };
  tasks.forEach((t) => depth(t.id));
  const layers: string[][] = [];
  for (const t of tasks) (layers[layer.get(t.id)!] ??= []).push(t.id);
  for (let i = 0; i < layers.length; i++) layers[i] ??= []; // a cycle can leave a layer empty
  const succ = new Map<string, string[]>();
  for (const [id, ds] of deps) for (const d of ds) succ.set(d, [...(succ.get(d) ?? []), id]);
  const pos = new Map<string, number>();
  const index = () => layers.forEach((row) => row.forEach((id, i) => pos.set(id, i)));
  index();
  const bary = (id: string, near: string[]) =>
    near.length ? near.reduce((s, n) => s + (pos.get(n) ?? 0), 0) / near.length : (pos.get(id) ?? 0);
  for (let sweep = 0; sweep < 4; sweep++) {
    const down = sweep % 2 === 0;
    const order = down ? layers.map((_, i) => i).slice(1) : layers.map((_, i) => i).slice(0, -1).reverse();
    for (const i of order) {
      const row = layers[i]!;
      const key = new Map(row.map((id) => [id, bary(id, down ? (deps.get(id) ?? []) : (succ.get(id) ?? []))]));
      row.sort((a, b) => key.get(a)! - key.get(b)! || a.localeCompare(b));
      index();
    }
  }
  const tallest = Math.max(1, ...layers.map((r) => r.length));
  const out: Placed[] = [];
  layers.forEach((row, l) => {
    const offset = ((tallest - row.length) * (NODE_H + GAP_Y)) / 2; // centre short layers
    row.forEach((id, r) => out.push({ id, layer: l, x: l * (NODE_W + GAP_X), y: offset + r * (NODE_H + GAP_Y) }));
  });
  return out;
}

/** Number of edge crossings between adjacent layers (for tests: the sweeps must not make it worse). */
export function crossings(tasks: readonly Pick<PlanTask, "id" | "depends_on">[], placed: readonly Placed[]): number {
  const at = new Map(placed.map((p) => [p.id, p]));
  const edges = tasks.flatMap((t) => t.depends_on.filter((d) => at.has(d)).map((d) => [at.get(d)!, at.get(t.id)!] as const));
  let n = 0;
  for (let i = 0; i < edges.length; i++) {
    for (let j = i + 1; j < edges.length; j++) {
      const [a1, b1] = edges[i]!;
      const [a2, b2] = edges[j]!;
      if (a1.layer !== a2.layer || b1.layer !== b2.layer) continue;
      if ((a1.y - a2.y) * (b1.y - b2.y) < 0) n++;
    }
  }
  return n;
}

// ------------------------------------------------------------------ edits (immutable)

export function updateTask(g: TaskGraph, id: string, patch: Partial<PlanTask>): TaskGraph {
  return { ...g, tasks: g.tasks.map((t) => (t.id === id ? { ...t, ...patch, id: t.id } : t)) };
}

export function nextTaskId(g: TaskGraph): string {
  const used = new Set(g.tasks.map((t) => t.id));
  let n = 1 + Math.max(0, ...g.tasks.map((t) => /^T(\d+)$/.exec(t.id)).filter(Boolean).map((m) => Number(m![1])));
  while (used.has(`T${n}`)) n++;
  return `T${n}`;
}

export function addTask(g: TaskGraph, title: string, phase: PlanPhase, capability: string): { graph: TaskGraph; id: string } {
  const id = nextTaskId(g);
  const task: PlanTask = {
    id, title: title.trim(), description: "", agent_capability: capability, requirement_ids: [], acceptance_criteria: [],
    depends_on: [], priority: "normal", est_effort: null, phase, research_questions: [],
  };
  return { graph: { ...g, tasks: [...g.tasks, task] }, id };
}

/** Remove a step; its dependants inherit its dependencies, so the order around it is kept. */
export function removeTask(g: TaskGraph, id: string): TaskGraph {
  const gone = g.tasks.find((t) => t.id === id);
  if (!gone) return g;
  const tasks = g.tasks
    .filter((t) => t.id !== id)
    .map((t) =>
      t.depends_on.includes(id)
        ? { ...t, depends_on: [...new Set([...t.depends_on.filter((d) => d !== id), ...gone.depends_on])].filter((d) => d !== t.id) }
        : t,
    );
  const coverage = Object.fromEntries(Object.entries(g.coverage_matrix).map(([r, ids]) => [r, ids.filter((x) => x !== id)]));
  return { ...g, tasks, coverage_matrix: coverage };
}

export function addEdge(g: TaskGraph, before: string, after: string): TaskGraph {
  if (before === after) return g;
  return { ...g, tasks: g.tasks.map((t) => (t.id === after && !t.depends_on.includes(before) ? { ...t, depends_on: [...t.depends_on, before] } : t)) };
}

export function removeEdge(g: TaskGraph, before: string, after: string): TaskGraph {
  return { ...g, tasks: g.tasks.map((t) => (t.id === after ? { ...t, depends_on: t.depends_on.filter((d) => d !== before) } : t)) };
}

/** Would `after` depending on `before` close a loop? (checked before the edge is drawn) */
export function wouldCycle(g: TaskGraph, before: string, after: string): boolean {
  if (before === after) return true;
  const deps = new Map(g.tasks.map((t) => [t.id, t.depends_on]));
  const stack = [before];
  const seen = new Set<string>();
  while (stack.length) {
    const id = stack.pop()!;
    if (id === after) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...(deps.get(id) ?? []));
  }
  return false;
}

/** Quick local problems (the server re-checks everything): empty titles, unknown dependencies, a cycle. */
export function localProblems(g: TaskGraph): string[] {
  const ids = new Set(g.tasks.map((t) => t.id));
  const out: string[] = [];
  for (const t of g.tasks) {
    if (!t.title.trim()) out.push(`${t.id} needs a title.`);
    for (const d of t.depends_on) if (!ids.has(d)) out.push(`${t.id} waits for ${d}, which is not in the plan.`);
  }
  for (const t of g.tasks) {
    if (t.depends_on.some((d) => ids.has(d) && wouldCycle(g, d, t.id))) {
      out.push(`${t.id} is part of a loop: steps would wait for each other forever.`);
      break;
    }
  }
  return out;
}

export function samePlan(a: TaskGraph, b: TaskGraph): boolean {
  return JSON.stringify(a.tasks) === JSON.stringify(b.tasks);
}

// ------------------------------------------------------------------ versions

export interface PlanDiff {
  added: string[];
  removed: string[];
  changed: string[];
  edgesAdded: string[];
  edgesRemoved: string[];
}

export function diffPlans(before: TaskGraph, after: TaskGraph): PlanDiff {
  const a = new Map(before.tasks.map((t) => [t.id, t]));
  const b = new Map(after.tasks.map((t) => [t.id, t]));
  const edges = (g: TaskGraph) => new Set(g.tasks.flatMap((t) => t.depends_on.map((d) => `${d} → ${t.id}`)));
  const ea = edges(before);
  const eb = edges(after);
  const content = (t: PlanTask) => JSON.stringify([t.title, t.description, t.agent_capability, t.phase, t.requirement_ids, t.acceptance_criteria]);
  return {
    added: [...b.keys()].filter((id) => !a.has(id)),
    removed: [...a.keys()].filter((id) => !b.has(id)),
    changed: [...b.keys()].filter((id) => a.has(id) && content(a.get(id)!) !== content(b.get(id)!)),
    edgesAdded: [...eb].filter((e) => !ea.has(e)),
    edgesRemoved: [...ea].filter((e) => !eb.has(e)),
  };
}

// ------------------------------------------------------------------ coverage and groups

export interface CoverageRow {
  requirementId: string;
  taskIds: string[];
  status: "covered" | "flagged" | "missing";
  reason?: string;
}

export function coverageRows(g: TaskGraph, flagged: Record<string, string> = {}): CoverageRow[] {
  const work = new Set(g.tasks.filter((t) => ["implement", "test", "document"].includes(t.phase)).map((t) => t.id));
  const ids = Object.keys(g.coverage_matrix).sort((x, y) => Number(x.slice(1)) - Number(y.slice(1)) || x.localeCompare(y));
  return ids.map((rid) => {
    // recompute from the tasks so unsaved edits show at once
    const taskIds = g.tasks.filter((t) => work.has(t.id) && t.requirement_ids.includes(rid)).map((t) => t.id);
    if (taskIds.length) return { requirementId: rid, taskIds, status: "covered" };
    if (flagged[rid]) return { requirementId: rid, taskIds, status: "flagged", reason: flagged[rid] };
    return { requirementId: rid, taskIds, status: "missing" };
  });
}

export interface GroupNode {
  group: PlanGroup;
  children: GroupNode[];
}

export function groupTree(groups: readonly PlanGroup[]): GroupNode[] {
  const byParent = new Map<string | null, PlanGroup[]>();
  for (const g of groups) byParent.set(g.parent_id, [...(byParent.get(g.parent_id) ?? []), g]);
  const build = (parent: string | null, depth: number): GroupNode[] =>
    depth > 3 ? [] : (byParent.get(parent) ?? []).map((group) => ({ group, children: build(group.id, depth + 1) }));
  return build(null, 1);
}

/** Tone of a step state in plain words (mirrors the core task states). */
export function stepStatus(state: string | undefined): { tone: "neutral" | "progress" | "success" | "warning" | "danger" | "muted"; label: string } {
  switch (state) {
    case undefined:
      return { tone: "muted", label: "Not started" };
    case "COMPLETED":
      return { tone: "success", label: "Done" };
    case "FAILED":
    case "DEAD_LETTERED":
      return { tone: "danger", label: "Failed" };
    case "BLOCKED":
      return { tone: "danger", label: "Blocked" };
    case "CANCELLED":
      return { tone: "muted", label: "Cancelled" };
    case "CREATED":
      return { tone: "neutral", label: "Waiting" };
    default:
      return { tone: "progress", label: "Working" };
  }
}
