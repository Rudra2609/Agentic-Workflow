// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/types";

import type { RunDetail, RunSummary } from "./types";

const listRuns = vi.fn();
const getRun = vi.fn();
const requestChanges = vi.fn();

vi.mock("./client", () => ({
  listRuns: (...a: unknown[]) => listRuns(...a),
  getRun: (...a: unknown[]) => getRun(...a),
  requestChanges: (...a: unknown[]) => requestChanges(...a),
  workspaceZipUrl: (p: string, t: string) => `/api/coding/runs/${p}/${t}/workspace.zip`,
}));

import { CodingPanel } from "./CodingPanel";

const project = { project_id: "P-1", name: "x", state: "EXECUTING" } as unknown as Project;

const summary: RunSummary = {
  task_id: "T-C", capability: "code.implement", status: "done", outcome: "success", stop_reason: "checks_pass",
  objective: "Fix the median for an even number of values", base: "inputs", template: null, files_changed: ["stats.py"],
  checks: { compile: "passed", tests: "passed" }, model_calls: 3, tokens: 2400, edits: 2, edits_rejected: 1, commands: 2,
  denials: 1, flags: ["README.md:3"], revision_round: 0, original_task_id: null, head_version: 1, updated_at: "2026-10-25T10:00:00Z",
};

const detail: RunDetail = {
  summary,
  diff: "--- a/stats.py\n+++ b/stats.py\n@@ -1,2 +1,3 @@\n mid = len(ordered) // 2\n-return ordered[mid]\n+if len(ordered) % 2:\n+    return ordered[mid]\n",
  changeset: { task_id: "T-C", files_changed: ["stats.py"], notes: "checks: compile passed" },
  revisions: [],
  trace: {
    task_id: "T-C", status: "done", objective: summary.objective, acceptance_criteria: ["median([1, 2, 3, 4]) == 2.5"], base: "inputs",
    template: null, required_changes: [], located: [{ path: "stats.py", score: 0.4 }], plan: { summary: "handle even counts" },
    steps: [
      { n: 1, kind: "plan", summary: "handle even counts", prompt_tokens: 900, completion_tokens: 60, ok: true },
      { n: 2, kind: "edit", summary: "edit attempt 1", prompt_tokens: 700, completion_tokens: 90, ok: false },
      { n: 3, kind: "edit", summary: "edit attempt 2", prompt_tokens: 700, completion_tokens: 90, ok: true },
    ],
    edits: [
      { step: 2, files: [], ok: false, error: "SEARCH was not found in stats.py.", notes: [] },
      { step: 3, files: ["stats.py"], ok: true, error: null, notes: [] },
    ],
    commands: [
      { step: 3, cmd: "python -m unittest", exit_code: 0, timed_out: false, duration_s: 0.4, output: "Ran 2 tests\n\nOK", denied: null },
      { step: 3, cmd: "curl http://x", exit_code: null, timed_out: false, duration_s: 0, output: "", denied: "'curl' may not run here" },
    ],
    denials: ["curl http://x: 'curl' may not run here"], flags: ["README.md:3"],
    checks: [{ name: "compile", status: "passed", detail: "" }, { name: "tests", status: "passed", detail: "" }],
    reflections: [], files_changed: ["stats.py"], stop_reason: "checks_pass", outcome: "success", notes: ["self-review (checks): scores 1.00"],
  },
};

describe("CodingPanel", () => {
  beforeEach(() => {
    listRuns.mockResolvedValue([summary]);
    getRun.mockResolvedValue(detail);
    requestChanges.mockResolvedValue({ task_id: "T-R", round: 1 });
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the step, its tool-call log and the diff", async () => {
    render(<CodingPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={() => {}} />);
    const cards = await screen.findByRole("list", { name: "Coding steps" });
    expect(cards.textContent).toContain("1 file changed");
    expect(cards.textContent).toContain("done");
    const log = await screen.findByRole("list", { name: "Tool-call log" });
    expect(log.textContent).toContain("refused: SEARCH was not found in stats.py.");
    expect(log.textContent).toContain("denied: 'curl' may not run here");
    expect(screen.getByLabelText("Diff").textContent).toContain("+if len(ordered) % 2:");
    expect(screen.getByText(/Lines that talk to an AI were found in README.md:3/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Download the code" }).getAttribute("href")).toBe("/api/coding/runs/P-1/T-C/workspace.zip");
  });

  it("requests changes, one per line", async () => {
    const reload = vi.fn();
    render(<CodingPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={reload} />);
    const box = await screen.findByLabelText("Changes to make");
    fireEvent.change(box, { target: { value: "- reject empty nicknames\nlog every join" } });
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));
    await waitFor(() => expect(requestChanges).toHaveBeenCalledWith("P-1", "T-C", ["reject empty nicknames", "log every join"]));
    expect(await screen.findByText(/Revision started/)).toBeTruthy();
    expect(reload).toHaveBeenCalled();
  });
});
