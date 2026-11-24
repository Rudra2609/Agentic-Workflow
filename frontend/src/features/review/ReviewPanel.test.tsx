// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/types";

import type { Decided, ReportDetail, Rounds } from "./types";

const listRounds = vi.fn();
const getReport = vi.fn();
const overrideItem = vi.fn();
const acceptReport = vi.fn();
const requestChanges = vi.fn();

vi.mock("./client", () => ({
  listRounds: (...a: unknown[]) => listRounds(...a),
  getReport: (...a: unknown[]) => getReport(...a),
  overrideItem: (...a: unknown[]) => overrideItem(...a),
  acceptReport: (...a: unknown[]) => acceptReport(...a),
  requestChanges: (...a: unknown[]) => requestChanges(...a),
}));

import { ReviewPanel } from "./ReviewPanel";

const project = { project_id: "P-1", name: "x", state: "REVIEWING" } as unknown as Project;
const evidence = {
  tests: [],
  verification: [],
  deliverables: [],
  doc_ungrounded: [],
  doc_status: null,
  violations: [],
  facts: [],
  producer_note: "Production ready.",
  stub: false,
};

const rounds: Rounds = {
  project_id: "P-1",
  project_state: "REVIEWING",
  rounds: [
    {
      task_id: "RV-0",
      state: "COMPLETED",
      created_at: "2026-11-01T10:00:00Z",
      round: 0,
      recommendation: "REVISE",
      completeness: 0.5,
      failures: 1,
      stop_reason: null,
      plan: {},
      created_tasks: [
        { task_id: "X", capability: "code.revise", title: "Fix the server", state: "COMPLETED", action: "revise",
          parent_task_id: "T-S" },
      ],
      stale_of: null,
      decision: null,
    },
    {
      task_id: "RV-1",
      state: "COMPLETED",
      created_at: "2026-11-01T10:05:00Z",
      round: 1,
      recommendation: "ESCALATE",
      completeness: 0.5,
      failures: 1,
      stop_reason: "plateau: the same failures as the last round (the fix did not help)",
      plan: {},
      created_tasks: [],
      stale_of: null,
      decision: null,
    },
  ],
};

const failing: Decided = {
  item: { id: "R1", kind: "requirement", text: "The server handles several clients.", priority: "must",
          covering: ["T-S"], max_marks: null, evidence },
  check: { verdict: "FAIL", reasons: ["tests failed (server.py)"], category: "INCORRECT", no_action: false },
  verdict: "FAIL",
  source: "objective",
  rationale: "tests failed (server.py)",
  votes: [],
  order_sensitive: false,
  level: null,
  score: null,
};

const detail: ReportDetail = {
  report: {
    project_id: "P-1",
    requirement_results: [],
    rubric_scores: [{ criterion_id: "E1", score: 5, max_marks: 10 }],
    failures: [{ category: "INCORRECT", requirement_id: "R1", responsible_task_id: "T-S",
                 description: "tests failed (server.py)" }],
    revision_requests: [{ task_id: "T-S", action: "escalate", required_changes: [] }],
    overall: 0.5,
    recommendation: "ESCALATE",
  },
  items: [
    failing,
    { ...failing, item: { ...failing.item, id: "E1", kind: "criterion", text: "Design", max_marks: 10 },
      verdict: "PARTIAL", source: "none", rationale: "estimated", score: 5 },
  ],
  mode: "software",
  notes: [],
  tasks: [{ task_id: "T-S", capability: "code.implement", title: "Write the server", plan_task_id: "S" }],
  trace: { round: 1, stop_reason: "plateau" },
  decision: null,
  project_state: "REVIEWING",
};

describe("ReviewPanel", () => {
  beforeEach(() => {
    listRounds.mockResolvedValue(rounds);
    getReport.mockResolvedValue(detail);
    overrideItem.mockResolvedValue({ decision: {} });
    acceptReport.mockResolvedValue({ decision: { accepted: true }, project_state: "COMPLETED" });
    requestChanges.mockResolvedValue({ created: ["A", "B"] });
  });
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the rounds, the matrix, marks and failures linked to their step", async () => {
    render(<ReviewPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={() => {}} />);
    expect(await screen.findByText("Round 1")).toBeTruthy();
    expect(screen.getByText("Needs a person")).toBeTruthy();
    expect(screen.getByText(/Fix the server/)).toBeTruthy();
    expect(await screen.findByText("The server handles several clients.")).toBeTruthy();
    expect(screen.getByText("5 / 10 marks (estimated)")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Write the server" });
    expect(link.getAttribute("href")).toBe("/features/ops?task=T-S");
    expect(screen.getByText(/The review stopped and asks you: plateau/)).toBeTruthy();
    expect(getReport).toHaveBeenCalledWith("P-1", "RV-1", expect.anything());
  });

  it("overrides, accepts and requests changes", async () => {
    const reload = vi.fn();
    render(<ReviewPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={reload} />);
    fireEvent.click(await screen.findByRole("button", { name: "PASS for R1" }));
    await waitFor(() => expect(overrideItem).toHaveBeenCalledWith("P-1", "RV-1", "R1", "PASS", expect.any(String)));
    fireEvent.change(screen.getByLabelText("Accept with notes"), { target: { value: "ok" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(acceptReport).toHaveBeenCalledWith("P-1", "RV-1", "ok"));
    fireEvent.change(screen.getByLabelText("Request changes"), { target: { value: "log to a file" } });
    fireEvent.change(screen.getByLabelText(/Step to revise/), { target: { value: "T-S" } });
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));
    await waitFor(() => expect(requestChanges).toHaveBeenCalledWith("P-1", "RV-1", "log to a file", "T-S"));
    expect(await screen.findByText("2 step(s) created.")).toBeTruthy();
    expect(reload).toHaveBeenCalled();
  });
});
