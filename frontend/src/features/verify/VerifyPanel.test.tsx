// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/types";

import type { RunDetail, RunSummary } from "./types";

const listRuns = vi.fn();
const getRun = vi.fn();
const getPage = vi.fn();
const requestFollowUp = vi.fn();

vi.mock("./client", () => ({
  listRuns: (...a: unknown[]) => listRuns(...a),
  getRun: (...a: unknown[]) => getRun(...a),
  getPage: (...a: unknown[]) => getPage(...a),
  requestFollowUp: (...a: unknown[]) => requestFollowUp(...a),
}));
vi.mock("@/lib/preferences", () => ({ usePreferences: () => ({ developer: false, theme: "light" }) }));

import { VerifyPanel } from "./VerifyPanel";

const project = { project_id: "P-1", name: "x", state: "EXECUTING" } as unknown as Project;
const QUOTE = "This is a stateless authentication mechanism as the user state is never saved in server memory";

const summary: RunSummary = {
  task_id: "T-V", status: "done", round: 0, research_task_id: "T-R", layers: ["l1", "l2", "l3", "l4"], claims: 2, verified: 1,
  unsupported: 1, conflicting: 0, needs_more: 0, model_calls: 6, tokens: 2000, seconds: 1.2, started_at: "2026-10-18T10:00:00Z",
  finished_at: "2026-10-18T10:00:02Z", follow_up_questions: ["Is it true that JWTs use HS512?"], follow_up_of: null, notes: [],
};

const l1ok = [{ evidence_id: "E1", ok: true, reason: "ok", detail: "" }];
const detail: RunDetail = {
  summary,
  research_questions: ["Which token scheme?"],
  follow_ups: [],
  trace: {
    task_id: "T-V", research_task_id: "T-R", layers: summary.layers, round: 0, status: "done", model_calls: 6, tokens: 2000, seconds: 1.2,
    notes: [], follow_up_questions: summary.follow_up_questions,
    claims: [
      { claim_id: "C1", text: "JWTs are stateless", evidence_ids: ["E1"], verdict: "VERIFIED", confidence: 0.8, explanation: "the quotes support the claim",
        supporting: ["E1"], contradicting: [],
        atoms: [{ atom_id: "C1", text: "JWTs are stateless", check_worthy: true, l1: l1ok, l2: { label: "supports", rationale: "says so", by: "model", swapped_label: "supports", guard: "" },
          l3_queries: ["jwt stateless"], l3_passages: 1, l4: [], independent_hosts: [], row: "R8", verdict: "VERIFIED", confidence: 0.8, explanation: "" }],
        evidence: [{ id: "E1", url: "https://en.wikipedia.org/wiki/JSON_Web_Token", quote: QUOTE, content_sha256: "c".repeat(64), title: "JWT",
          page_artifact: { artifact_id: "rp-1", artifact_type: "research-page", version: 1 } }] },
      { claim_id: "C4", text: "JWTs use HS512", evidence_ids: ["E6"], verdict: "UNSUPPORTED", confidence: 0.98, explanation: "a cited quote does not check out",
        supporting: [], contradicting: ["E6"],
        atoms: [{ atom_id: "C4", text: "JWTs use HS512", check_worthy: true, l1: [{ evidence_id: "E6", ok: false, reason: "quote_not_found", detail: "" }], l2: null,
          l3_queries: [], l3_passages: 0, l4: [], independent_hosts: [], row: "R1", verdict: "UNSUPPORTED", confidence: 0.98, explanation: "" }],
        evidence: [] },
    ],
  },
};

describe("VerifyPanel", () => {
  beforeEach(() => {
    listRuns.mockResolvedValue([summary]);
    getRun.mockResolvedValue(detail);
    getPage.mockResolvedValue({ url: "u", title: "JWT", text: `Intro. ${QUOTE}. More.`, content_sha256: "c".repeat(64), spans: [{ evidence_id: "E1", start: 7, end: 7 + QUOTE.length }], license: null });
    requestFollowUp.mockResolvedValue({ research_task_id: "T-R2", verify_task_id: "T-V2" });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("lists flagged findings first with verdict chips and layer results", async () => {
    render(<VerifyPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={() => {}} />);
    const table = await screen.findByRole("list", { name: "Checked findings" });
    expect(table.textContent).toMatch(/C4.*unsupported.*C1.*verified/s);
    expect(screen.getByRole("list", { name: "Verification steps" }).textContent).toContain("1 unsupported");
    fireEvent.click(screen.getByRole("button", { name: /C4/ }));
    expect(await screen.findByText(/E6: the quote is not in the saved page/)).toBeTruthy();
  });

  it("shows the quote next to the saved page and asks for more research", async () => {
    render(<VerifyPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /C1/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Show the saved page" }));
    await waitFor(() => expect(getPage).toHaveBeenCalledWith("P-1", "rp-1", "T-R", expect.anything()));
    expect((await screen.findByText(QUOTE, { selector: "mark" })).tagName).toBe("MARK");
    fireEvent.click(screen.getByRole("button", { name: "Request more research" }));
    await waitFor(() => expect(requestFollowUp).toHaveBeenCalledWith("P-1", "T-V", ["C4"]));
  });
});
