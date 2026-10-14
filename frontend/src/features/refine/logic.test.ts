import { describe, expect, it } from "vitest";

import {
  bestIndex,
  categoryText,
  curvePath,
  curvePoints,
  describeChange,
  groupIssues,
  iterationLabel,
  outcomeText,
  percent,
  refineEventKey,
  stopText,
  strategyText,
  subjectLabel,
} from "./logic";
import type { Issue } from "./types";

const issue = (category: Issue["category"], severity: Issue["severity"], description = "x"): Issue => ({ category, severity, description });

describe("refine logic", () => {
  it("groups issues by category, worst first, issues by severity", () => {
    const groups = groupIssues([issue("STYLE", "minor"), issue("OMISSION", "minor"), issue("OMISSION", "critical", "R9 missing"), issue("LOGIC", "major")]);
    expect(groups.map((g) => g.category)).toEqual(["OMISSION", "LOGIC", "STYLE"]);
    expect(groups[0]!.issues.map((i) => i.severity)).toEqual(["critical", "minor"]);
    expect(groups[0]!.label).toBe("Missing");
    expect(categoryText("WEIRD_THING").label).toBe("weird thing");
  });

  it("formats scores, stop reasons, strategies and labels in plain words", () => {
    expect(percent(0.856)).toBe("86%");
    expect(percent(null)).toBe("—");
    expect(stopText("plateau")).toMatch(/stopped improving/i);
    expect(stopText(null)).toMatch(/checking/i);
    expect(strategyText("full")).toMatch(/changed approach/i);
    expect(strategyText(null)).toBeNull();
    expect(iterationLabel(0)).toBe("Original");
    expect(iterationLabel(2)).toBe("Revision 2");
    expect(subjectLabel({ capability: "plan.generate", subject: "plan" })).toBe("Plan");
    expect(subjectLabel({ capability: "refine.run", subject: "research-report" })).toBe("Research report");
  });

  it("says what happened to a run", () => {
    expect(outcomeText({ status: "stopped", applied: true, base_score: 0.6, best_score: 0.95, iterations: 2 })).toMatch(/Improved from 60% to 95% in 2 rounds/);
    expect(outcomeText({ status: "stopped", applied: false, base_score: 1, best_score: 1, iterations: 0 })).toMatch(/Nothing needed fixing/);
    expect(outcomeText({ status: "stopped", applied: false, base_score: 0.7, best_score: 0.7, iterations: 2 })).toMatch(/original is kept/);
    expect(outcomeText({ status: "running", applied: false, base_score: null, best_score: null, iterations: 0 })).toBe("Checking…");
  });

  it("draws the score curve inside its box, top = 100%", () => {
    const pts = curvePoints([0, 0.5, 1], 100, 50, 5);
    expect(pts.map((p) => [p.x, p.y])).toEqual([[5, 45], [50, 25], [95, 5]]);
    expect(curvePath(pts)).toBe("M5.0,45.0 L50.0,25.0 L95.0,5.0");
    expect(curvePoints([2], 100, 50, 5)[0]).toMatchObject({ x: 50, y: 5 });   // clamped, centred
    expect(curvePoints([], 10, 10)).toEqual([]);
    expect(bestIndex([0.5, 0.9, 0.9])).toBe(1);
    expect(bestIndex([])).toBeNull();
  });

  it("describes revisions as sentences", () => {
    expect(describeChange({ path: "requirements/R7", op: "added", before: null, after: { id: "R7", text: "Dark mode" } })).toEqual({
      kind: "added", text: "Added requirement R7", detail: "Dark mode",
    });
    expect(describeChange({ path: "tasks/T5/depends_on", op: "changed", before: ["design"], after: ["design", "T3"], added_items: ["T3"], removed_items: [] }).text).toBe(
      "Step T5: waits for — now waits for T3",
    );
    expect(describeChange({ path: "requirements/R2/priority", op: "changed", before: "must", after: "should" })).toMatchObject({
      text: "Requirement R2: priority changed", detail: "must → should",
    });
    expect(describeChange({ path: "summary", op: "changed", before: "", after: "Done." }).text).toBe("Changed summary");
  });

  it("changes its event key only when refinement events arrive", () => {
    const base = [{ event_type: "task.progress", seq: 1 }];
    expect(refineEventKey(base)).toBe("0:0");
    expect(refineEventKey([...base, { event_type: "refine.iteration", seq: 7 }])).toBe("1:7");
  });
});
