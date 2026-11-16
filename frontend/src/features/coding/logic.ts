/** Pure helpers for the Coding tab (unit-tested in logic.test.ts): diff parsing, the tool-call log, words, event key. */
import type { Tone } from "@/lib/plain";

import type { CheckStatus, CodingTrace, Outcome } from "./types";

export type DiffLineKind = "add" | "del" | "ctx" | "hunk" | "meta";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
}

export interface DiffFile {
  path: string;
  status: "added" | "deleted" | "modified";
  added: number;
  removed: number;
  lines: DiffLine[];
}

/** A unified diff (as written by the coding agent) split per file. */
export function parseDiff(diff: string): DiffFile[] {
  const files: DiffFile[] = [];
  let current: DiffFile | null = null;
  let from = "";
  for (const raw of diff.split("\n")) {
    if (raw.startsWith("--- ")) {
      from = raw.slice(4);
      continue;
    }
    if (raw.startsWith("+++ ")) {
      const to = raw.slice(4);
      const path = (to === "/dev/null" ? from : to).replace(/^[ab]\//, "");
      current = { path, status: from === "/dev/null" ? "added" : to === "/dev/null" ? "deleted" : "modified", added: 0, removed: 0, lines: [] };
      files.push(current);
      continue;
    }
    if (!current) continue;
    if (raw.startsWith("@@")) current.lines.push({ kind: "hunk", text: raw });
    else if (raw.startsWith("\\")) current.lines.push({ kind: "meta", text: raw });
    else if (raw.startsWith("+")) {
      current.added += 1;
      current.lines.push({ kind: "add", text: raw.slice(1) });
    } else if (raw.startsWith("-")) {
      current.removed += 1;
      current.lines.push({ kind: "del", text: raw.slice(1) });
    } else if (raw.startsWith(" ")) current.lines.push({ kind: "ctx", text: raw.slice(1) });
  }
  return files;
}

export const OUTCOME_TEXT: Record<Exclude<Outcome, "">, { label: string; tone: Tone; help: string }> = {
  success: { label: "done", tone: "success", help: "Every check the agent ran passes." },
  partial: { label: "not finished", tone: "warning", help: "The budget ran out with checks failing, or no model answered. The next steps still run." },
  failure: { label: "failed", tone: "danger", help: "The workspace could not be loaded or stored." },
};

export const CHECK_TONE: Record<CheckStatus, Tone> = { passed: "success", failed: "danger", skipped: "muted" };

export const STOP_TEXT: Record<string, string> = {
  checks_pass: "the checks pass",
  checks_fail: "the checks still fail",
  plateau: "two fix rounds in a row did not help",
  max_iters: "the fix-round limit was reached",
  budget: "the token budget was used up",
  step_budget: "the model-call limit was reached",
  no_model: "no model answered (offline / not recorded)",
  time_limit: "the safety time limit was reached",
  revision_limit: "the revision limit was reached",
  error: "an error stopped the self-review",
};

export const STEP_TEXT: Record<string, string> = {
  plan: "Planned the change",
  edit: "Edited the code",
  debug: "Fixed a failing check",
  review: "Self-review fix",
  revise: "Revision",
  locate: "Located files",
};

export type LogEntry =
  | { kind: "step"; step: number; label: string; detail: string; tokens: number; ok: boolean }
  | { kind: "edit"; step: number; ok: boolean; detail: string }
  | { kind: "command"; step: number; ok: boolean; cmd: string; detail: string; output: string };

/** Steps, edits and commands of a trace as one ordered tool-call log. */
export function toolLog(trace: CodingTrace): LogEntry[] {
  const out: { order: number; entry: LogEntry }[] = [];
  trace.steps.forEach((s, i) =>
    out.push({ order: s.n * 1000 + i, entry: { kind: "step", step: s.n, label: STEP_TEXT[s.kind] ?? s.kind, detail: s.summary, tokens: s.prompt_tokens + s.completion_tokens, ok: s.ok } }),
  );
  trace.edits.forEach((e, i) =>
    out.push({
      order: e.step * 1000 + 200 + i,
      entry: { kind: "edit", step: e.step, ok: e.ok, detail: e.ok ? (e.files.length ? `changed ${e.files.join(", ")}` : e.notes.join("; ") || "no change") : `refused: ${e.error ?? ""}` },
    }),
  );
  trace.commands.forEach((c, i) =>
    out.push({
      order: c.step * 1000 + 500 + i,
      entry: {
        kind: "command",
        step: c.step,
        ok: !c.denied && !c.timed_out && c.exit_code === 0,
        cmd: c.cmd,
        detail: c.denied ? `denied: ${c.denied}` : c.timed_out ? "timed out (killed)" : `exit ${c.exit_code} · ${c.duration_s.toFixed(1)} s`,
        output: c.output,
      },
    }),
  );
  return out.sort((a, b) => a.order - b.order).map((x) => x.entry);
}

export function runTitle(capability: string, round: number): string {
  return capability === "code.revise" ? `Revision${round ? ` (round ${round})` : ""}` : "Code change";
}

export function baseText(base: string, template: string | null): string {
  if (template) return `started from the ${template.replaceAll("_", " ")} template`;
  return (
    { inputs: "started from a given workspace", head: "started from the project's code so far", upstream: "started from the previous step's code", empty: "started from an empty folder" }[
      base
    ] ?? base
  );
}

/** Refetch key: changes when a coding step reports progress or finishes. */
export function codingEventKey(events: readonly { event_type: string; seq: number; data?: Record<string, unknown> }[]): string {
  const mine = events.filter((e) => e.event_type === "code.completed" || (e.event_type.startsWith("task.") && JSON.stringify(e.data ?? {}).includes("code.")));
  return `${mine.length}:${mine.at(-1)?.seq ?? 0}`;
}

/** One change per non-empty line of the "Request changes" box. */
export function parseChanges(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.replace(/^[-*•]\s*/, "").trim())
    .filter(Boolean)
    .slice(0, 10);
}
