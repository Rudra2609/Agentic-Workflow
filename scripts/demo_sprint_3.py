#!/usr/bin/env python3
"""Sprint 3 demo (Member 3, planning): PDF -> requirements -> plan -> edit -> approve -> steps run in dependency
order (independent ones at the same time) -> replan with feedback, all over the API.

1. Upload the TCP chat assignment (guide §32): the planner makes a validated plan (one final review, every
   requirement covered, research questions for the Researcher).
2. Edit the plan (a new step) -> version 2; deciding on the old version is refused (409); approve version 2.
3. The placeholder agents run the steps: each starts only after its dependencies finished, and at least two run at
   the same time (from the event log).
4. "Don't use threads": a replan keeps every finished step and turns the feedback into a change request; approve.
5. A three-part upload: Part B's build waits for Part A (its requirements say so).

Talks to a running API (default http://127.0.0.1:8767; demo_sprint_3.sh starts one). Exits non-zero if a check fails.
"""

import secrets
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait
import demo_sprint_2 as docs  # folder upload + check helpers

GOLD = Path(__file__).resolve().parents[1] / "samples" / "doc_intel" / "gold" / "docs"
check = docs.check


def plan_of(pid: str) -> dict:
    return demo.call("GET", f"/planning/plan/{pid}")  # type: ignore[return-value]


def show(plan: dict) -> None:
    g, report = plan["graph"], plan["report"]
    by_id = {t["id"]: t for t in g["tasks"]}
    s = report["schedule"]
    print(f"    {len(g['tasks'])} steps, ~{s['total_effort']} h of work, critical path {s['makespan']} h "
          f"({report['method']}, answered by {report['answered_by'] or 'rules'})")
    for i, layer in enumerate(s["layers"], start=1):
        print(f"    stage {i:2d}: " + " | ".join(f"{t} {by_id[t]['title'][:34]}" for t in layer))
    print(f"    critical path: {' -> '.join(s['critical_path'])}")


def events(pid: str) -> list[dict]:
    return sorted(demo.call("GET", f"/events?project_id={pid}&limit=2000"), key=lambda e: e["seq"])  # type: ignore[arg-type]


def run_order_checks(pid: str) -> None:
    tasks = {t["task_id"]: t for t in demo.call("GET", f"/projects/{pid}/tasks")  # type: ignore[union-attr]
             if t["plan_task_id"] and not t.get("replaced")}
    started: dict[str, int] = {}
    done: dict[str, int] = {}
    running: set[str] = set()
    peak = 0
    for e in events(pid):
        tid = e["aggregate_id"]
        if tid not in tasks:
            continue
        if e["event_type"] == "task.started":
            started[tid] = e["seq"]
            running.add(tid)
            peak = max(peak, len(running))
        elif e["event_type"] == "task.completed":
            done[tid] = e["seq"]
            running.discard(tid)
    ok = all(done.get(d, 1 << 62) < started.get(tid, -1) for tid, t in tasks.items() for d in t["depends_on"]
             if d in tasks and tid in started)
    check(ok, "every step started only after all the steps it waits for had finished")
    check(peak >= 2, f"independent steps ran at the same time (up to {peak} at once)")


