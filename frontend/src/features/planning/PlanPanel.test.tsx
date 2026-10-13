// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/types";

import type { PlanResponse, PlanTask } from "./types";

const getPlan = vi.fn();
const decidePlan = vi.fn();
const savePlan = vi.fn();
const replan = vi.fn();

vi.mock("./client", async (importOriginal) => {
  const real = await importOriginal<typeof import("./client")>();
  return {
    ...real,
    getPlan: (...a: unknown[]) => getPlan(...a),
    decidePlan: (...a: unknown[]) => decidePlan(...a),
    savePlan: (...a: unknown[]) => savePlan(...a),
    replan: (...a: unknown[]) => replan(...a),
    getCapabilities: async () => ({
      capabilities: ["code.implement", "test.run", "review.final"],
      by_phase: { research: ["research.run"], design: ["code.implement"], implement: ["code.implement"], test: ["test.run"], document: ["docs.generate"], review: ["review.final"] },
    }),
  };
});
// React Flow needs layout APIs happy-dom lacks; the graph is tested through logic.ts, here it is a list of buttons
vi.mock("./PlanGraph", () => ({
  PlanGraph: ({ tasks, onSelect }: { tasks: PlanTask[]; onSelect: (id: string) => void }) => (
    <div>{tasks.map((t) => <button key={t.id} type="button" onClick={() => onSelect(t.id)}>node {t.id}</button>)}</div>
  ),
}));
vi.mock("@/lib/preferences", () => ({ usePreferences: () => ({ developer: false, theme: "light" }) }));

import { PlanPanel } from "./PlanPanel";

function task(id: string, phase: PlanTask["phase"], deps: string[] = [], reqs: string[] = []): PlanTask {
  return { id, title: `Step ${id}`, description: "", agent_capability: phase === "review" ? "review.final" : phase === "test" ? "test.run" : "code.implement",
    requirement_ids: reqs, acceptance_criteria: ["done"], depends_on: deps, priority: "normal", est_effort: 1, phase, research_questions: [] };
}

function response(version = 1): PlanResponse {
  const tasks = [task("design", "design"), task("T1", "implement", ["design"], ["R1"]), task("T2", "test", ["T1"], ["R1"]), task("review", "review", ["T2"])];
  return {
    artifact: { artifact_id: "ART-1", version, created_by: "planner", created_at: "2026-10-13T00:00:00Z" },
    graph: { project_id: "P-1", version, tasks, roadmap: { phases: [], milestones: [], markdown: "# Plan" }, coverage_matrix: { R1: ["T1", "T2"], R2: [] } },
    report: {
      graph_version: version, origin: "generated", method: "llm", project_kind: "software", prompt_version: "2", answered_by: {}, llm_calls: 1,
      fallbacks: [], repairs: [], issues: [], flagged: { R2: "needs a person" }, deliverables: {}, questions: ["Which port?"], low_confidence: [],
      edges: {}, schedule: { layers: [["design"], ["T1"], ["T2"], ["review"]], critical_path: ["design", "T1", "T2", "review"], earliest_start: {}, slack: {}, total_effort: 4, makespan: 4 },
      feedback: null, author: null,
    },
    versions: [{ version, created_by: "planner", created_at: "2026-10-13T00:00:00Z" }],
    submitted_version: version,
    project_state: "AWAITING_APPROVAL",
    states: { design: "CREATED", T1: "CREATED", T2: "CREATED", review: "CREATED" },
    requirements: { artifact_id: "ART-R", used_version: 1, latest_version: 2, changed: true },
  };
}

const project = { project_id: "P-1", state: "AWAITING_APPROVAL", graph_version: 1 } as unknown as Project;

function show() {
  return render(<PlanPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={vi.fn()} />);
}

beforeEach(() => {
  getPlan.mockResolvedValue(response());
});
afterEach(() => {
  cleanup();
  for (const m of [getPlan, decidePlan, savePlan, replan]) m.mockReset();
});

describe("PlanPanel", () => {
  it("shows the plan, what to check before approving, and approves the shown version with a note", async () => {
    show();
    await screen.findByText("Waiting for your approval");
    expect(screen.getByText("Which port?")).toBeTruthy();
    expect(screen.getByText(/needs a person/)).toBeTruthy();
    expect(screen.getByText(/requirements were edited after this plan/)).toBeTruthy();

    decidePlan.mockResolvedValue(response());
    fireEvent.click(screen.getByRole("button", { name: "Approve plan…" }));
    fireEvent.change(screen.getByLabelText(/note is optional/), { target: { value: "looks good" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve and start" }));
    await waitFor(() => expect(decidePlan).toHaveBeenCalledWith("P-1", true, 1, "looks good"));
  });

  it("needs a reason to reject", async () => {
    show();
    await screen.findByText("Waiting for your approval");
    fireEvent.click(screen.getByRole("button", { name: "Reject…" }));
    const reject = screen.getByRole("button", { name: "Reject plan" }) as HTMLButtonElement;
    expect(reject.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Say what is wrong/), { target: { value: "too many steps" } });
    expect(reject.disabled).toBe(false);
  });

  it("edits a step, saves it as the next version and shows the server's problems", async () => {
    show();
    await screen.findByText("Waiting for your approval");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "node T1" }));
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "Accept many clients" } });

    const { PlanRejected } = await import("./client");
    savePlan.mockRejectedValueOnce(new PlanRejected("Not saved: dependency cycle", [
      { code: "cycle", severity: "error", message: "dependency cycle: T1 -> T2 -> T1", task_id: "T1", requirement_id: null }]));
    fireEvent.click(screen.getByRole("button", { name: "Save as version 2" }));
    await screen.findByText("dependency cycle: T1 -> T2 -> T1");
    const sent = savePlan.mock.calls[0]!;
    expect(sent.slice(0, 3)).toEqual(["P-1", "ART-1", 1]);
    expect(sent[3].tasks.find((t: PlanTask) => t.id === "T1").title).toBe("Accept many clients");
  });

  it("sends feedback and failed steps when the plan is changed", async () => {
    const r = response();
    r.states.T1 = "FAILED";
    getPlan.mockResolvedValue(r);
    replan.mockResolvedValue({ task_id: "T-9", base_version: 1 });
    show();
    await screen.findByText(/1 step failed/);
    fireEvent.click(screen.getByRole("button", { name: "Change plan…" }));
    fireEvent.change(screen.getByLabelText(/What should change/), { target: { value: "Don't use threads" } });
    fireEvent.click(screen.getByRole("button", { name: "Make a new version" }));
    await waitFor(() => expect(replan).toHaveBeenCalledWith("P-1", "Don't use threads", ["T1"]));
  });

  it("shows coverage with flagged requirements", async () => {
    show();
    await screen.findByText("Waiting for your approval");
    fireEvent.click(screen.getByRole("tab", { name: "Coverage" }));
    expect(screen.getByText("For you: needs a person")).toBeTruthy();
    expect(screen.getByText(/Every requirement has a step/)).toBeTruthy();
  });
});
