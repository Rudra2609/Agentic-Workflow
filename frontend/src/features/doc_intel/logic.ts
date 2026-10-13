/** Pure helpers for the requirements panel (unit-tested in logic.test.ts). */
import type { Tone } from "@/lib/plain";

import type { Block, DocumentModel, Priority, Requirement, RequirementSet, SourceDocument, SourceRef } from "./types";

/** 1.0 is only ever set by a person (the extractor tops out at 0.95): "Confirm" in the panel, or an added item. */
export const CONFIRMED = 1;

export function confidenceLevel(c: number): { label: string; tone: Tone } {
  if (c >= CONFIRMED) return { label: "Checked by a person", tone: "success" };
  if (c >= 0.85) return { label: "High confidence", tone: "success" };
  if (c >= 0.6) return { label: "Check this", tone: "warning" };
  return { label: "Low confidence", tone: "danger" };
}

export const PRIORITY_LABEL: Record<Priority, string> = { must: "Must", should: "Should", could: "Could" };

export const CONSTRAINT_LABEL: Record<string, string> = {
  technology: "Technology", format: "Format", process: "Process", resource: "Resources", other: "Other",
};

/** Requirements grouped by upload folder (Part A, Part B, ...) in first-seen order; one group without folders. */
export function groupByFolder(reqs: readonly Requirement[]): Array<{ folder: string | null; items: Requirement[] }> {
  const groups = new Map<string, { folder: string | null; items: Requirement[] }>();
  for (const r of reqs) {
    const key = r.source_ref.folder ?? "";
    if (!groups.has(key)) groups.set(key, { folder: r.source_ref.folder, items: [] });
    groups.get(key)!.items.push(r);
  }
  return [...groups.values()];
}

export interface MarksSummary {
  sum: number;
  total: number | null;
  consistent: boolean;
}

export function marksSummary(rs: RequirementSet): MarksSummary {
  const sum = rs.evaluation_criteria.reduce((acc, e) => acc + e.max_marks, 0);
  return { sum, total: rs.total_marks, consistent: rs.total_marks === null || Math.abs(sum - rs.total_marks) < 1e-6 };
}

export interface Segment {
  text: string;
  mark: boolean;
}

/** Split `text` so the quoted part (or else the given span) can be highlighted; case- and space-insensitive. */
export function highlight(text: string, quote: string | null, span?: [number, number] | null): Segment[] {
  let start = -1;
  let end = -1;
  const words = (quote ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length) {
    const pattern = new RegExp(words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+"), "i");
    const m = pattern.exec(text);
    if (m) [start, end] = [m.index, m.index + m[0].length];
  }
  if (start < 0 && span) [start, end] = span;
  if (start < 0 || end <= start) return [{ text, mark: false }];
  return [
    { text: text.slice(0, start), mark: false },
    { text: text.slice(start, end), mark: true },
    { text: text.slice(end), mark: false },
  ].filter((s) => s.text.length > 0);
}

export function findSource(model: DocumentModel | undefined, ref: SourceRef | null): {
  doc: SourceDocument | null;
  block: Block | null;
} {
  if (!model || !ref) return { doc: null, block: null };
  const doc = model.documents.find((d) => d.doc_id === ref.doc_id) ?? null;
  if (!doc) return { doc: null, block: null };
  const id = ref.block_ids[0];
  let block = id ? (doc.blocks.find((b) => b.id === id) ?? null) : null;
  if (!block && ref.char_span) {
    const [s] = ref.char_span;
    block = doc.blocks.find((b) => b.char_start <= s && s < b.char_end) ?? null;
  }
  return { doc, block };
}

/** The next free id with ``prefix`` (R, C, D, E). */
export function nextId(ids: readonly string[], prefix: string): string {
  const nums = ids.map((i) => Number(i.slice(prefix.length))).filter((n) => Number.isFinite(n));
  return `${prefix}${(nums.length ? Math.max(...nums) : 0) + 1}`;
}

export function updateRequirement(rs: RequirementSet, id: string, patch: Partial<Requirement>): RequirementSet {
  return { ...rs, requirements: rs.requirements.map((r) => (r.id === id ? { ...r, ...patch } : r)) };
}

export function confirmRequirement(rs: RequirementSet, id: string): RequirementSet {
  return updateRequirement(rs, id, { confidence: CONFIRMED });
}

export function confirmAll(rs: RequirementSet): RequirementSet {
  return { ...rs, requirements: rs.requirements.map((r) => ({ ...r, confidence: CONFIRMED })) };
}

export function unconfirmedCount(rs: RequirementSet): number {
  return rs.requirements.filter((r) => r.confidence < CONFIRMED).length;
}

export function removeRequirement(rs: RequirementSet, id: string): RequirementSet {
  return { ...rs, requirements: rs.requirements.filter((r) => r.id !== id) };
}

/** A requirement added by a person: no source in the documents, so it carries the first document and full trust. */
export function addRequirement(rs: RequirementSet, text: string, priority: Priority = "must"): RequirementSet {
  const docId = rs.source_docs[0]?.artifact_id ?? "manual";
  const req: Requirement = {
    id: nextId(rs.requirements.map((r) => r.id), "R"),
    text: text.trim(),
    type: "functional",
    priority,
    confidence: 1,
    source_ref: { doc_id: docId, page: null, block_ids: [], char_span: null, quote: null, folder: null },
  };
  return { ...rs, requirements: [...rs.requirements, req] };
}

export function sameSet(a: RequirementSet | null | undefined, b: RequirementSet | null | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

export function editedBy(createdBy: string): string {
  return createdBy.startsWith("user:") ? "edited by you" : "extracted automatically";
}
