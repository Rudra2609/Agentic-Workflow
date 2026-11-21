// @vitest-environment happy-dom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/types";

import type { RunDetail, RunSummary } from "./types";

const listRuns = vi.fn();
const getRun = vi.fn();
const rerun = vi.fn();
const getQuarantine = vi.fn();
const releaseTest = vi.fn();

vi.mock("./client", () => ({
  listRuns: (...a: unknown[]) => listRuns(...a),
  getRun: (...a: unknown[]) => getRun(...a),
  rerun: (...a: unknown[]) => rerun(...a),
  getQuarantine: (...a: unknown[]) => getQuarantine(...a),
  releaseTest: (...a: unknown[]) => releaseTest(...a),
  logUrl: (p: string, t: string) => `/api/testing/runs/${p}/${t}/log`,
}));

import { TestingPanel } from "./TestingPanel";

const project = {
  project_id: "P-1",
  name: "x",
  state: "EXECUTING",
} as unknown as Project;

const first: RunSummary = {
  task_id: "T-1",
  status: "done",
  passed: false,
  backend: "docker",
  objective: "Test the median fix",
  stages: { static: "passed", unit: "failed" },
  tests: 2,
  tests_failed: 1,
  failures: 1,
  lint: 1,
  flaky: 0,
  coverage: 92.5,
  pass_ratio: 0.5,
  loop_round: 0,
  coding_task_id: "T-C",
  generated: 0,
  seconds: 3.2,
  updated_at: "2026-10-30T10:00:00Z",
};
const second: RunSummary = {
  ...first,
  task_id: "T-2",
  passed: true,
  tests_failed: 0,
  failures: 0,
  lint: 0,
  pass_ratio: 1,
  loop_round: 1,
};

const detail: RunDetail = {
  summary: first,
  report: { passed: false },
  generated_tests: null,
  loop: [first, second],
  trace: {
    task_id: "T-1",
    status: "done",
    backend: "docker",
    isolation: "Docker",
    workspace_from: "the coding step's workspace",
    coding_task_id: "T-C",
    objective: "Test the median fix",
    acceptance_criteria: ["median([1, 2, 3, 4]) == 2.5"],
    files: 4,
    stages: [
      {
        name: "static",
        status: "failed",
        duration_s: 0.2,
        detail: "",
        tests: 0,
        tests_failed: 0,
      },
      {
        name: "unit",
        status: "failed",
        duration_s: 1.1,
        detail: "",
        tests: 2,
        tests_failed: 1,
      },
    ],
    steps: [
      {
        stage: "unit",
        name: "unit",
        cmd: "pytest -q",
        exit_code: 1,
        timed_out: false,
        duration_s: 1.1,
        output: "1 failed, 1 passed",
      },
    ],
    failures: [
      {
        stage: "static",
        category: "LINT",
        file: "stats.py",
        line: 1,
        test: null,
        message: "F401 os unused",
        hint: "remove the unused import",
        hint_by: "rule",
        generated: false,
        flaky: false,
      },
      {
        stage: "unit",
        category: "ASSERTION",
        file: "test_stats.py",
        line: 7,
        test: "test_stats.py::test_even",
        message: "assert 3 == 2.5",
        hint: "average the two middle values",
        hint_by: "model",
        generated: false,
        flaky: false,
      },
    ],
    flaky: [],
    generated: {},
    coverage: 92.5,
    mutation: {
      total: 10,
      killed: 8,
      score: 0.8,
      survived: [{ file: "stats.py", line: 4, op: "< -> <=" }],
      error: null,
    },
    fuzz: { targets: 2, functions: ["stats.median"], findings: 1 },
    dependencies: {
      audited: ["PyPI:requests==2.19.0"],
      unpinned: [],
      vulnerable: [{ dependency: "PyPI:requests==2.19.0", id: "GHSA-1" }],
      source: "cache",
      note: "",
    },
    passed: false,
    pass_ratio: 0.5,
    loop: { round: 0, origin_task_id: null, history: [] },
    model_calls: 1,
    notes: [],
  },
};

describe("TestingPanel", () => {
  beforeEach(() => {
    listRuns.mockResolvedValue([first, second]);
    getRun.mockResolvedValue(detail);
    rerun.mockResolvedValue({ task_id: "T-3" });
    getQuarantine.mockResolvedValue({
      project_id: "P-1",
      tests: {
        "t.py::test_race": {
          flaky: 2,
          clean_passes: 1,
          first_seen: "",
          last_seen: "",
          last_task_id: null,
        },
      },
      released: [],
      release_after: 3,
    });
    releaseTest.mockResolvedValue({
      project_id: "P-1",
      tests: {},
      released: ["t.py::test_race"],
      release_after: 3,
    });
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the runs, the stage timeline, failures with hints and the loop", async () => {
    render(
      <TestingPanel
        projectId="P-1"
        project={project}
        tasks={[]}
        events={[]}
        reload={() => {}}
      />,
    );
    const cards = await screen.findByRole("list", { name: "Test runs" });
    expect(cards.textContent).toContain("1/2 tests passed");
    expect(cards.textContent).toContain("Re-test after fix 1");
    const stages = await screen.findByRole("list", { name: "Stages" });
    expect(stages.textContent).toContain("Unit tests");
    expect(stages.textContent).toContain("1/2 tests");
    const failures = screen.getByRole("list", { name: "Failure list" });
    expect(failures.firstElementChild?.textContent).toContain("Wrong result"); // counted failure before lint
    expect(failures.textContent).toContain(
      "Hint (AI): average the two middle values",
    );
    expect(
      screen.getByRole("list", { name: "Loop rounds" }).children.length,
    ).toBe(2);
    expect(
      screen.getByRole("link", { name: "Full log" }).getAttribute("href"),
    ).toBe("/api/testing/runs/P-1/T-1/log");
    const extras = screen.getByRole("list", { name: "Extra checks" });
    expect(extras.textContent).toContain("8/10 planted faults caught (80%)");
    expect(extras.textContent).toContain("stats.py:4 (< -> <=)");
    expect(extras.textContent).toContain("2 function(s), 1 finding(s)");
    expect(extras.textContent).toContain("1 known vulnerability");
  });

  it("re-runs the tests", async () => {
    const reload = vi.fn();
    render(
      <TestingPanel
        projectId="P-1"
        project={project}
        tasks={[]}
        events={[]}
        reload={reload}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Re-run the tests" }),
    );
    await waitFor(() => expect(rerun).toHaveBeenCalledWith("P-1", "T-1"));
    expect(await screen.findByText(/Re-run started/)).toBeTruthy();
    expect(reload).toHaveBeenCalled();
  });

  it("lists quarantined flaky tests and releases one", async () => {
    render(
      <TestingPanel
        projectId="P-1"
        project={project}
        tasks={[]}
        events={[]}
        reload={() => {}}
      />,
    );
    const list = await screen.findByRole("list", { name: "Quarantined tests" });
    expect(list.textContent).toContain("t.py::test_race");
    expect(list.textContent).toContain("flaky 2×");
    fireEvent.click(screen.getByRole("button", { name: "Release" }));
    await waitFor(() =>
      expect(releaseTest).toHaveBeenCalledWith("P-1", "t.py::test_race"),
    );
  });
});
