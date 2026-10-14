/** Pure helpers for the Refinement tab (unit-tested in logic.test.ts): plain words, grouping, the score curve, and
 * readable descriptions of what a revision changed. */
import type { Tone } from "@/lib/plain";

import type { Category, DiffChange, Issue, Iteration, RunSummary, Severity, StopReason } from "./types";

export const CATEGORY_TEXT: Record<Category, { label: string; explain: string }> = {
  OMISSION: { label: "Missing", explain: "Something the input asks for is not there." },
  HALLUCINATION: { label: "Not in the source", explain: "Something is not supported by the input (invented or misquoted)." },
  FACTUAL: { label: "Wrong detail", explain: "A fact, number or attribute (priority, kind) is wrong." },
  LOGIC: { label: "Wrong order or logic", explain: "A dependency is missing, the order is wrong, or the reasoning does not hold." },
  REQUIREMENT_VIOLATION: { label: "Requirement not met", explain: "The result does not do what a requirement asks." },
  CONSISTENCY: { label: "Inconsistent", explain: "Parts disagree: duplicates, totals that do not add up, mismatched ids." },
  SCHEMA: { label: "Wrong structure", explain: "A field is missing or has a value that is not allowed." },
  FORMAT: { label: "Broken format", explain: "The result is not well-formed." },
  STYLE: { label: "Unclear", explain: "Vague or hard to check, but not wrong." },
  SAFETY: { label: "Safety", explain: "Unsafe content, secrets or personal data." },
};

export const SEVERITY_ORDER: Severity[] = ["critical", "major", "minor", "info"];
export const SEVERITY_TONE: Record<Severity, Tone> = { critical: "danger", major: "danger", minor: "warning", info: "muted" };
export const SEVERITY_TEXT: Record<Severity, string> = { critical: "critical", major: "major", minor: "minor", info: "note" };

export function categoryText(c: string): { label: string; explain: string } {
  return CATEGORY_TEXT[c as Category] ?? { label: c.toLowerCase().replace(/_/g, " "), explain: "" };
}

export interface IssueGroup {
  category: string;
  label: string;
  explain: string;
  issues: Issue[];
  worst: Severity;
}

/** Issues grouped by category, the groups with the worst problems first, issues inside by severity. */
export function groupIssues(issues: readonly Issue[]): IssueGroup[] {
  const rank = (s: Severity) => SEVERITY_ORDER.indexOf(s);
  const groups = new Map<string, Issue[]>();
  for (const i of issues) groups.set(i.category, [...(groups.get(i.category) ?? []), i]);
  return [...groups.entries()]
    .map(([category, list]) => {
      const sorted = [...list].sort((a, b) => rank(a.severity) - rank(b.severity));
      const t = categoryText(category);
      return { category, label: t.label, explain: t.explain, issues: sorted, worst: sorted[0]!.severity };
    })
    .sort((a, b) => rank(a.worst) - rank(b.worst) || b.issues.length - a.issues.length || a.label.localeCompare(b.label));
}

export function percent(score: number | null | undefined): string {
  return score === null || score === undefined || Number.isNaN(score) ? "—" : `${Math.round(score * 100)}%`;
}

export const STOP_TEXT: Record<StopReason, string> = {
  threshold: "Good enough: the score reached the target.",
  no_critical_issues: "No serious problems were left.",
  plateau: "Stopped improving, so it stopped trying.",
  max_iters: "Reached the maximum number of rounds.",
  budget: "Used its time or token budget.",
  tests_pass: "The checks pass.",
  cancelled: "Stopped because the step was cancelled.",
  error: "A check or a fix failed; the best version so far was kept.",
};

export function stopText(reason: StopReason | null | undefined): string {
  return reason ? STOP_TEXT[reason] ?? reason : "Still checking…";
}

export function strategyText(strategy: string | null | undefined): string | null {
  if (!strategy) return null;
  return (
    { targeted: "Fixed only the flagged parts", full: "Changed approach: reworked the whole result", widen: "Changed approach again: looked at the wider input" } as Record<string, string>
  )[strategy] ?? strategy;
}

