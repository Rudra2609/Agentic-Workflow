/**
 * The project's real pipeline, derived only from backend data (tasks, approvals, runs):
 *
 *   Request -> Understanding (document.extract) -> Plan (plan.generate) -> Review (approval) -> Work (plan tasks)
 *
 * plus a layered layout of the plan tasks' dependency graph for the workflow canvas. Pure and unit-tested.
 */
import type { Approval, Project, Run, Task } from "./types";
import { FAILED_TASK_STATES } from "./plain";

/** "brief.pdf", or "4 documents in 3 folders (Part A, Part B, Part C)". */
export function documentsSummary(documents: readonly string[]): string {
  if (documents.length === 1) return documents[0]!;
  const folders = [...new Set(documents.map((d) => (d.includes("/") ? d.slice(0, d.lastIndexOf("/")) : null)).filter((f): f is string => f !== null))];
  const base = `${documents.length} documents`;
  if (folders.length === 0) return base;
  const listed = folders.length <= 4 ? ` (${folders.join(", ")})` : "";
  return `${base} in ${folders.length} folder${folders.length === 1 ? "" : "s"}${listed}`;
}

export type StageStatus = "done" | "active" | "waiting" | "pending" | "failed" | "stopped" | "skipped";

export interface Stage {
  id: "request" | "understanding" | "plan" | "review" | "work";
  title: string;
  status: StageStatus;
  detail: string;
  /** The task behind the stage, when there is one (inspector target). */
  taskId?: string;
}

const RUNNING_TASK = new Set(["ASSIGNED", "ACCEPTED", "RUNNING", "RESULT_SUBMITTED", "REVIEWING", "READY", "RETRY_SCHEDULED", "NEEDS_REVISION"]);

export function runOf(task: Pick<Task, "run">): number {
  return task.run ?? 1;
}

export function currentRun(project: Pick<Project, "runs">): number {
  return project.runs && project.runs.length > 0 ? project.runs[project.runs.length - 1]!.number : 1;
}

function taskStage(task: Task | undefined, project: Project, isCurrent: boolean): StageStatus {
  if (!task) return "pending";
  if (task.state === "COMPLETED") return "done";
  if (FAILED_TASK_STATES.has(task.state)) return "failed";
  if (task.state === "CANCELLED") return "stopped";
  if (task.state === "BLOCKED") return "failed";
  if (RUNNING_TASK.has(task.state)) return isCurrent && project.state === "CANCELLED" ? "stopped" : "active";
  return "pending";
}

/** Approvals requested during this run (runs do not overlap, so time decides). */
export function approvalsOfRun(approvals: readonly Approval[], runs: readonly Run[], run: number): Approval[] {
  const me = runs.find((r) => r.number === run);
  if (!me) return run === 1 ? [...approvals] : [];
  const next = runs.find((r) => r.number === run + 1);
  return approvals.filter(
    (a) => a.requested_at >= me.started_at && (!next || a.requested_at < next.started_at),
  );
}

