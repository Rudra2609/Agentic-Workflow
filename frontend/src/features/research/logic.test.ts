import { describe, expect, it } from "vitest";

import { bySource, claimsBySub, excerpt, groupByQuestion, host, parseQuestions, percent, researchEventKey, safeHref, sourceNumbers, stopText } from "./logic";
import type { Report } from "./types";

const report = {
  questions: ["Threads or asyncio?", "How to measure latency?"],
  sub_questions: [
    { id: "S1.1", question: 0, text: "event loop", queries: [], success_criteria: "", coverage: 1, status: "covered" },
    { id: "S2.1", question: 1, text: "timers", queries: [], success_criteria: "", coverage: 0, status: "open" },
  ],
  claims: [{ id: "C1", text: "One loop serves many sockets.", evidence_ids: ["E2", "E1"] }],
  evidence: [
    { id: "E1", url: "https://docs.python.org/a", quote: "q1", content_sha256: "x", retrieved_at: "", sub_question: "S1.1", page_artifact: null },
    { id: "E2", url: "https://en.wikipedia.org/b", quote: "q2", content_sha256: "y", retrieved_at: "", sub_question: "S1.1", page_artifact: null },
    { id: "E3", url: "https://docs.python.org/a", quote: "q3", content_sha256: "x", retrieved_at: "", sub_question: "S2.1", page_artifact: null },
  ],
} as unknown as Report;

describe("research logic", () => {
  it("groups evidence by source for one chip each", () => {
    expect(bySource(report.evidence).map((g) => g.map((e) => e.id))).toEqual([["E1", "E3"], ["E2"]]);
  });

  it("groups sub-questions and claims", () => {
    const g = groupByQuestion(report);
    expect(g.map((x) => x.subs.map((s) => s.id))).toEqual([["S1.1"], ["S2.1"]]);
    expect(claimsBySub(report).get("S1.1")?.map((c) => c.id)).toEqual(["C1"]);
  });

  it("numbers sources in order of first citation, then the rest", () => {
    expect([...sourceNumbers(report).entries()]).toEqual([["https://en.wikipedia.org/b", 1], ["https://docs.python.org/a", 2]]);
  });

  it("speaks plainly and links only to the web", () => {
    expect(stopText("all_covered")).toMatch(/answered by sources/);
    expect(stopText("something_new")).toBe("something new");
    expect(stopText(null)).toBe("Researching…");
    expect(percent(0.756)).toBe("76%");
    expect(host("https://www.example.org/x")).toBe("example.org");
    expect(host("project://D1")).toBe("your documents");
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref("https://a.org")).toBe("https://a.org");
  });

  it("cuts an excerpt around the quote at word boundaries", () => {
    const text = "word ".repeat(200) + "THE QUOTE" + " tail".repeat(200);
    const start = text.indexOf("THE QUOTE");
    const ex = excerpt(text, start, start + 9, 50);
    expect(ex.mark).toBe("THE QUOTE");
    expect(ex.cutStart && ex.cutEnd).toBe(true);
    expect(ex.before.length).toBeLessThanOrEqual(50);
  });

  it("refetches on research events only and reads questions line by line", () => {
    const k1 = researchEventKey([{ event_type: "task.progress", seq: 1, data: { artifact_refs: [{ artifact_type: "refinement-progress" }] } }]);
    const k2 = researchEventKey([{ event_type: "task.progress", seq: 2, data: { artifact_refs: [{ artifact_type: "research-trace" }] } }]);
    expect(k1).toBe("0:0");
    expect(k2).toBe("1:2");
    expect(parseQuestions("  What is TCP?\n\nok\nWhy asyncio?\n")).toEqual(["What is TCP?", "Why asyncio?"]);
  });
});
