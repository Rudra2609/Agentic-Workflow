/** Pure helpers for the Research tab (unit-tested in logic.test.ts): plain words, grouping, citations, excerpts. */
import type { Tone } from "@/lib/plain";

import type { Claim, Evidence, Report, Source, SubQuestion, SubStatus } from "./types";

export const STOP_TEXT: Record<string, string> = {
  all_covered: "Every sub-question was answered by sources.",
  low_novelty: "New searches stopped finding anything new, so it stopped.",
  max_rounds: "Reached the maximum number of search rounds.",
  budget: "Used its token or time budget.",
  cancelled: "Stopped because the step was cancelled.",
  no_sources: "No usable source was found (offline, or nothing relevant in the saved pages).",
};

export function stopText(reason: string | null | undefined): string {
  return reason ? STOP_TEXT[reason] ?? reason.replace(/_/g, " ") : "Researching…";
}

export const STATUS_TEXT: Record<SubStatus, { label: string; tone: Tone }> = {
  covered: { label: "answered", tone: "success" },
  partial: { label: "partly answered", tone: "warning" },
  open: { label: "not answered", tone: "danger" },
  exhausted: { label: "no more searches", tone: "muted" },
};

export function percent(x: number | null | undefined): string {
  return x === null || x === undefined || Number.isNaN(x) ? "—" : `${Math.round(x * 100)}%`;
}

export const MODE_TEXT: Record<string, string> = {
  online: "Online: searches the web",
  cached: "Offline: saved pages only",
  local: "Local documents only",
};

/** Sub-questions grouped under the question they belong to (in order). */
export function groupByQuestion(report: Pick<Report, "questions" | "sub_questions">): { question: string; subs: SubQuestion[] }[] {
  return report.questions.map((q, i) => ({ question: q, subs: report.sub_questions.filter((s) => s.question === i) }));
}

/** The sub-question a claim answers: the sub-question of its first cited evidence. */
export function claimsBySub(report: Pick<Report, "claims" | "evidence">): Map<string, Claim[]> {
  const subOf = new Map(report.evidence.map((e) => [e.id, e.sub_question ?? ""]));
  const out = new Map<string, Claim[]>();
  for (const c of report.claims) {
    const sub = c.evidence_ids.map((id) => subOf.get(id)).find(Boolean) ?? "";
    out.set(sub, [...(out.get(sub) ?? []), c]);
  }
  return out;
}

/** Source number per URL, in order of first citation (like the written report). */
export function sourceNumbers(report: Pick<Report, "claims" | "evidence">): Map<string, number> {
  const byId = new Map(report.evidence.map((e) => [e.id, e]));
  const out = new Map<string, number>();
  for (const c of report.claims) {
    for (const id of c.evidence_ids) {
      const e = byId.get(id);
      if (e && !out.has(e.url)) out.set(e.url, out.size + 1);
    }
  }
  for (const e of report.evidence) if (!out.has(e.url)) out.set(e.url, out.size + 1);
  return out;
}

export function host(url: string): string {
  if (url.startsWith("project://")) return "your documents";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Only http(s) links are rendered as links (a page could carry javascript: or other schemes). */
export function safeHref(url: string): string | undefined {
  return /^https?:\/\//i.test(url) ? url : undefined;
}

export const KIND_TEXT: Record<string, string> = { wiki: "encyclopaedia", arxiv: "paper", web: "web page", local: "your document" };

export function scoreParts(s: Pick<Source, "score_breakdown">): { label: string; value: number }[] {
  const names: Record<string, string> = { relevance: "relevance", authority: "source quality", recency: "recency", novelty: "new information" };
  return Object.entries(s.score_breakdown).map(([k, v]) => ({ label: names[k] ?? k, value: v }));
}

export interface Excerpt {
  before: string;
  mark: string;
  after: string;
  cutStart: boolean;
  cutEnd: boolean;
}

/** The highlighted quote with up to ``radius`` characters around it, cut at word boundaries. */
export function excerpt(text: string, start: number, end: number, radius = 320): Excerpt {
  let a = Math.max(0, start - radius);
  let b = Math.min(text.length, end + radius);
  if (a > 0) a = text.indexOf(" ", a) + 1 || a;
  if (b < text.length) b = text.lastIndexOf(" ", b) > end ? text.lastIndexOf(" ", b) : b;
  return { before: text.slice(a, start), mark: text.slice(start, end), after: text.slice(end, b), cutStart: a > 0, cutEnd: b < text.length };
}

/** Changes when research progresses or finishes: the panel refetches. */
export function researchEventKey(events: readonly { event_type: string; seq: number; data?: Record<string, unknown> }[]): string {
  const mine = events.filter((e) => e.event_type === "research.completed" || (e.event_type === "task.progress" && JSON.stringify(e.data ?? {}).includes("research-trace")));
  return `${mine.length}:${mine.at(-1)?.seq ?? 0}`;
}

export function evidenceFor(report: Pick<Report, "evidence">, ids: readonly string[]): Evidence[] {
  const byId = new Map(report.evidence.map((e) => [e.id, e]));
  return ids.map((i) => byId.get(i)).filter((e): e is Evidence => Boolean(e));
}

/** Questions typed in the "research a question" box: one per line, 1-5, each at most 300 characters. */
export function parseQuestions(raw: string): string[] {
  return raw
    .split("\n")
    .map((q) => q.trim())
    .filter((q) => q.length >= 5)
    .slice(0, 5)
    .map((q) => q.slice(0, 300));
}

/** Evidence grouped by source URL, in first-seen order: one citation chip per source. */
export function bySource(evidence: readonly Evidence[]): Evidence[][] {
  const groups = new Map<string, Evidence[]>();
  for (const e of evidence) groups.set(e.url, [...(groups.get(e.url) ?? []), e]);
  return [...groups.values()];
}
