import { describe, expect, it } from "vitest";

import { describeEvent, nameFromGoal, projectStateText, roleOf, taskStateText } from "@/lib/plain";
import type { Approval, HmapEvent, Project, Task } from "@/lib/types";
import { approvalsOfRun, documentsSummary, layoutGraph, NODE_W, stagesOf } from "@/lib/workflow";

function task(over: Partial<Task>): Task {
  return {
    task_id: "T", project_id: "P", capability: "echo", objective: "o", title: null, acceptance_criteria: [], inputs: {},
    artifact_refs: [], context_refs: [], depends_on: [], parent_task_id: null, plan_task_id: null, run: 1,
    priority: "normal", needs_approval: false, state: "CREATED", state_version: 1, active_execution_id: null,
    attempts: 0, retries: 0, rejections: 0, rejected_by: [], retry_at: null, last_error: null, blocked_by: [],
    created_at: "2026-10-11T10:00:00Z", updated_at: "2026-10-11T10:00:00Z", ...over,
  };
}

function project(over: Partial<Project>): Project {
  return {
    project_id: "P", name: "p", state: "EXECUTING", state_version: 1, created_at: "2026-10-11T09:00:00Z",
    updated_at: "2026-10-11T09:00:00Z", graph_version: 1, plan_task_map: {}, auto_approve: false, cloud_ok: true, stopped_reason: null,
    runs: [{ number: 1, started_at: "2026-10-11T09:59:00Z", finished_at: null, outcome: null, goal: "Build it", documents: ["request.txt"] }],
    approvals: [], ...over,
  };
}

const approval = (over: Partial<Approval>): Approval => ({
  approval_id: "A", project_id: "P", graph_version: 1, status: "pending", comment: null,
  requested_at: "2026-10-11T10:01:00Z", decided_at: null, ...over,
});

describe("stagesOf", () => {
  it("reflects a plan waiting for review, with nothing invented", () => {
    const tasks = [
      task({ task_id: "E", capability: "document.extract", state: "COMPLETED" }),
      task({ task_id: "G", capability: "plan.generate", state: "COMPLETED" }),
      task({ task_id: "W1", plan_task_id: "T1", needs_approval: true }),
    ];
    const p = project({ state: "AWAITING_APPROVAL", approvals: [approval({})] });
    const s = stagesOf(p, tasks, 1);
    expect(s.map((x) => [x.id, x.status])).toEqual([
      ["request", "done"], ["understanding", "done"], ["plan", "done"], ["review", "waiting"], ["work", "pending"],
    ]);
    expect(s[1]!.taskId).toBe("E");
    expect(s[4]!.detail).toBe("0 of 1 steps done.");
  });

  it("marks auto-approval as skipped, failures as failed and stops as stopped", () => {
    const auto = project({ auto_approve: true, approvals: [approval({ status: "approved", comment: "auto-approved (project setting)" })] });
    const failing = [task({ capability: "document.extract", state: "COMPLETED" }), task({ capability: "plan.generate", state: "COMPLETED" }),
      task({ task_id: "W", plan_task_id: "T1", state: "FAILED" })];
    const s = stagesOf(auto, failing, 1);
    expect(s[3]!.status).toBe("skipped");
    expect(s[4]!.status).toBe("failed");
    const stopped = project({ state: "CANCELLED", approvals: [approval({ status: "rejected", comment: "project stopped: stopped by user" })] });
    const st = stagesOf(stopped, [task({ capability: "document.extract", state: "CANCELLED" })], 1);
    expect(st[1]!.status).toBe("stopped");
    expect(st[3]!.detail).toBe("Closed when the work was stopped.");
  });

  it("keeps runs apart", () => {
    const p = project({
      runs: [
        { number: 1, started_at: "2026-10-11T09:00:00Z", finished_at: "2026-10-11T09:30:00Z", outcome: "COMPLETED", goal: "a", documents: [] },
        { number: 2, started_at: "2026-10-11T11:00:00Z", finished_at: null, outcome: null, goal: "b", documents: [] },
      ],
      approvals: [approval({ approval_id: "A1", requested_at: "2026-10-11T09:10:00Z" }), approval({ approval_id: "A2", requested_at: "2026-10-11T11:05:00Z" })],
    });
    expect(approvalsOfRun(p.approvals!, p.runs!, 1).map((a) => a.approval_id)).toEqual(["A1"]);
    expect(approvalsOfRun(p.approvals!, p.runs!, 2).map((a) => a.approval_id)).toEqual(["A2"]);
    const tasks = [task({ task_id: "old", capability: "document.extract", state: "COMPLETED", run: 1 })];
    expect(stagesOf(p, tasks, 2)[1]!.status).toBe("pending");
  });
});

