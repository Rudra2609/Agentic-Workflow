// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/types";

import type { RefineRun, RunSummary } from "./types";

const listRuns = vi.fn();
const getRun = vi.fn();
const getDiff = vi.fn();
const updateProject = vi.fn();

vi.mock("./client", () => ({
  listRuns: (...a: unknown[]) => listRuns(...a),
  getRun: (...a: unknown[]) => getRun(...a),
  getDiff: (...a: unknown[]) => getDiff(...a),
  getPolicy: async () => ({ default: { max_iters: 3, threshold: 0.9 }, hard_max_iters: 10 }),
  checkAgain: async () => ({ task_id: "T-9", version: 2 }),
}));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: { updateProject: (...a: unknown[]) => updateProject(...a), listArtifacts: async () => [] },
}));
let developer = false;
vi.mock("@/lib/preferences", () => ({ usePreferences: () => ({ developer, theme: "light" }) }));

import { RefinePanel } from "./RefinePanel";

const project = (refine: boolean) => ({ project_id: "P-1", name: "x", state: "AWAITING_APPROVAL", refine } as unknown as Project);

const summary: RunSummary = {
  run_id: "rf-T-1", task_id: "T-1", capability: "document.extract", subject: "requirements", status: "stopped", iterations: 1,
  best_iteration: 1, stop_reason: "threshold", base_score: 0.6, best_score: 0.95, tokens: 1200, model_calls: 3, seconds: 4.2,
  started_at: "2026-10-13T10:00:00Z", updated_at: "2026-10-13T10:00:05Z", applied: true, error: null,
  output_artifact: { artifact_id: "A-1", artifact_type: "requirement-set", version: 2 }, issues_by_category: {}, scores: [0.6, 0.95],
};

const run: RefineRun = {
  ...summary, project_id: "P-1", status: "stopped",
  spec: { producer: "document.extract agent", critics: ["quotes", "judge"], reviser: "extraction-patch", stop_policy: {} },
  iterations: [
    { index: 0, score: 0.6, tokens: 700, duration_s: 2, strategy: null, reflection: "R9 was missed; quote the sentence.", revision_notes: [], rejected_changes: ["add requirement: its quote is not in the documents"],
      critics: [{ critic: "quotes", score: 1, issues: 0 }, { critic: "judge", score: 0.5, issues: 1 }], issues_by_category: { OMISSION: 1 },
      critique: { score: 0.6, critic: "composite", issues: [{ category: "OMISSION", severity: "major", description: "A wish is not listed.", location: "requirements", evidence: "Dark mode would be nice." }] } },
    { index: 1, score: 0.95, tokens: 500, duration_s: 2.2, strategy: "targeted", reflection: null, revision_notes: ["strategy: targeted (extraction-patch)", "add requirement"], rejected_changes: [],
      critic_errors: ["judge: ReplayMissError"], critics: [{ critic: "quotes", score: 1, issues: 0 }], issues_by_category: {}, critique: { score: 0.95, critic: "composite", issues: [] } },
  ],
};

describe("RefinePanel", () => {
  beforeEach(() => {
    developer = false;
    listRuns.mockResolvedValue([summary]);
    getRun.mockResolvedValue(run);
    getDiff.mockResolvedValue({ changes: [{ path: "requirements/R4", op: "added", before: null, after: { id: "R4", text: "The app could offer a dark mode." } }] });
    updateProject.mockResolvedValue({});
  });
  afterEach(() => cleanup());

  it("shows each round with problems by kind, the score and what changed", async () => {
    render(<RefinePanel projectId="P-1" project={project(true)} tasks={[]} events={[]} reload={() => {}} />);
    expect(await screen.findByText("Requirements: improved")).toBeTruthy();
    expect(screen.getAllByText(/Improved from 60% to 95% in 1 round/).length).toBeGreaterThan(0);
    expect(screen.getByText("Good enough: the score reached the target.")).toBeTruthy();
    expect(screen.getAllByRole("img", { name: /Original 60%, Revision 1 95%/ }).length).toBe(2);   // card + detail
    expect(screen.getByText("Missing (1)")).toBeTruthy();
    expect(screen.getByText("Dark mode would be nice.")).toBeTruthy();
    expect(screen.getByText(/R9 was missed/)).toBeTruthy();
    expect(screen.getByText("Fixed only the flagged parts.")).toBeTruthy();
    expect(screen.queryByText(/strategy: targeted/)).toBeNull();            // simple mode hides internals
    expect(screen.queryByText(/Refused changes/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "What changed" }));
    expect(await screen.findByText("Added requirement R4")).toBeTruthy();
    expect(getDiff).toHaveBeenCalledWith("P-1", "rf-T-1", 0, 1, expect.anything());
  });

  it("developer mode adds critics, cost and refused changes", async () => {
    developer = true;
    render(<RefinePanel projectId="P-1" project={project(true)} tasks={[]} events={[]} reload={() => {}} />);
    expect(await screen.findByText(/1,200 tokens · 3 model calls/)).toBeTruthy();
    expect(screen.getByText("Refused changes (1)")).toBeTruthy();
    expect(screen.getByText("judge 50%")).toBeTruthy();
    expect(screen.getByText(/Only the automatic checks scored this round/)).toBeTruthy();
    expect(screen.getByText("(judge: ReplayMissError)")).toBeTruthy();
  });

  it("explains when checking is off and turns it on", async () => {
    listRuns.mockResolvedValue([]);
    const reload = vi.fn();
    render(<RefinePanel projectId="P-1" project={project(false)} tasks={[]} events={[]} reload={reload} />);
    expect(await screen.findByText("Results are not being checked")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("P-1", { refine: true }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
  });
});
