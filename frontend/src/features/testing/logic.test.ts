import { describe, expect, it } from "vitest";

import {
  percent,
  roundTitle,
  sortFailures,
  stagesInOrder,
  testingEventKey,
  where,
} from "./logic";
import type { Failure } from "./types";

const f = (over: Partial<Failure>): Failure => ({
  stage: "unit",
  category: "ASSERTION",
  file: null,
  line: null,
  test: null,
  message: "m",
  hint: null,
  hint_by: "rule",
  generated: false,
  flaky: false,
  ...over,
});

describe("testing logic", () => {
  it("puts counted failures before lint and flaky ones", () => {
    const out = sortFailures([
      f({ category: "LINT", message: "a" }),
      f({ flaky: true, message: "b" }),
      f({ message: "c" }),
    ]);
    expect(out.map((x) => x.message)).toEqual(["c", "a", "b"]);
  });

  it("names where a failure is", () => {
    expect(where(f({ file: "m.py", line: 3 }))).toBe("m.py:3");
    expect(where(f({ test: "t.py::test_x" }))).toBe("t.py::test_x");
    expect(where(f({}))).toBe("unit");
  });

  it("lists every stage in pipeline order, missing ones as skipped", () => {
    const out = stagesInOrder({
      stages: [
        {
          name: "unit",
          status: "failed",
          duration_s: 1,
          detail: "",
          tests: 3,
          tests_failed: 1,
        },
      ],
    });
    expect(out.map((s) => `${s.name}:${s.status}`)).toEqual([
      "static:skipped",
      "build:skipped",
      "unit:failed",
      "integration:skipped",
      "security:skipped",
      "execution:skipped",
    ]);
  });

  it("words and numbers", () => {
    expect(roundTitle(0)).toBe("Test run");
    expect(roundTitle(2)).toBe("Re-test after fix 2");
    expect(percent(0.756)).toBe("76%");
    expect(percent(null)).toBe("–");
  });

  it("refetch key follows test events only", () => {
    const ev = [
      {
        event_type: "task.completed",
        seq: 1,
        data: { capability: "code.implement" },
      },
      { event_type: "test.completed", seq: 4, data: {} },
      { event_type: "task.started", seq: 5, data: { capability: "test.run" } },
    ];
    expect(testingEventKey(ev)).toBe("2:5");
  });
});
