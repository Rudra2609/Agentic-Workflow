/** Pure helpers for the Operations page (unit-tested in logic.test.ts). */
import type { Tone } from "@/lib/plain";

import type { Explanation, TaskRow } from "./types";

export const VERDICT_TONE: Record<string, Tone> = {
  completed: "success",
  running: "progress",
  waiting: "neutral",
  retrying: "warning",
  blocked: "warning",
  cancelled: "muted",
  failed: "danger",
  dead_lettered: "danger",
};

export const VERDICT_LABEL: Record<string, string> = {
  completed: "Finished",
  running: "Running",
  waiting: "Not started",
  retrying: "Retrying",
  blocked: "Blocked",
  cancelled: "Cancelled",
  failed: "Failed",
  dead_lettered: "Gave up (dead letter)",
};

export function verdictTone(status: string): Tone {
  return VERDICT_TONE[status] ?? "neutral";
}

export function errorLine(err: TaskRow["last_error"]): string {
  if (!err) return "—";
  return [err.code, err.message].filter(Boolean).join(": ").slice(0, 160) || "—";
}

/** Where a task id in the URL comes from: `?task=` (deep links from a project's step inspector). */
export function taskFromSearch(search: string): string | null {
  const id = new URLSearchParams(search).get("task");
  return id && /^[A-Za-z0-9_-]{1,120}$/.test(id) ? id : null;
}

/** A replay reason must say something (it is kept in the audit trail). */
export function reasonProblem(reason: string): string | null {
  const r = reason.trim();
  if (r.length < 3) return "Say briefly why it is safe to try again (it is kept in the history).";
  if (r.length > 500) return "Keep the reason under 500 characters.";
  return null;
}

/** Execution summary line: "Attempt 2 · TIMED_OUT · agent-x · AGENT_UNAVAILABLE". */
export function executionLine(e: Explanation["executions"][number]): string {
  return [`Attempt ${e.attempt}`, e.status.toLowerCase().replace(/_/g, " "), e.agent_id, e.error?.code].filter(Boolean).join(" · ");
}

export function sumValues(rec: Record<string, number>): number {
  return Object.values(rec).reduce((a, b) => a + b, 0);
}
