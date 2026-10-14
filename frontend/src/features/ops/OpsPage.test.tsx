// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Explanation, TaskRow } from "./types";

const replayTask = vi.fn();
const row: TaskRow = {
  task_id: "T-1", project_id: "P-1", project_name: "Lab", capability: "research.run", title: "Fetch sources", state: "DEAD_LETTERED",
  attempts: 3, replays: 0, last_error: { code: "TOOL_TRANSIENT", message: "tool timed out" }, updated_at: "2026-10-13T10:00:00Z", plan_task_id: "T1",
};
const explanation: Explanation = {
  task: { task_id: "T-1", project_id: "P-1", capability: "research.run", title: "Fetch sources", objective: "fetch", state: "DEAD_LETTERED", attempts: 3, retries: 2,
    replays: 0, run: 1, plan_task_id: "T1", depends_on: [], blocked_by: [], last_error: { code: "TOOL_TRANSIENT" }, created_at: "", updated_at: "" },
  verdict: { status: "dead_lettered", headline: "It gave up after 3 attempt(s): a temporary tool or network error.", facts: ["errors: TOOL_TRANSIENT x3"],
    cause: "TOOL_TRANSIENT", actions: [{ action: "replay", allowed: true, label: "Replay as a new attempt", why: "" }, { action: "replan", allowed: true, label: "", why: "" }] },
  executions: [{ execution_id: "E-1", attempt: 1, status: "FAILED", agent_id: "agent-r", created_at: "", updated_at: "", error: { code: "TOOL_TRANSIENT", message: "tool timed out" },
    superseded_by: "E-2", orphaned_at: null, outcome: null, late_reports: [] }],
  messages: [{ message_id: "M-1", queue: "hmap.cap.research.run", execution_id: "E-1", created_at: "", published_at: "2026-10-13T10:00:00Z", processed_by: ["agent:x"] }],
  timeline: [{ seq: 1, at: "2026-10-13T10:00:00Z", event_type: "task.retrying", summary: "attempt 1 failed (TOOL_TRANSIENT); retry 1 in 0.1 s" }],
  dependencies: [], dependants: [{ task_id: "T-2", title: "Write", state: "BLOCKED" }],
  trace: { trace_ids: ["abc"], tracing: true, links: ["http://127.0.0.1:16686/trace/abc"] }, artifacts: [],
};

vi.mock("./client", () => ({
  getOverview: async () => ({ tasks_by_state: { DEAD_LETTERED: 1 }, dead_lettered: 1, agents_by_state: { AVAILABLE: 4 }, queues: {}, tracing: true,
    links: { jaeger: "http://127.0.0.1:16686", grafana: "http://127.0.0.1:3001", prometheus: "http://127.0.0.1:9090" }, metrics_path: "/metrics" }),
  getFailures: async () => [row],
  getDeadLetters: async () => ({ tasks: [row], messages: [] }),
  explainTask: async () => explanation,
  replayTask: (...a: unknown[]) => replayTask(...a),
}));
vi.mock("@/lib/preferences", () => ({ usePreferences: () => ({ developer: false, theme: "light" }) }));
vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { OpsPage } from "./OpsPage";

describe("OpsPage", () => {
  beforeEach(() => {
    replayTask.mockResolvedValue({ task_id: "T-1", replay: 1, unblocked: ["T-2"], state: "ASSIGNED", executions: 4 });
    HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) { this.setAttribute("open", ""); };
    HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) { this.removeAttribute("open"); };
  });
  afterEach(() => cleanup());

  it("explains a dead letter and replays it with a reason", async () => {
    render(<OpsPage route="ops" />);
    const attention = await screen.findByRole("list", { name: "Steps that need attention" });
    fireEvent.click(within(attention).getByRole("button", { name: "Why?" }));
    expect(await screen.findByText(/It gave up after 3 attempt/)).toBeTruthy();
    expect(screen.getByText("errors: TOOL_TRANSIENT x3")).toBeTruthy();
    expect(screen.getByText(/Write — blocked/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "open in Jaeger" }).getAttribute("href")).toBe("http://127.0.0.1:16686/trace/abc");
    fireEvent.click(screen.getByRole("button", { name: "Replay as a new attempt…" }));
    const confirm = screen.getByRole("button", { name: "Replay" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);                                 // a reason is required
    fireEvent.change(screen.getByLabelText("Why is it safe to try again?"), { target: { value: "the tool was restarted" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(replayTask).toHaveBeenCalledWith("T-1", "the tool was restarted"));
  });

  it("shows the overview and the dashboard links", async () => {
    render(<OpsPage route="ops" />);
    expect(await screen.findByText("Agents online")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Dashboard (Grafana)" }).getAttribute("href")).toBe("http://127.0.0.1:3001");
    expect(await screen.findByRole("table", { name: "Dead-lettered steps" })).toBeTruthy();
  });
});
