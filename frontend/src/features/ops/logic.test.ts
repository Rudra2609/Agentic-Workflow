import { describe, expect, it } from "vitest";

import { errorLine, executionLine, reasonProblem, sumValues, taskFromSearch, verdictTone } from "./logic";

describe("ops logic", () => {
  it("maps verdicts to tones and errors to one line", () => {
    expect(verdictTone("dead_lettered")).toBe("danger");
    expect(verdictTone("completed")).toBe("success");
    expect(verdictTone("whatever")).toBe("neutral");
    expect(errorLine({ code: "TOOL_TRANSIENT", message: "tool timed out" })).toBe("TOOL_TRANSIENT: tool timed out");
    expect(errorLine(null)).toBe("—");
  });

  it("reads a safe task id from the URL", () => {
    expect(taskFromSearch("?task=T-01ABC")).toBe("T-01ABC");
    expect(taskFromSearch("?task=../../etc")).toBeNull();
    expect(taskFromSearch("")).toBeNull();
  });

  it("requires a real replay reason", () => {
    expect(reasonProblem(" ")).toMatch(/why it is safe/);
    expect(reasonProblem("x".repeat(501))).toMatch(/500/);
    expect(reasonProblem("the API is back")).toBeNull();
  });

  it("summarises an attempt", () => {
    expect(executionLine({ execution_id: "E", attempt: 2, status: "TIMED_OUT", agent_id: "agent-x", created_at: "", updated_at: "", error: { code: "AGENT_UNAVAILABLE" }, superseded_by: null, orphaned_at: null, outcome: null, late_reports: [] })).toBe(
      "Attempt 2 · timed out · agent-x · AGENT_UNAVAILABLE",
    );
    expect(sumValues({ a: 1, b: 2 })).toBe(3);
  });
});
