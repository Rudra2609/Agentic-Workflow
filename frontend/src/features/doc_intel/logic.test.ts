import { describe, expect, it } from "vitest";

import {
  addRequirement,
  confidenceLevel,
  confirmAll,
  confirmRequirement,
  editedBy,
  findSource,
  groupByFolder,
  highlight,
  marksSummary,
  nextId,
  removeRequirement,
  sameSet,
  unconfirmedCount,
  updateRequirement,
} from "./logic";
import type { DocumentModel, Requirement, RequirementSet, SourceRef } from "./types";

const ref = (folder: string | null, extra: Partial<SourceRef> = {}): SourceRef => ({
  doc_id: "A-1", page: 1, block_ids: ["b2"], char_span: [10, 30], quote: "must accept 10 clients", folder, ...extra,
});

const req = (id: string, folder: string | null = null, confidence = 0.9): Requirement => ({
  id, text: `${id} text`, type: "functional", priority: "must", confidence, source_ref: ref(folder),
});

const set = (over: Partial<RequirementSet> = {}): RequirementSet => ({
  project_id: "P-1", source_docs: [{ artifact_id: "A-1", media_type: "application/pdf" }],
  requirements: [req("R1"), req("R2")], constraints: [], deliverables: [], open_questions: [], total_marks: 10,
  evaluation_criteria: [
    { id: "E1", criterion: "a", max_marks: 6, rubric_levels: [], source_ref: null },
    { id: "E2", criterion: "b", max_marks: 4, rubric_levels: [], source_ref: null },
  ],
  ...over,
});

describe("doc_intel panel logic", () => {
  it("labels confidence in words with a tone", () => {
    expect(confidenceLevel(0.95)).toEqual({ label: "High confidence", tone: "success" });
    expect(confidenceLevel(0.7).tone).toBe("warning");
    expect(confidenceLevel(0.4).label).toBe("Low confidence");
  });

  it("confirms one or all requirements (confidence 1.0 = checked by a person)", () => {
    const rs = set({ requirements: [req("R1", null, 0.9), req("R2", null, 0.4)] });
    expect(unconfirmedCount(rs)).toBe(2);
    expect(confirmRequirement(rs, "R2").requirements.map((r) => r.confidence)).toEqual([0.9, 1]);
    expect(unconfirmedCount(confirmAll(rs))).toBe(0);
    expect(confidenceLevel(1)).toEqual({ label: "Checked by a person", tone: "success" });
  });

  it("groups requirements by upload folder in order", () => {
    const groups = groupByFolder([req("R1", "Part A"), req("R2", "Part B"), req("R3", "Part A")]);
    expect(groups.map((g) => [g.folder, g.items.map((r) => r.id)])).toEqual([
      ["Part A", ["R1", "R3"]],
      ["Part B", ["R2"]],
    ]);
    expect(groupByFolder([req("R1")])[0]?.folder).toBeNull();
  });

  it("sums marks and checks them against the stated total", () => {
    expect(marksSummary(set())).toEqual({ sum: 10, total: 10, consistent: true });
    expect(marksSummary(set({ total_marks: 12 })).consistent).toBe(false);
    expect(marksSummary(set({ total_marks: null })).consistent).toBe(true);
  });

  it("highlights a quote ignoring case and spacing, else a span", () => {
    expect(highlight("The server MUST accept\n10 clients now.", "must accept 10 clients")).toEqual([
      { text: "The server ", mark: false },
      { text: "MUST accept\n10 clients", mark: true },
      { text: " now.", mark: false },
    ]);
    expect(highlight("abcdef", null, [2, 4])).toEqual([
      { text: "ab", mark: false }, { text: "cd", mark: true }, { text: "ef", mark: false }]);
    expect(highlight("plain", "absent (regex] chars")).toEqual([{ text: "plain", mark: false }]);
  });

  it("finds the source block by id or by character span", () => {
    const model: DocumentModel = {
      project_id: "P-1",
      documents: [{ doc_id: "A-1", name: "a.pdf", folder: null, kind: "pdf", pages: [], text: "", warnings: [],
        blocks: [{ id: "b2", type: "list_item", text: "x", page: 1, bbox: null, level: null, section_path: [],
          char_start: 5, char_end: 40, ocr: false }] }],
    };
    expect(findSource(model, ref(null)).block?.id).toBe("b2");
    expect(findSource(model, ref(null, { block_ids: [], char_span: [6, 7] })).block?.id).toBe("b2");
    expect(findSource(model, ref(null, { doc_id: "other" }))).toEqual({ doc: null, block: null });
    expect(findSource(undefined, ref(null)).doc).toBeNull();
  });

  it("edits, removes and adds requirements without touching the original", () => {
    const original = set();
    const edited = updateRequirement(original, "R1", { text: "new", priority: "should" });
    expect(edited.requirements[0]).toMatchObject({ id: "R1", text: "new", priority: "should" });
    expect(original.requirements[0]?.text).toBe("R1 text");
    expect(removeRequirement(original, "R1").requirements.map((r) => r.id)).toEqual(["R2"]);
    const added = addRequirement(removeRequirement(original, "R1"), "  Support dark mode ");
    expect(added.requirements.at(-1)).toMatchObject({ id: "R3", text: "Support dark mode", confidence: 1 });
    expect(added.requirements.at(-1)?.source_ref).toMatchObject({ doc_id: "A-1", quote: null });
    expect(nextId([], "C")).toBe("C1");
    expect(sameSet(original, set())).toBe(true);
    expect(sameSet(original, edited)).toBe(false);
    expect(editedBy("user:U-1")).toBe("edited by you");
    expect(editedBy("doc-intel-x")).toBe("extracted automatically");
  });
});
