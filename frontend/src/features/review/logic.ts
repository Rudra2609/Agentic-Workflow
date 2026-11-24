/** Pure helpers of the Review tab (tested in logic.test.ts). */
import type { Tone } from "@/lib/plain";

import type { Decided, Recommendation, Verdict } from "./types";

export const VERDICT_TONE: Record<Verdict, Tone> = {
  PASS: "success",
  PARTIAL: "warning",
  FAIL: "danger",
};

export const RECOMMENDATION_TEXT: Record<Recommendation, string> = {
  PASS: "Passed",
  REVISE: "Revising",
  ESCALATE: "Needs a person",
};

export const RECOMMENDATION_TONE: Record<Recommendation, Tone> = {
  PASS: "success",
  REVISE: "progress",
  ESCALATE: "warning",
};

export const SOURCE_TEXT: Record<Decided["source"], string> = {
  objective: "checks",
  judge: "judge",
  both: "checks + judge",
  none: "not judged",
  human: "a person",
};

export const KIND_TEXT: Record<Decided["item"]["kind"], string> = {
  requirement: "Requirement",
  constraint: "Constraint",
  deliverable: "Deliverable",
  criterion: "Marking criterion",
  change: "Change request",
};

export const CATEGORY_TEXT: Record<string, string> = {
  MISSING: "missing",
  INCORRECT: "incorrect",
  UNTESTED: "untested",
  UNSUPPORTED_CLAIM: "unsupported claim",
  DOC_MISMATCH: "docs do not match the code",
  QUALITY: "quality",
};

export const ACTION_TEXT: Record<string, string> = {
  revise: "revise",
  rerun: "re-run",
  replan: "replan",
  escalate: "ask a person",
  review: "review again",
};

/** Requirements first (must before should / could), then constraints, deliverables, change requests. */
export function sortItems(items: readonly Decided[]): Decided[] {
  const kind = { requirement: 0, constraint: 1, deliverable: 2, change: 3, criterion: 4 } as const;
  const prio: Record<string, number> = { must: 0, should: 1, could: 2 };
  return [...items]
    .filter((d) => d.item.kind !== "criterion")
    .sort(
      (a, b) =>
        kind[a.item.kind] - kind[b.item.kind] ||
        (prio[a.item.priority] ?? 3) - (prio[b.item.priority] ?? 3) ||
        a.item.id.localeCompare(b.item.id, undefined, { numeric: true }),
    );
}

export function counts(items: readonly Decided[]): Record<Verdict, number> {
  const out: Record<Verdict, number> = { PASS: 0, PARTIAL: 0, FAIL: 0 };
  for (const d of items) if (d.item.kind !== "criterion") out[d.verdict] += 1;
  return out;
}

export function percent(x: number | null | undefined): string {
  return x == null ? "–" : `${Math.round(x * 100)} %`;
}

/** Live-reload key: review / revision events and review.final task changes. */
export function reviewEventKey(
  events: readonly { event_type: string; seq: number; data?: Record<string, unknown> }[],
): string {
  const mine = events.filter(
    (e) =>
      e.event_type === "review.completed" ||
      e.event_type === "revision.requested" ||
      e.event_type.startsWith("project.") ||
      (e.event_type.startsWith("task.") && JSON.stringify(e.data ?? {}).includes("review.final")),
  );
  return `${mine.length}:${mine.at(-1)?.seq ?? 0}`;
}

export function taskLabel(
  taskId: string | null,
  tasks: readonly { task_id: string; title: string; capability: string }[],
): string {
  if (!taskId) return "no step covers it";
  const t = tasks.find((x) => x.task_id === taskId);
  return t ? `${t.title || t.capability}` : taskId;
}
