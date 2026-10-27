/** Pure helpers for the Verify tab (unit-tested in logic.test.ts): verdict words, layer summaries, event key. */
import type { Tone } from "@/lib/plain";

import type { AtomCheck, ClaimCheck, Verdict } from "./types";

export const VERDICT_TEXT: Record<Verdict, { label: string; tone: Tone; help: string }> = {
  VERIFIED: { label: "verified", tone: "success", help: "Its quotes are in the saved pages and state the claim." },
  UNSUPPORTED: { label: "unsupported", tone: "danger", help: "A quote does not check out, or the quotes do not state the claim." },
  CONFLICTING: { label: "conflicting", tone: "warning", help: "The quotes support it, but another source says otherwise." },
  NEEDS_MORE_RESEARCH: { label: "needs more research", tone: "progress", help: "The check was unsure; more evidence is needed." },
};

export const VERDICT_ORDER: Verdict[] = ["UNSUPPORTED", "CONFLICTING", "NEEDS_MORE_RESEARCH", "VERIFIED"];

export const LABEL_TEXT: Record<string, string> = {
  supports: "support the claim",
  refutes: "contradict the claim",
  not_enough: "do not state the claim",
};

export const L1_TEXT: Record<string, string> = {
  ok: "quote found word for word, page hash matches",
  unknown_evidence: "cites evidence the report does not contain",
  page_missing: "the saved page is missing",
  hash_mismatch: "the page does not match its hash",
  url_mismatch: "the evidence points at another page",
  quote_not_found: "the quote is not in the saved page",
};

export function isFlagged(v: Verdict): boolean {
  return v !== "VERIFIED";
}

/** Claims sorted for review: flagged first (worst first), then by id. */
export function sortClaims(claims: readonly ClaimCheck[]): ClaimCheck[] {
  return [...claims].sort((a, b) => VERDICT_ORDER.indexOf(a.verdict) - VERDICT_ORDER.indexOf(b.verdict) || a.claim_id.localeCompare(b.claim_id, undefined, { numeric: true }));
}

export interface LayerStep {
  layer: "L1" | "L2" | "L3" | "L4";
  state: "pass" | "fail" | "warn" | "skip";
  text: string;
}

/** One line per layer for an atomic claim, in plain words. */
export function layerSteps(a: AtomCheck): LayerStep[] {
  const out: LayerStep[] = [];
  const bad = a.l1.filter((r) => !r.ok);
  out.push(bad.length
    ? { layer: "L1", state: "fail", text: bad.map((r) => `${r.evidence_id}: ${L1_TEXT[r.reason] ?? r.reason}`).join("; ") }
    : { layer: "L1", state: "pass", text: `${a.l1.length} quote${a.l1.length === 1 ? "" : "s"} found word for word, page hashes match` });
  if (!a.l2) {
    out.push({ layer: "L2", state: "skip", text: bad.length ? "not asked (L1 failed)" : "not run" });
  } else {
    const unsure = a.l2.swapped_label !== null && a.l2.swapped_label !== a.l2.label;
    const state = unsure ? "warn" : a.l2.label === "supports" ? "pass" : "fail";
    const who = a.l2.by === "rules" ? " (rules: no model answered)" : "";
    out.push({ layer: "L2", state, text: `${unsure ? "unsure: the two orders disagreed" : `the quotes ${LABEL_TEXT[a.l2.label] ?? a.l2.label}`}${who}${a.l2.guard ? ` — ${a.l2.guard}` : ""}` });
  }
  if (a.l3_queries.length) {
    out.push({ layer: "L3", state: "pass", text: `own searches: ${a.l3_queries.map((q) => `“${q}”`).join(", ")} → ${a.l3_passages} passage${a.l3_passages === 1 ? "" : "s"}` });
  } else {
    out.push({ layer: "L3", state: "skip", text: a.l2?.label === "supports" ? "no own search" : "not needed" });
  }
  const conflicts = a.l4.filter((c) => c.judgement?.label === "refutes");
  if (!a.l4.length) out.push({ layer: "L4", state: "skip", text: "no other source to compare" });
  else if (conflicts.length) out.push({ layer: "L4", state: "fail", text: `${conflicts.length} source${conflicts.length === 1 ? "" : "s"} say otherwise: ${conflicts.map((c) => c.passage.host).join(", ")}` });
  else out.push({ layer: "L4", state: "pass", text: a.independent_hosts.length ? `agreeing sites: ${a.independent_hosts.join(", ")}` : `${a.l4.length} other passage${a.l4.length === 1 ? "" : "s"} compared, no conflict` });
  return out;
}

export function percent(x: number | null | undefined): string {
  return x === null || x === undefined || Number.isNaN(x) ? "—" : `${Math.round(x * 100)}%`;
}

export function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function safeHref(url: string): string | undefined {
  return /^https?:\/\//i.test(url) ? url : undefined;
}

/** Refetch key: changes when a verification finishes or a verify step reports progress. */
export function verifyEventKey(events: readonly { event_type: string; seq: number; data?: Record<string, unknown> }[]): string {
  const mine = events.filter((e) => e.event_type === "verification.completed" || (e.event_type.startsWith("task.") && JSON.stringify(e.data ?? {}).includes("verify.claims")));
  return `${mine.length}:${mine.at(-1)?.seq ?? 0}`;
}

export interface Excerpt {
  before: string;
  mark: string;
  after: string;
  cutStart: boolean;
  cutEnd: boolean;
}

export function excerpt(text: string, start: number, end: number, radius = 240): Excerpt {
  const a = Math.max(0, start - radius);
  const b = Math.min(text.length, end + radius);
  return { before: text.slice(a, start), mark: text.slice(start, end), after: text.slice(end, b), cutStart: a > 0, cutEnd: b < text.length };
}
