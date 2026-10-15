// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "@/lib/types";

import type { RunDetail, RunSummary } from "./types";

const listRuns = vi.fn();
const getRun = vi.fn();
const getPage = vi.fn();
const startResearch = vi.fn();

vi.mock("./client", () => ({
  listRuns: (...a: unknown[]) => listRuns(...a),
  getRun: (...a: unknown[]) => getRun(...a),
  getPage: (...a: unknown[]) => getPage(...a),
  startResearch: (...a: unknown[]) => startResearch(...a),
  getProviders: async () => ({ mode: "cached", providers: ["wikipedia", "local"], corpus: { pages: 105, by_kind: {} } }),
}));
let developer = false;
vi.mock("@/lib/preferences", () => ({ usePreferences: () => ({ developer, theme: "light" }) }));

import { ResearchPanel } from "./ResearchPanel";

const project = { project_id: "P-1", name: "x", state: "EXECUTING" } as unknown as Project;
const QUOTE = "An event loop runs in a single thread and multiplexes many sockets";
const PAGE_TEXT = `asyncio is a library. ${QUOTE}. Coroutines yield control.`;

const summary: RunSummary = {
  task_id: "T-1", status: "stopped", mode: "cached", providers: ["wikipedia", "local"], rounds: 2, stop_reason: "all_covered",
  tokens: 4200, model_calls: 6, seconds: 3.1, started_at: "2026-10-14T10:00:00Z", finished_at: "2026-10-14T10:00:03Z",
  questions: ["Threads or asyncio for a chat server?"], claims: 1, evidence: 1, sources: 1, sub_questions: 2, covered: 1, coverage: 0.5,
};

const detail: RunDetail = {
  summary,
  brief: { questions: summary.questions, scope: "" },
  trace: {
    task_id: "T-1", mode: "cached", providers: ["wikipedia", "local"], status: "stopped", stop_reason: "all_covered", planner: "model",
    synthesis: "model", claims_dropped: ["Threads are deprecated (no existing evidence cited)"], tokens: 4200, model_calls: 6, seconds: 3.1,
    notes: [],
    rounds: [{ index: 1, queries: [{ sub_question: "S1.1", provider: "wikipedia", query: "asyncio event loop sockets", hits: 3 }], hits: 3,
      fetched: 2, fetch_failures: { not_in_cache: 1 }, selected: [], triaged: 2, relevant: 2, quotes_proposed: 2, quotes_dropped: 1,
      new_evidence: 1, novelty: 1, coverage: { "S1.1": 1 }, tokens: 4200, seconds: 3 }],
  },
  report: {
    task_id: "T-1", questions: summary.questions, stop_reason: "all_covered", summary_markdown: "## Threads or asyncio\n- One loop. [1]",
    coverage: { "S1.1": 1, "S1.2": 0 },
    sub_questions: [
      { id: "S1.1", question: 0, text: "How does an event loop serve many sockets?", queries: [], success_criteria: "", coverage: 1, status: "covered" },
      { id: "S1.2", question: 0, text: "What does the GIL cost threads?", queries: [], success_criteria: "", coverage: 0, status: "open" },
    ],
    claims: [{ id: "C1", text: "One asyncio event loop thread can serve many sockets.", evidence_ids: ["E1"] }],
    evidence: [{ id: "E1", url: "https://docs.python.org/3/library/asyncio.html", quote: QUOTE, content_sha256: "a".repeat(64),
      retrieved_at: "2026-10-14T10:00:00Z", sub_question: "S1.1", page_artifact: { artifact_id: "rp-1", artifact_type: "research-page", version: 1 } }],
    sources: [{ url: "https://docs.python.org/3/library/asyncio.html", title: "asyncio — Asynchronous I/O", score: 0.91,
      score_breakdown: { relevance: 0.95, authority: 1, recency: 1, novelty: 1 }, provider: "local", kind: "web", retrieved_at: null,
      content_sha256: "a".repeat(64), page_artifact: null }],
  },
};

describe("ResearchPanel", () => {
  beforeEach(() => {
    developer = false;
    listRuns.mockResolvedValue([summary]);
    getRun.mockResolvedValue(detail);
    getPage.mockResolvedValue({ url: detail.report!.evidence[0]!.url, title: "asyncio", kind: "web", provider: "local", retrieved_at: "",
      content_sha256: "a".repeat(64), text: PAGE_TEXT, spans: [{ evidence_id: "E1", start: PAGE_TEXT.indexOf(QUOTE), end: PAGE_TEXT.indexOf(QUOTE) + QUOTE.length }],
      injection_lines_removed: 0, license: "PSF Documentation License" });
    startResearch.mockResolvedValue({ task_id: "T-2" });
  });
  afterEach(() => cleanup());

  it("shows sub-questions, cited findings, sources and the highlighted quote", async () => {
    render(<ResearchPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={() => {}} />);
    expect(await screen.findByText("One asyncio event loop thread can serve many sockets.")).toBeTruthy();
    expect(screen.getAllByText("Every sub-question was answered by sources.").length).toBeGreaterThan(0);
    expect(screen.getByText("answered")).toBeTruthy();
    expect(screen.getByText("not answered")).toBeTruthy();
    expect(screen.getAllByText("No sourced answer found.").length).toBe(1);
    expect(screen.getByText("Offline: saved pages only")).toBeTruthy();
    expect(screen.getByText("source quality 100%")).toBeTruthy();
    expect(screen.queryByText(/4,200 tokens/)).toBeNull();                      // simple mode
    fireEvent.click(screen.getByRole("button", { name: "[1]" }));
    expect(screen.getAllByRole("button", { name: "[1]" }).length).toBe(1);   // one chip per source
    const mark = await screen.findByText(QUOTE, { selector: "mark" });
    expect(mark).toBeTruthy();
    expect(screen.getByText(/Licence: PSF Documentation License/)).toBeTruthy();
    expect(getPage).toHaveBeenCalledWith("P-1", "rp-1", "T-1", expect.anything());
  });

  it("developer mode shows cost, refused findings and the reasons pages were not read", async () => {
    developer = true;
    render(<ResearchPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={() => {}} />);
    expect(await screen.findByText(/4,200 tokens · 6 model calls/)).toBeTruthy();
    expect(screen.getByText(/Findings refused by the citation check \(1\)/)).toBeTruthy();
    expect(screen.getByText(/Not read: not in cache 1/)).toBeTruthy();
    expect(screen.getByText(/1 refused \(not word for word\)/)).toBeTruthy();
  });

  it("starts research on typed questions", async () => {
    listRuns.mockResolvedValue([]);
    render(<ResearchPanel projectId="P-1" project={project} tasks={[]} events={[]} reload={() => {}} />);
    expect(await screen.findByText("No research yet")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Questions to research/), { target: { value: "What is TCP framing?\nWhy asyncio?" } });
    fireEvent.click(screen.getByRole("button", { name: "Research" }));
    await waitFor(() => expect(startResearch).toHaveBeenCalledWith("P-1", ["What is TCP framing?", "Why asyncio?"]));
  });
});
