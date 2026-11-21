/** Pure helpers for the Testing tab (unit-tested in logic.test.ts): stage order and words, failure grouping, event key. */
import type { Tone } from "@/lib/plain";

import type { Category, Failure, StageStatus, TestingTrace } from "./types";

export const STAGE_ORDER = [
  "static",
  "build",
  "unit",
  "integration",
  "security",
  "execution",
] as const;

export const STAGE_TEXT: Record<string, { label: string; help: string }> = {
  static: {
    label: "Static checks",
    help: "ruff (and mypy when the code configures it): the code is read, not run",
  },
  build: {
    label: "Build",
    help: "every file compiles and every module imports",
  },
  unit: {
    label: "Unit tests",
    help: "the project's tests (pytest), with coverage in the Docker sandbox",
  },
  integration: {
    label: "Integration",
    help: "tests that start several processes, e.g. a server and its clients",
  },
  security: {
    label: "Security",
    help: "bandit and built-in rules: eval, shell commands, hard-coded secrets…",
  },
  execution: {
    label: "Run",
    help: "the program's entry point with a sample input (only when the task names one)",
  },
};

export const STATUS_TONE: Record<StageStatus, Tone> = {
  passed: "success",
  failed: "danger",
  skipped: "neutral",
  error: "warning",
};

export const CATEGORY_TEXT: Record<Category, string> = {
  SYNTAX: "Syntax error",
  IMPORT: "Import error",
  ASSERTION: "Wrong result",
  TIMEOUT: "Too slow / hangs",
  CRASH: "Crash",
  SECURITY: "Security",
  LINT: "Style / lint",
  ENV: "Test environment",
};

export const BACKEND_TEXT: Record<string, string> = {
  docker: "Docker sandbox (no network, read-only, non-root, limits)",
  local: "local jailed runner (Docker not running: weaker isolation)",
  none: "not run",
};

/** Failures that count (not lint, not flaky) first, then the rest; each group in report order. */
export function sortFailures(failures: readonly Failure[]): Failure[] {
  const counts = (f: Failure) => f.category !== "LINT" && !f.flaky;
  return [...failures.filter(counts), ...failures.filter((f) => !counts(f))];
}

export function where(f: Failure): string {
  if (f.file && f.line) return `${f.file}:${f.line}`;
  return f.file ?? f.test ?? f.stage;
}

export function stagesInOrder(
  trace: Pick<TestingTrace, "stages">,
): TestingTrace["stages"] {
  return STAGE_ORDER.map(
    (n) =>
      trace.stages.find((s) => s.name === n) ?? {
        name: n,
        status: "skipped" as const,
        duration_s: 0,
        detail: "",
        tests: 0,
        tests_failed: 0,
      },
  );
}

export function roundTitle(round: number): string {
  return round === 0 ? "Test run" : `Re-test after fix ${round}`;
}

export function percent(x: number | null | undefined): string {
  return x === null || x === undefined ? "–" : `${Math.round(x * 100)}%`;
}

/** Changes when a testing task moves (refetch key): test.completed events and task events that mention test.run. */
export function testingEventKey(
  events: readonly {
    event_type: string;
    seq: number;
    data?: Record<string, unknown>;
  }[],
): string {
  const mine = events.filter(
    (e) =>
      e.event_type === "test.completed" ||
      (e.event_type.startsWith("task.") &&
        JSON.stringify(e.data ?? {}).includes("test.run")),
  );
  return `${mine.length}:${mine.at(-1)?.seq ?? 0}`;
}
