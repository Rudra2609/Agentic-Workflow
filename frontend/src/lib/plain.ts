/**
 * Plain-language translations for the simple mode: capabilities -> team roles, states -> sentences, events ->
 * activity lines. Pure functions (unit-tested). They describe what the backend reports, never more: unknown values
 * fall back to a humanized form of the raw value instead of an invented meaning.
 */
import { humanize } from "./format";
import type { HmapEvent, ProjectState, TaskState } from "./types";

export interface Role {
  name: string;
  does: string;
}

/** Each real capability of the platform (backend `core/contracts/capabilities.py`) as a team role. */
export const ROLES: Record<string, Role> = {
  "document.extract": { name: "Analyst", does: "Reads your request or documents and lists the requirements." },
  "plan.generate": { name: "Planner", does: "Turns the requirements into a step-by-step plan." },
  "research.run": { name: "Researcher", does: "Finds and organizes information." },
  "verify.claims": { name: "Fact-checker", does: "Checks research findings against their sources." },
  "code.implement": { name: "Developer", does: "Writes the code." },
  "test.run": { name: "Tester", does: "Runs tests against the code." },
  "docs.generate": { name: "Writer", does: "Prepares documentation and reports." },
  "review.final": { name: "Reviewer", does: "Reviews the finished work against the requirements." },
  echo: { name: "Echo", does: "Repeats a message back. Used to check that the system is working." },
};

export function roleOf(capability: string): Role {
  return ROLES[capability] ?? { name: humanize(capability), does: `Handles “${capability}” work.` };
}

export type Tone = "neutral" | "progress" | "success" | "warning" | "danger" | "muted";

export interface StateText {
  label: string;
  explain: string;
  tone: Tone;
}

export const PROJECT_STATE_TEXT: Record<ProjectState, StateText> = {
  CREATED: { label: "Not started", explain: "Describe a goal or add a document to start.", tone: "neutral" },
  INGESTING: { label: "Understanding", explain: "Your AI team is reading the request and planning the work.", tone: "progress" },
  PLANNING: { label: "Planning", explain: "Your AI team is preparing a plan.", tone: "progress" },
  AWAITING_APPROVAL: { label: "Needs your review", explain: "Your plan is ready. Review it before work continues.", tone: "warning" },
  EXECUTING: { label: "Working", explain: "Your AI team is working through the plan.", tone: "progress" },
  REVIEWING: { label: "Reviewing", explain: "The finished work is being reviewed.", tone: "progress" },
  COMPLETED: { label: "Completed", explain: "All steps finished successfully.", tone: "success" },
  FAILED: { label: "Couldn't finish", explain: "A step could not be completed. Open the issue for details.", tone: "danger" },
  CANCELLED: { label: "Stopped", explain: "This work was stopped.", tone: "muted" },
};

export function projectStateText(state: string): StateText {
  return PROJECT_STATE_TEXT[state as ProjectState] ?? { label: humanize(state), explain: "", tone: "neutral" };
}

export const TASK_STATE_TEXT: Record<TaskState, StateText> = {
  CREATED: { label: "Waiting", explain: "Waiting for earlier steps (or your approval) before it can start.", tone: "neutral" },
  READY: { label: "Ready", explain: "Ready to start as soon as a team member is free.", tone: "neutral" },
  ASSIGNED: { label: "Assigned", explain: "Handed to a team member.", tone: "progress" },
  ACCEPTED: { label: "Starting", explain: "A team member accepted this step.", tone: "progress" },
  RUNNING: { label: "Working", explain: "A team member is working on this step.", tone: "progress" },
  RESULT_SUBMITTED: { label: "Finishing", explain: "The result was handed in and is being recorded.", tone: "progress" },
  REVIEWING: { label: "In review", explain: "The result is being reviewed.", tone: "progress" },
  COMPLETED: { label: "Done", explain: "This step finished successfully.", tone: "success" },
  BLOCKED: { label: "Blocked", explain: "An earlier step it depends on did not finish, so it cannot start.", tone: "warning" },
  CANCELLED: { label: "Stopped", explain: "This step was stopped.", tone: "muted" },
  RETRY_SCHEDULED: { label: "Retrying soon", explain: "Something went wrong temporarily; it will be tried again.", tone: "warning" },
  DEAD_LETTERED: { label: "Gave up", explain: "It failed every retry and needs a person to look at it.", tone: "danger" },
  FAILED: { label: "Failed", explain: "This step could not be completed.", tone: "danger" },
  NEEDS_REVISION: { label: "Needs changes", explain: "The reviewer asked for changes.", tone: "warning" },
};