describe("layoutGraph", () => {
  it("puts each node one column after its deepest dependency and draws one edge per dependency", () => {
    const g = layoutGraph([
      { id: "A", dependsOn: [] }, { id: "B", dependsOn: ["A"] }, { id: "C", dependsOn: ["A"] },
      { id: "D", dependsOn: ["B", "C", "missing"] },
    ]);
    const at = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
    expect([at.A!.layer, at.B!.layer, at.C!.layer, at.D!.layer]).toEqual([0, 1, 1, 2]);
    expect([at.B!.row, at.C!.row]).toEqual([0, 1]);
    expect(g.edges.map((e) => `${e.from}>${e.to}`).sort()).toEqual(["A>B", "A>C", "B>D", "C>D"]);
    expect(g.edges[0]!.path.startsWith(`M ${NODE_W} `)).toBe(true);
    expect(g.width).toBeGreaterThan(2 * NODE_W);
    expect(layoutGraph([])).toEqual({ nodes: [], edges: [], width: 0, height: 0 });
  });
});

describe("plain language", () => {
  const ev = (event_type: string, data: Record<string, unknown> = {}): HmapEvent => ({
    seq: 1, event_id: "e", event_type, aggregate_id: "T1", occurred_at: "2026-10-11T10:00:00Z", project_id: "P", data,
  });

  it("maps real capabilities to roles and falls back honestly", () => {
    expect(roleOf("code.implement").name).toBe("Developer");
    expect(roleOf("weird.thing").name).toBe("Weird thing");
  });

  it("translates states and events, hiding low-level ones", () => {
    expect(projectStateText("AWAITING_APPROVAL").label).toBe("Needs your review");
    expect(taskStateText("DEAD_LETTERED").tone).toBe("danger");
    expect(describeEvent(ev("approval.requested"))).toBe("Your plan is ready for review.");
    expect(describeEvent(ev("approval.decided", { approved: true, auto: true }))).toContain("automatically");
    expect(describeEvent(ev("task.completed", { capability: "research.run" }))).toBe("Researcher finished.");
    expect(describeEvent(ev("task.completed"), () => "Write the report")).toBe("Write the report finished.");
    expect(describeEvent(ev("task.progress"))).toBeNull();
    expect(describeEvent(ev("task.assigned"))).toBeNull();
    expect(describeEvent(ev("document.uploaded", { filename: "brief.pdf" }))).toBe("Document “brief.pdf” was added.");
    const files = [{ folder: "Part A" }, { folder: "Part A" }, { folder: "Part B" }, { folder: null }];
    expect(describeEvent(ev("document.uploaded", { filename: "Part A/a.pdf", files }))).toBe("4 documents were added from 2 folders.");
  });

  it("names a project from the first sentence of a goal", () => {
    expect(nameFromGoal("Build a site for the chess club. It needs a leaderboard.")).toBe("Build a site for the chess club");
    expect(nameFromGoal("   ")).toBe("Untitled project");
    expect(nameFromGoal("x".repeat(80)).length).toBeLessThanOrEqual(58);
  });
});

describe("documentsSummary", () => {
  it("names one document, counts several and lists their folders", () => {
    expect(documentsSummary(["brief.pdf"])).toBe("brief.pdf");
    expect(documentsSummary(["a.pdf", "b.md"])).toBe("2 documents");
    expect(documentsSummary(["Part A/a.pdf", "Part A/b.md", "Part B/c.txt", "Part C/d.png"])).toBe(
      "4 documents in 3 folders (Part A, Part B, Part C)",
    );
    expect(documentsSummary(["Part A/a.pdf", "loose.txt"])).toBe("2 documents in 1 folder (Part A)");
  });
});
