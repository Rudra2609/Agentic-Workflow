import { describe, expect, it } from "vitest";

import { counts, percent, reviewEventKey, sortItems, taskLabel } from "./logic";
import type { Decided } from "./types";

function d(id: string, kind: Decided["item"]["kind"], verdict: Decided["verdict"], priority = "must"): Decided {
  return {
    item: {
      id,
      kind,
      text: id,
      priority,
      covering: [],
      max_marks: null,
      evidence: {
        tests: [],
        verification: [],
        deliverables: [],
        doc_ungrounded: [],
        doc_status: null,
        violations: [],
        facts: [],
        producer_note: "",
        stub: false,
      },
    },
    check: { verdict, reasons: [], category: null, no_action: false },
    verdict,
    source: "objective",
    rationale: "",
    votes: [],
    order_sensitive: false,
    level: null,
    score: null,
  };
}

describe("review logic", () => {
  it("sorts requirements (must first, numeric ids), then constraints, deliverables; drops criteria", () => {
    const out = sortItems([
      d("D1", "deliverable", "PASS"),
      d("R10", "requirement", "PASS"),
      d("R2", "requirement", "FAIL", "should"),
      d("R3", "requirement", "PASS"),
      d("C1", "constraint", "PARTIAL"),
      d("E1", "criterion", "PARTIAL"),
    ]).map((x) => x.item.id);
    expect(out).toEqual(["R3", "R10", "R2", "C1", "D1"]);
  });

  it("counts verdicts without criteria and formats percentages", () => {
    expect(counts([d("R1", "requirement", "PASS"), d("R2", "requirement", "FAIL"), d("E1", "criterion", "FAIL")]))
      .toEqual({ PASS: 1, PARTIAL: 0, FAIL: 1 });
    expect(percent(0.756)).toBe("76 %");
    expect(percent(null)).toBe("–");
  });

  it("keys on review events only", () => {
    const a = reviewEventKey([{ event_type: "task.state_changed", seq: 1, data: { capability: "code.implement" } }]);
    const b = reviewEventKey([
      { event_type: "task.state_changed", seq: 1, data: { capability: "code.implement" } },
      { event_type: "review.completed", seq: 2 },
    ]);
    expect(a).toBe("0:0");
    expect(b).toBe("1:2");
  });

  it("labels a responsible step", () => {
    const tasks = [{ task_id: "T-1", title: "Write the server", capability: "code.implement" }];
    expect(taskLabel("T-1", tasks)).toBe("Write the server");
    expect(taskLabel(null, tasks)).toBe("no step covers it");
    expect(taskLabel("T-9", tasks)).toBe("T-9");
  });
});