export function taskStateText(state: string): StateText {
  return TASK_STATE_TEXT[state as TaskState] ?? { label: humanize(state), explain: "", tone: "neutral" };
}

export const ACTIVE_PROJECT_STATES: ReadonlySet<string> = new Set([
  "INGESTING", "PLANNING", "AWAITING_APPROVAL", "EXECUTING", "REVIEWING",
]);
export const NEEDS_ATTENTION_STATES: ReadonlySet<string> = new Set(["AWAITING_APPROVAL", "FAILED"]);
export const FAILED_TASK_STATES: ReadonlySet<string> = new Set(["FAILED", "DEAD_LETTERED"]);

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}

/**
 * One human sentence for an event, or null when it is too low-level for the simple activity view (progress pings,
 * internal assignment hops). `taskTitle` resolves task ids to their step names when known.
 */
export function describeEvent(e: HmapEvent, taskTitle?: (taskId: string) => string | undefined): string | null {
  const d = e.data ?? {};
  const cap = str(d.capability);
  const step = taskTitle?.(e.aggregate_id) ?? (cap ? roleOf(cap).name : "A step");
  switch (e.event_type) {
    case "project.created":
      return `Project “${str(d.name) ?? "Untitled"}” was created.`;
    case "project.ingesting":
      return "Your AI team started reading the request.";
    case "document.uploaded": {
      if (str(d.source) === "goal") return "Your request was received.";
      const files = Array.isArray(d.files) ? (d.files as Array<{ folder?: unknown }>) : [];
      if (files.length > 1) {
        const folders = new Set(files.map((f) => str(f.folder)).filter(Boolean)).size;
        return `${files.length} documents were added${folders ? ` from ${folders} folder${folders === 1 ? "" : "s"}` : ""}.`;
      }
      return `Document “${str(d.filename) ?? "file"}” was added.`;
    }
    case "approval.requested":
      return "Your plan is ready for review.";
    case "approval.decided":
      if (d.auto === true) return "The plan was approved automatically (this project runs without a review step).";
      return d.approved === true ? "You approved the plan." : "The plan was rejected.";
    case "project.executing":
      return "Work on the plan started.";
    case "project.completed":
      return "All work finished successfully.";
    case "project.failed":
      return "The work could not be completed.";
    case "project.cancelled":
      return `Work was stopped${str(d.reason) && d.reason !== "stopped by user" ? ` (${String(d.reason)})` : ""}.`;
    case "project.updated":
      return d.archived === true ? "The project was archived." : d.archived === false ? "The project was restored." : "The project was renamed.";
    case "project.deleted":
      return "The project was deleted.";
    case "task.started":
      return `${step} started.`;
    case "task.completed":
      return `${step} finished.`;
    case "task.failed":
      return `${step} could not be completed.`;
    case "task.dead_lettered":
      return `${step} failed after every retry and needs attention.`;
    case "task.retrying":
      return `${step} hit a temporary problem and will be retried.`;
    case "task.blocked":
      return `${step} cannot start because an earlier step did not finish.`;
    case "task.cancelled":
      return `${step} was stopped.`;
    case "agent.offline":
      return `A team member (${cap ? roleOf(cap).name : "worker"}) went offline.`;
    case "agent.recovered":
      return "A team member is back online.";
    default:
      return null;
  }
}

export function eventTone(type: string): Tone {
  if (/\.(failed|dead_lettered)$/.test(type) || type === "agent.offline") return "danger";
  if (type === "approval.requested" || type === "task.retrying" || type === "task.blocked") return "warning";
  if (/\.(completed)$/.test(type) || type === "agent.recovered") return "success";
  if (/\.(cancelled|deleted)$/.test(type)) return "muted";
  return "neutral";
}

/** "Good morning" etc. for the workspace greeting (local time). */
export function greeting(date: Date = new Date()): string {
  const h = date.getHours();
  return h < 5 ? "Good evening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

/** A project name from a typed goal: its first line/sentence, trimmed to ~60 characters. */
export function nameFromGoal(goal: string): string {
  const first = goal.trim().split(/\n|(?<=[.!?])\s/)[0]?.trim() ?? "";
  const clean = first.replace(/[.!?]+$/, "");
  if (!clean) return "Untitled project";
  return clean.length > 60 ? `${clean.slice(0, 57).trimEnd()}…` : clean;
}