export function subjectLabel(run: Pick<RunSummary, "capability" | "subject">): string {
  if (run.capability === "document.extract") return "Requirements";
  if (run.capability === "plan.generate") return "Plan";
  const s = run.subject.replace(/-/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** One line for a run's outcome, in plain words. */
export function outcomeText(run: Pick<RunSummary, "status" | "applied" | "base_score" | "best_score" | "iterations">): string {
  if (run.status === "running") return "Checking…";
  if (run.applied) return `Improved from ${percent(run.base_score)} to ${percent(run.best_score)} in ${run.iterations} round${run.iterations === 1 ? "" : "s"}; the improved version is used.`;
  if (run.iterations === 0) return `Checked: ${percent(run.base_score)}. Nothing needed fixing.`;
  return `Checked: ${percent(run.base_score)}. The fixes did not score higher, so the original is kept.`;
}

export function iterationLabel(index: number): string {
  return index === 0 ? "Original" : `Revision ${index}`;
}

export interface CurvePoint {
  x: number;
  y: number;
  score: number;
  index: number;
}

/** Points of the score curve in a `width` x `height` box (scores 0..1, top = 1), with `pad` pixels of margin. */
export function curvePoints(scores: readonly number[], width: number, height: number, pad = 6): CurvePoint[] {
  if (!scores.length) return [];
  const step = scores.length > 1 ? (width - 2 * pad) / (scores.length - 1) : 0;
  return scores.map((s, i) => {
    const clamped = Math.min(1, Math.max(0, s));
    return { x: scores.length > 1 ? pad + i * step : width / 2, y: pad + (1 - clamped) * (height - 2 * pad), score: s, index: i };
  });
}

export function curvePath(points: readonly CurvePoint[]): string {
  return points.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}

export function bestIndex(scores: readonly number[]): number | null {
  if (!scores.length) return null;
  let best = 0;
  scores.forEach((s, i) => {
    if (s > scores[best]!) best = i;
  });
  return best;
}

/** Totals over a run's iterations (for the summary line). */
export function totals(iterations: readonly Iteration[]): { tokens: number; seconds: number; issues: number } {
  return iterations.reduce(
    (acc, it) => ({ tokens: acc.tokens + it.tokens, seconds: acc.seconds + it.duration_s, issues: acc.issues + it.critique.issues.length }),
    { tokens: 0, seconds: 0, issues: 0 },
  );
}

function short(v: unknown, max = 140): string {
  if (v === null || v === undefined) return "—";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function itemText(v: unknown): string {
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return short(o.text ?? o.name ?? o.title ?? o.criterion ?? v);
  }
  return short(v);
}

const LIST_WORD: Record<string, string> = {
  requirements: "requirement",
  constraints: "constraint",
  deliverables: "deliverable",
  evaluation_criteria: "marking criterion",
  tasks: "step",
};

const FIELD_WORD: Record<string, string> = {
  depends_on: "waits for",
  acceptance_criteria: "acceptance criteria",
  requirement_ids: "requirements",
  priority: "priority",
  type: "type",
  text: "text",
};

export interface ChangeLine {
  kind: "added" | "removed" | "changed";
  text: string;
  detail?: string;
}

/** A diff change from the API as a sentence: "Added requirement R7: …", "Step T5 now waits for T3". */
export function describeChange(c: DiffChange): ChangeLine {
  const parts = c.path.split("/");
  const [list, id, field] = parts;
  const noun = list ? LIST_WORD[list] : undefined;
  if (noun && id && parts.length === 2) {
    const thing = noun === "step" ? "step" : noun;
    if (c.op === "added") return { kind: "added", text: `Added ${thing} ${id}`, detail: itemText(c.after) };
    if (c.op === "removed") return { kind: "removed", text: `Removed ${thing} ${id}`, detail: itemText(c.before) };
  }
  if (noun && id && field) {
    const what = FIELD_WORD[field] ?? field.replace(/_/g, " ");
    const subject = `${noun.charAt(0).toUpperCase()}${noun.slice(1)} ${id}`;
    if (c.added_items || c.removed_items) {
      const add = (c.added_items ?? []).map((x) => short(x, 80));
      const rem = (c.removed_items ?? []).map((x) => short(x, 80));
      const bits = [add.length ? `now ${field === "depends_on" ? "waits for" : "has"} ${add.join(", ")}` : "", rem.length ? `no longer ${field === "depends_on" ? "waits for" : "has"} ${rem.join(", ")}` : ""].filter(Boolean);
      return { kind: "changed", text: `${subject}: ${what} — ${bits.join("; ")}` };
    }
    return { kind: "changed", text: `${subject}: ${what} changed`, detail: `${short(c.before, 70)} → ${short(c.after, 70)}` };
  }
  const where = c.path || "the result";
  if (c.op === "added") return { kind: "added", text: `Added ${where}`, detail: short(c.after) };
  if (c.op === "removed") return { kind: "removed", text: `Removed ${where}`, detail: short(c.before) };
  return { kind: "changed", text: `Changed ${where}`, detail: `${short(c.before, 70)} → ${short(c.after, 70)}` };
}

/** The latest refine.* event count: the panel refetches when it changes. */
export function refineEventKey(events: readonly { event_type: string; seq: number }[]): string {
  const mine = events.filter((e) => e.event_type.startsWith("refine.") || e.event_type === "task.completed");
  return `${mine.length}:${mine.at(-1)?.seq ?? 0}`;
}
