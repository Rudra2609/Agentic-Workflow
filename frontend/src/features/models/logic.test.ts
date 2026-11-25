import { describe, expect, it } from "vitest";

import { barWidth, gb, isCloud, outcome, pct, quickResults } from "./logic";
import type { RouteRecord } from "./types";

const rec = (over: Partial<RouteRecord>): RouteRecord => ({
  id: "rd-1", at: "2026-11-01T10:00:00+00:00", decision: { role: "coder", model: "m", backend: "groq", reason: "" },
  plugin: "coding", est_tokens: 100, chain: [], rule: "rules", answered_by: null, ok: null, latency_s: null,
  attempts: 0, rate_limited: 0, error: "", ...over,
});

describe("models logic", () => {
  it("formats sizes, percentages and bars", () => {
    expect(gb(5.77)).toBe("5.8 GB");
    expect(gb(null)).toBe("–");
    expect(pct(0.833)).toBe("83%");
    expect(barWidth(0)).toBe("1%");
    expect(barWidth(0.5)).toBe("50%");
  });

  it("says who answered, and flags a local fallback", () => {
    expect(outcome(rec({})).label).toBe("running");
    expect(outcome(rec({ ok: true, answered_by: "groq:x" }))).toEqual({ label: "answered by groq:x", tone: "success" });
    expect(outcome(rec({ ok: true, answered_by: "ollama:qwen3.5:9b" })).tone).toBe("warning");
    expect(outcome(rec({ ok: false, error: "MODEL_TRANSIENT" })).label).toBe("failed (MODEL_TRANSIENT)");
  });

  it("sorts complete benchmark runs first, best first", () => {
    const files = {
      quick_a: { model: "a", mode: "replay", quality: 0.8, coverage: 1, suites: {} },
      quick_b: { model: "groq:b", mode: "record", quality: 0.9, coverage: 0.4, suites: {} },
      quick_c: { model: "c", mode: "replay", quality: 0.83, coverage: 1, suites: {} },
      speed: { x: 1 },
    };
    expect(quickResults(files).map((r) => r.model)).toEqual(["c", "a", "groq:b"]);
    expect(isCloud("groq:b")).toBe(true);
    expect(isCloud("qwen3.5:9b")).toBe(false);
  });
});
