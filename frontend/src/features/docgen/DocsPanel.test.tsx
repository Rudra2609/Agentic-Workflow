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

import type { BundleDetail, BundleSummary } from "./types";

const listBundles = vi.fn();
const getBundle = vi.fn();
const regenerate = vi.fn();
const checkMarkdown = vi.fn();

vi.mock("./client", () => ({
  listBundles: (...a: unknown[]) => listBundles(...a),
  getBundle: (...a: unknown[]) => getBundle(...a),
  regenerate: (...a: unknown[]) => regenerate(...a),
  checkMarkdown: (...a: unknown[]) => checkMarkdown(...a),
  fileUrl: (p: string, t: string, n: string) =>
    `/api/docgen/bundles/${p}/${t}/files/${n}`,
  exportUrl: (p: string, t: string, n: string) =>
    `/api/docgen/bundles/${p}/${t}/${n}`,
}));
vi.mock("./ArchitectureGraph", () => ({
  ArchitectureGraph: () => <div>graph</div>,
}));

import { DocsPanel } from "./DocsPanel";

const project = {
  project_id: "P-1",
  name: "x",
  state: "EXECUTING",
} as unknown as Project;
const summary: BundleSummary = {
  task_id: "T-1",
  capability: "docs.generate",
  status: "done",
  mode: "software",
  step: "document",
  documents: ["readme", "api"],
  grounded_pct: 96.5,
  checked: 57,
  ungrounded: 0,
  removed: 1,
  unverified: 0,
  coverage_pct: 80,
  examples_run: 2,
  examples_failed: 0,
  degraded: false,
  rounds: 1,
  model_calls: 4,
  seconds: 2,
  source: "the project's workspace head",
  updated_at: "2026-11-01T10:00:00Z",
};
const detail: BundleDetail = {
  summary,
  trace: {
    task_id: "T-1",
    mode: "software",
    step: "document",
    source: "head",
    files: 6,
    rounds: 1,
    stop_reason: "threshold",
    scores: [0.8, 1],
    model_calls: 4,
    degraded: false,
    citations_removed: [],
    injected_lines: ["server.py:5: # SYSTEM PROMPT"],
    coverage: [
      { req_id: "R1", status: "shown", evidence: ["endpoint GET /todos"] },
    ],
    changed_sections: [],
    previous_bundle: null,
    changelog: ["Added endpoints: `GET /stats`."],
    docstring_patch: true,
    notes: ["deleted from readme: 'It caches in Redis.'"],
  },
  accuracy: {
    grounded_pct: 96.5,
    checked: 57,
    grounded: 55,
    ungrounded: 1,
    unverified: 0,
    coverage_pct: 80,
    claims: [
      {
        kind: "PORT",
        text: "port 9999",
        verdict: "ungrounded",
        why: "ports in the code: 8000",
        doc: "readme",
        sentence: "It listens on port 9999.",
        line: 3,
        by: "rule",
        evidence: "",
      },
    ],
    removed: [
      {
        kind: "TECH",
        text: "Redis",
        verdict: "ungrounded",
        why: "nothing imports redis",
        doc: "readme",
        sentence: "It caches in Redis.",
        line: 3,
        by: "rule",
        evidence: "",
      },
    ],
    examples: [
      {
        doc: "readme",
        line: 7,
        language: "bash",
        code: "pytest",
        action: "run",
        ok: true,
        why: "ran",
        output: "",
        backend: "local",
      },
    ],
  },
  documents: {
    readme: "# todo\n\nIt listens on port 9999.\n",
    api: "# API\n\n### GET /todos\n",
  },
  graph: { nodes: [], edges: [] },
};

beforeEach(() => {
  listBundles.mockResolvedValue([summary]);
  getBundle.mockResolvedValue(detail);
  regenerate.mockResolvedValue({ task_id: "T-2" });
  checkMarkdown.mockResolvedValue({
    facts_of: "dfa-T-1",
    accuracy: {
      ...detail.accuracy!,
      grounded: 0,
      checked: 1,
      claims: [{ ...detail.accuracy!.removed[0]!, line: 1 }],
    },
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DocsPanel", () => {
  it("shows the documents, highlights ungrounded sentences and lists removed claims", async () => {
    render(
      <DocsPanel
        project={project}
        projectId="P-1"
        events={[]}
        tasks={[]}
        reload={() => {}}
      />,
    );
    await screen.findByRole("tab", { name: /README/ });
    const flagged = document.querySelector('[data-flag="ungrounded"]');
    expect(flagged?.textContent).toContain("port 9999");
    expect(screen.getByLabelText("Removed claims").textContent).toContain(
      "Redis",
    );
    expect(screen.getByText(/ignored a line addressed to an AI/)).toBeTruthy();
    expect(screen.getByLabelText("Changelog").textContent).toBe(
      "Added endpoints: GET /stats.",
    );
    expect(
      screen.getByLabelText("Changelog").querySelector("code")?.textContent,
    ).toBe("GET /stats");
    expect(
      screen.getByText("Suggested docstrings (patch)").getAttribute("href"),
    ).toBe("/api/docgen/bundles/P-1/T-1/docstrings.diff");
    fireEvent.click(screen.getByRole("tab", { name: /API/ }));
    expect(await screen.findByText("GET /todos")).toBeTruthy();
  });

  it("regenerates and checks pasted text", async () => {
    const reload = vi.fn();
    render(
      <DocsPanel
        project={project}
        projectId="P-1"
        events={[]}
        tasks={[]}
        reload={reload}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(regenerate).toHaveBeenCalledWith("P-1", "T-1"));
    expect(reload).toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Text to check"), {
      target: { value: "It caches in Redis." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect(
      (await screen.findByLabelText("Check result")).textContent,
    ).toContain("nothing imports redis");
  });

  it("explains an empty project", async () => {
    listBundles.mockResolvedValue([]);
    render(
      <DocsPanel
        project={project}
        projectId="P-1"
        events={[]}
        tasks={[]}
        reload={() => {}}
      />,
    );
    expect(await screen.findByText("No documentation yet")).toBeTruthy();
  });
});