export function stagesOf(project: Project, tasks: readonly Task[], run: number): Stage[] {
  const mine = tasks.filter((t) => runOf(t) === run);
  const isCurrent = run === currentRun(project);
  const runRec = project.runs?.find((r) => r.number === run);
  const extract = mine.filter((t) => t.capability === "document.extract").at(-1);
  const plan = mine.filter((t) => t.capability === "plan.generate").at(-1);
  const work = mine.filter((t) => t.plan_task_id !== null);
  const approvals = approvalsOfRun(project.approvals ?? [], project.runs ?? [], run);
  const approval = approvals.at(-1);

  const request: Stage = {
    id: "request",
    title: "Request",
    status: runRec || mine.length > 0 ? "done" : "pending",
    detail: runRec?.goal ? "Your request was received." : runRec?.documents.length ? `Received ${documentsSummary(runRec.documents)}.` : "Waiting for a request or document.",
  };
  const understanding: Stage = {
    id: "understanding",
    title: "Understanding",
    status: taskStage(extract, project, isCurrent),
    detail: extract ? "Requirements pulled out of your request." : "Not started yet.",
    taskId: extract?.task_id,
  };
  const planStage: Stage = {
    id: "plan",
    title: "Plan",
    status: taskStage(plan, project, isCurrent),
    detail: plan ? (work.length ? `${work.length} steps planned.` : "Preparing the plan.") : "Comes after the requirements.",
    taskId: plan?.task_id,
  };

  let review: Stage;
  if (approval?.status === "approved") {
    const auto = approval.comment?.startsWith("auto-approved") ?? false;
    review = { id: "review", title: "Review", status: auto ? "skipped" : "done", detail: auto ? "Approved automatically (no review step)." : "You approved the plan." };
  } else if (approval?.status === "rejected") {
    review = { id: "review", title: "Review", status: "stopped", detail: approval.comment?.startsWith("project stopped") ? "Closed when the work was stopped." : "The plan was rejected." };
  } else if (approval?.status === "pending" && isCurrent && project.state === "AWAITING_APPROVAL") {
    review = { id: "review", title: "Review", status: "waiting", detail: "Your plan is ready. Review it before work continues." };
  } else if (work.length > 0) {
    review = { id: "review", title: "Review", status: "skipped", detail: "This plan did not need a review." };
  } else {
    review = { id: "review", title: "Review", status: "pending", detail: project.auto_approve ? "Will be approved automatically." : "You'll review the plan here." };
  }

  let workStatus: StageStatus = "pending";
  if (work.length > 0) {
    if (work.every((t) => t.state === "COMPLETED")) workStatus = "done";
    else if (work.some((t) => FAILED_TASK_STATES.has(t.state) || t.state === "BLOCKED") && work.every((t) => t.state !== "RUNNING" && !RUNNING_TASK.has(t.state))) workStatus = "failed";
    else if (isCurrent && project.state === "CANCELLED") workStatus = "stopped";
    else if (runRec?.outcome === "CANCELLED") workStatus = "stopped";
    else if (work.some((t) => RUNNING_TASK.has(t.state) || t.state === "COMPLETED")) workStatus = "active";
    else if (review.status === "waiting") workStatus = "pending";
    else workStatus = work.every((t) => t.state === "CANCELLED") ? "stopped" : "active";
  }
  const done = work.filter((t) => t.state === "COMPLETED").length;
  const workStage: Stage = {
    id: "work",
    title: "Work",
    status: workStatus,
    detail: work.length ? `${done} of ${work.length} steps done.` : "Starts once the plan is approved.",
  };
  return [request, understanding, planStage, review, workStage];
}

// ------------------------------------------------------------------ dependency-graph layout

export interface LayoutNode {
  id: string;
  layer: number;
  row: number;
  x: number;
  y: number;
}

export interface LayoutEdge {
  from: string;
  to: string;
  path: string;
}

export interface GraphLayout {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  width: number;
  height: number;
}

export const NODE_W = 208;
export const NODE_H = 64;
const GAP_X = 56;
const GAP_Y = 16;

/**
 * Layered layout: a node's column is the length of its longest dependency chain, rows keep the plan order. Edges are
 * cubic curves from the right edge of a dependency to the left edge of its dependant. Unknown dependency ids (not in
 * `nodes`) are ignored; cycles cannot occur (the backend validates task graphs).
 */
export function layoutGraph(items: readonly { id: string; dependsOn: readonly string[] }[]): GraphLayout {
  const ids = new Set(items.map((i) => i.id));
  const deps = new Map(items.map((i) => [i.id, i.dependsOn.filter((d) => ids.has(d))]));
  const layer = new Map<string, number>();
  const visiting = new Set<string>();
  const depth = (id: string): number => {
    const known = layer.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0; // defensive: treat a cycle as a root
    visiting.add(id);
    const d = Math.max(-1, ...(deps.get(id) ?? []).map(depth)) + 1;
    visiting.delete(id);
    layer.set(id, d);
    return d;
  };
  items.forEach((i) => depth(i.id));

  const rows = new Map<number, number>();
  const nodes: LayoutNode[] = items.map((i) => {
    const l = layer.get(i.id) ?? 0;
    const r = rows.get(l) ?? 0;
    rows.set(l, r + 1);
    return { id: i.id, layer: l, row: r, x: l * (NODE_W + GAP_X), y: r * (NODE_H + GAP_Y) };
  });
  const at = new Map(nodes.map((n) => [n.id, n]));
  const edges: LayoutEdge[] = [];
  for (const i of items) {
    for (const d of deps.get(i.id) ?? []) {
      const a = at.get(d)!;
      const b = at.get(i.id)!;
      const x1 = a.x + NODE_W;
      const y1 = a.y + NODE_H / 2;
      const x2 = b.x;
      const y2 = b.y + NODE_H / 2;
      const mid = (x1 + x2) / 2;
      edges.push({ from: d, to: i.id, path: `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}` });
    }
  }
  const layers = Math.max(0, ...nodes.map((n) => n.layer)) + (nodes.length ? 1 : 0);
  const maxRows = Math.max(0, ...rows.values());
  return {
    nodes,
    edges,
    width: Math.max(0, layers * NODE_W + Math.max(0, layers - 1) * GAP_X),
    height: Math.max(0, maxRows * NODE_H + Math.max(0, maxRows - 1) * GAP_Y),
  };
}