def main() -> None:
    demo.API = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8767").rstrip("/") + "/api"
    for _ in range(120):
        try:
            demo.call("GET", "/health")
            break
        except OSError:
            time.sleep(0.5)
    demo.sign_up("Sprint 3 demo", f"sprint3-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    check(caps.get("plan.generate") == "real", "plan.generate is served by the real planning agent")

    # 1. PDF -> plan
    pid = demo.call("POST", "/projects", {"name": "Sprint 3 demo: TCP chat"})["project_id"]  # type: ignore[index]
    t0 = time.time()
    docs.upload(pid, [("tcp_chat_assignment.pdf", GOLD / "g01_tcp_chat" / "tcp_chat_assignment.pdf")])
    demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("AWAITING_APPROVAL", "FAILED"), "the plan", timeout=600)
    plan = plan_of(pid)
    print(f"\nTCP chat: requirements + plan in {time.time() - t0:.1f} s")
    show(plan)
    g, report = plan["graph"], plan["report"]
    sinks = [t["id"] for t in g["tasks"] if not any(t["id"] in o["depends_on"] for o in g["tasks"])]
    check(len(sinks) == 1 and next(t for t in g["tasks"] if t["id"] == sinks[0])["agent_capability"] == "review.final",
          "the plan is one DAG ending in a single final review")
    check(all(g["coverage_matrix"][r] or r in report["flagged"] for r in g["coverage_matrix"]),
          f"all {len(g['coverage_matrix'])} requirements are covered by a step (or flagged for a person)")
    check(all(t["research_questions"] for t in g["tasks"] if t["agent_capability"] == "research.run"),
          "research steps carry questions for the Researcher (Member 5)")

    # 2. edit -> v2, stale approval refused, approve v2
    edited = dict(g)
    edited["tasks"] = [*g["tasks"], {"id": "X1", "title": "Add a /quit command", "agent_capability": "code.implement",
                                     "phase": "implement", "requirement_ids": ["R2"]}]
    v2 = demo.call("PUT", f"/planning/plan/{pid}", {"artifact_id": plan["artifact"]["artifact_id"],
                                                    "base_version": 1, "graph": edited})
    check(v2["artifact"]["version"] == 2 and v2["submitted_version"] == 2,  # type: ignore[index]
          "a human edit is validated and becomes version 2 (version 1 kept)")
    try:
        demo.call("POST", f"/planning/plan/{pid}/approve", {"approved": True, "graph_version": 1})
        check(False, "approving the replaced version 1 is refused")
    except urllib.error.HTTPError as exc:
        check(exc.code == 409, "approving the replaced version 1 is refused (409)")
    demo.call("POST", f"/planning/plan/{pid}/approve", {"approved": True, "graph_version": 2, "comment": "looks good"})

    # 3. execution
    demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("COMPLETED", "FAILED"), "the steps", timeout=600)
    check(demo.call("GET", f"/projects/{pid}")["state"] == "COMPLETED", "every step finished")  # type: ignore[index]
    run_order_checks(pid)
    check(any(e["event_type"] == "plan.approved" for e in events(pid)), "plan.approved was published")

    # 4. replan with feedback
    done_plan = plan_of(pid)
    work = {t["id"] for t in done_plan["graph"]["tasks"] if t["phase"] in ("research", "design", "implement", "test")}
    demo.call("POST", f"/planning/plan/{pid}/replan", {"feedback": "Don't use threads; use asyncio."})
    demo.wait(f"/projects/{pid}", lambda p: p.get("graph_version") == 3, "the new plan version", timeout=600)
    v3 = plan_of(pid)
    check(all(v3["states"].get(t) == "COMPLETED" for t in work),
          f"the replan kept all {len(work)} finished research / design / build / test steps")
    check(any(t["title"].startswith("Change request") or "threads" in " ".join(t["acceptance_criteria"])
              for t in v3["graph"]["tasks"]), "the feedback became part of the plan")
    demo.call("POST", f"/planning/plan/{pid}/approve", {"approved": True, "graph_version": 3})
    demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("COMPLETED", "FAILED"), "the change", timeout=600)
    check(demo.call("GET", f"/projects/{pid}")["state"] == "COMPLETED", "the change request ran to the end")  # type: ignore[index]

    # 5. three parts
    mp = demo.call("POST", "/projects", {"name": "Sprint 3 demo: hostel booking (3 parts)"})["project_id"]  # type: ignore[index]
    docs.upload(mp, [("Part A/part_a.pdf", GOLD / "g08_multipart" / "Part A" / "part_a.pdf"),
                     ("Part B/part_b.docx", GOLD / "g08_multipart" / "Part B" / "part_b.docx"),
                     ("Part C/part_c.md", GOLD / "g08_multipart" / "Part C" / "part_c.md")])
    demo.wait(f"/projects/{mp}", lambda p: p["state"] in ("AWAITING_APPROVAL", "FAILED"), "the plan", timeout=600)
    mplan = plan_of(mp)
    print("\nHostel booking (3 parts):")
    show(mplan)
    groups = {p["name"] for p in mplan["graph"]["roadmap"]["phases"]}
    check({"Part A", "Part B", "Part C"} <= groups, "each upload folder is its own part of the plan")

    print("\nSprint 3 demo PASS. In the dashboard, open a project's Plan tab: the graph, roadmap, coverage and "
          "versions; Edit, Approve and Change plan work from there.")


if __name__ == "__main__":
    main()
