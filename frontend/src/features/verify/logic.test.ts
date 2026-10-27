import { describe, expect, it } from "vitest";

import { excerpt, isFlagged, layerSteps, sortClaims, verifyEventKey } from "./logic";
import type { AtomCheck, ClaimCheck } from "./types";

const atom = (over: Partial<AtomCheck> = {}): AtomCheck => ({
  atom_id: "C1", text: "x", check_worthy: true, l1: [{ evidence_id: "E1", ok: true, reason: "ok", detail: "" }], l2: null,
  l3_queries: [], l3_passages: 0, l4: [], independent_hosts: [], row: "R8", verdict: "VERIFIED", confidence: 0.8, explanation: "",
  ...over,
});

const claim = (id: string, verdict: ClaimCheck["verdict"]): ClaimCheck => ({
  claim_id: id, text: id, evidence_ids: [], atoms: [], verdict, confidence: 0.5, explanation: "", supporting: [], contradicting: [],
});

describe("verify logic", () => {
  it("sorts flagged claims first, worst first", () => {
    const out = sortClaims([claim("C2", "VERIFIED"), claim("C10", "UNSUPPORTED"), claim("C1", "CONFLICTING"), claim("C3", "UNSUPPORTED")]);
    expect(out.map((c) => c.claim_id)).toEqual(["C3", "C10", "C1", "C2"]);
    expect(isFlagged("NEEDS_MORE_RESEARCH")).toBe(true);
    expect(isFlagged("VERIFIED")).toBe(false);
  });

  it("explains a failed L1 and skips the model", () => {
    const steps = layerSteps(atom({ l1: [{ evidence_id: "E2", ok: false, reason: "quote_not_found", detail: "" }] }));
    expect(steps[0]).toMatchObject({ layer: "L1", state: "fail" });
    expect(steps[0]!.text).toContain("E2: the quote is not in the saved page");
    expect(steps[1]).toMatchObject({ layer: "L2", state: "skip" });
  });

  it("marks an unsure judge and a conflict", () => {
    const steps = layerSteps(atom({
      l2: { label: "supports", rationale: "", by: "model", swapped_label: "not_enough", guard: "" },
      l3_queries: ["jwt stateless"], l3_passages: 2,
      l4: [{ passage: { url: "https://a.test/x", host: "a.test", title: "", text: "t", overlap: 0.8, origin: "independent", query: "", published: null }, signals: ["negation"], judgement: { label: "refutes", rationale: "", by: "model", swapped_label: null, guard: "" } }],
    }));
    expect(steps.map((s) => s.state)).toEqual(["pass", "warn", "pass", "fail"]);
    expect(steps[3]!.text).toContain("a.test");
  });

  it("builds a refetch key from verify events only", () => {
    const k = verifyEventKey([
      { event_type: "research.completed", seq: 1, data: {} },
      { event_type: "task.completed", seq: 2, data: { capability: "verify.claims" } },
      { event_type: "verification.completed", seq: 3, data: {} },
    ]);
    expect(k).toBe("2:3");
  });

  it("cuts an excerpt around the quote", () => {
    const ex = excerpt("aaaa QUOTE bbbb", 5, 10, 2);
    expect(ex).toEqual({ before: "a ", mark: "QUOTE", after: " b", cutStart: true, cutEnd: true });
  });
});
