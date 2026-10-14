#!/usr/bin/env python3
"""Sprint 4 demo (Member 4: self-reflection & refinement + observability), all over the API.

1. "Check and improve results" on: the TCP chat PDF -> the requirements and the plan are each critiqued (code checks
   first, then the judge model) and stop at once: nothing to fix. Timelines printed.
2. The messy weather-dashboard brief, checked: the requirements improve (score up, a priority fixed), the improved
   version is what the planner uses; timeline, issues by category and the diff of the revision printed.
3. Operations: a step that keeps failing ends in the dead-letter queue; "why did this task fail?" explains it; the
   metrics show the dead letter (the HmapDeadLetter alert's condition); an operator replays it as a NEW attempt and it
   finishes. With DEMO_OBS=1 (``make obs-up`` first) it also checks the trace in Jaeger and the firing alert in
   Prometheus.

Talks to a running API (default http://127.0.0.1:8767; demo_sprint_4.sh starts one). Exits non-zero if a check fails.
"""

import json
import os
import secrets
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait
import demo_sprint_2 as docs  # upload + check helpers

GOLD = Path(__file__).resolve().parents[1] / "samples" / "doc_intel" / "gold" / "docs"
check = docs.check
OBS = os.environ.get("DEMO_OBS") == "1"


def runs(pid: str) -> list[dict]:
    return demo.call("GET", f"/refine/runs/{pid}")  # type: ignore[return-value]


def timeline(pid: str, summary: dict) -> dict:
    run = demo.call("GET", f"/refine/runs/{pid}/{summary['run_id']}")
    label = {"document.extract": "Requirements", "plan.generate": "Plan"}.get(summary["capability"], summary["subject"])
    print(f"    {label}: {summary['base_score']:.2f} -> {summary['best_score']:.2f}, "
          f"{len(run['iterations']) - 1} round(s), stopped: {run['stop_reason']}, "  # type: ignore[index]
          f"{'improved version used' if run['applied'] else 'original kept'} "  # type: ignore[index]
          f"({run['tokens']} tokens, {run['model_calls']} model calls)")  # type: ignore[index]
    for it in run["iterations"]:  # type: ignore[index]
        cats = ", ".join(f"{c} x{n}" for c, n in sorted(it["issues_by_category"].items())) or "no problems"
        critics = " ".join(f"{c['critic']}={c['score']:.2f}" for c in it["critics"])
        how = f" [{it['strategy']}]" if it["strategy"] else ""
        print(f"      {'original' if it['index'] == 0 else 'revision ' + str(it['index']):11s}{how} "
              f"score {it['score']:.2f}  {cats}  ({critics})")
        for issue in it["critique"]["issues"][:4]:
            print(f"          - [{issue['severity']} {issue['category']}] {issue.get('location') or ''}: "
                  f"{issue['description'][:90]}")
        if it.get("reflection"):
            print(f"          reflection: {it['reflection'][:110]}")
    return run  # type: ignore[return-value]


def events(pid: str) -> list[dict]:
    return demo.call("GET", f"/events?project_id={pid}&limit=2000")  # type: ignore[return-value]


def checked_project(name: str, files: list[tuple[str, Path]]) -> str:
    pid = demo.call("POST", "/projects", {"name": name, "refine": True})["project_id"]  # type: ignore[index]
    docs.upload(pid, files)
    demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("AWAITING_APPROVAL", "FAILED"), "the plan", timeout=600)
    demo.wait(f"/refine/runs/{pid}", lambda rs: len(rs) == 2 and all(r["status"] == "stopped" for r in rs),
              "both checks", timeout=120)
    return pid


def jaeger_trace(trace_id: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:16686/api/traces/{trace_id}", timeout=10) as r:
        return json.loads(r.read())


def prometheus_alerts() -> list[dict]:
    with urllib.request.urlopen("http://127.0.0.1:9090/api/v1/alerts", timeout=10) as r:
        return json.loads(r.read())["data"]["alerts"]


def main() -> None:
    root = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8767").rstrip("/")
    demo.API = root + "/api"
    for _ in range(120):
        try:
            demo.call("GET", "/health")
            break
        except OSError:
            time.sleep(0.5)
    demo.sign_up("Sprint 4 demo", f"sprint4-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    check(caps.get("refine.run") == "real", "refine.run is served by the refine agent")
    policy = demo.call("GET", "/refine/policy")["default"]  # type: ignore[index]
    print(f"    stop policy: {policy}")

    # 1. TCP chat, checked
    print("\n1. TCP chat assignment with 'Check and improve results' on")
    pid = checked_project("Sprint 4 demo: TCP chat (checked)", [("tcp_chat_assignment.pdf",
                                                                 GOLD / "g01_tcp_chat" / "tcp_chat_assignment.pdf")])
    for s in sorted(runs(pid), key=lambda r: r["capability"]):
        timeline(pid, s)
    stopped = [e for e in events(pid) if e["event_type"] == "refine.stopped"]
    check(len(stopped) == 2, "refine.stopped events for the requirements and the plan (refine.iteration while "
                             "running)")
    check(demo.call("GET", f"/projects/{pid}")["state"] == "AWAITING_APPROVAL",  # type: ignore[index]
          "the checked plan waits for approval as usual")

    # 2. messy brief: the check improves the requirements
    print("\n2. Messy weather-dashboard brief, checked")
    mpid = checked_project("Sprint 4 demo: weather dashboard (checked)",
                           [("weather_dashboard.pdf", GOLD / "g07_messy" / "weather_dashboard.pdf")])
    by_cap = {r["capability"]: r for r in runs(mpid)}
    ex = by_cap["document.extract"]
    run = timeline(mpid, ex)
    timeline(mpid, by_cap["plan.generate"])
    check(ex["applied"] and ex["best_score"] > ex["base_score"],
          f"the requirements improved ({ex['base_score']:.2f} -> {ex['best_score']:.2f}) and the improved version "
          "is used")
    diff = demo.call("GET", f"/refine/runs/{mpid}/{ex['run_id']}/diff?a=0&b={run['best_iteration']}")
    for c in diff["changes"]:  # type: ignore[index]
        print(f"      changed {c['path']}: {json.dumps(c['before'])[:60]} -> {json.dumps(c['after'])[:60]}")
    check(bool(diff["changes"]), "the revision's diff shows exactly what changed")  # type: ignore[index]
    rs = demo.call("GET", f"/doc_intel/requirements/{mpid}")
    check(rs["artifact"]["version"] == 2, "the improved requirements are version 2 of Member 2's artifact "  # type: ignore[index]
          "(version 1 kept)")

    # 3. operations: dead letter -> why -> metrics -> replay as a new attempt
    print("\n3. Operations: a step that keeps failing")
    opid = demo.call("POST", "/projects", {"name": "Sprint 4 demo: operations"})["project_id"]  # type: ignore[index]
    tid = demo.call("POST", f"/projects/{opid}/tasks", {"capability": "research.run", "objective": "Fetch the sources",
                                                       "inputs": {"stub_fail": "TOOL_TRANSIENT",
                                                                  "stub_fail_times": 4}})["task_id"]  # type: ignore[index]
    demo.wait(f"/tasks/{tid}", lambda t: t["state"] == "DEAD_LETTERED", "the dead letter", timeout=120)
    why = demo.call("GET", f"/ops/explain/{tid}")
    print(f"    why: {why['verdict']['headline']}")  # type: ignore[index]
    for f in why["verdict"]["facts"]:  # type: ignore[index]
        print(f"      - {f}")
    check(why["verdict"]["status"] == "dead_lettered" and why["verdict"]["cause"] == "TOOL_TRANSIENT",  # type: ignore[index]
          "'why did this task fail?' names the cause and the attempts")
    dlq = demo.call("GET", "/ops/dlq")
    check(any(t["task_id"] == tid for t in dlq["tasks"]), "it is listed in the dead-letter queue")  # type: ignore[index]
    deadline, dead = time.time() + 15, 0.0
    while dead < 1 and time.time() < deadline:
        with urllib.request.urlopen(root + "/metrics", timeout=10) as r:
            line = next((ln for ln in r.read().decode().splitlines() if ln.startswith("hmap_dead_lettered_tasks ")), "")
        dead = float(line.split()[-1]) if line else 0.0
        time.sleep(0.5)
    check(dead >= 1, f"/metrics: hmap_dead_lettered_tasks = {dead:g} (the HmapDeadLetter alert's condition)")
    if OBS:
        deadline = time.time() + 60
        firing: list[dict] = []
        while time.time() < deadline and not firing:
            firing = [a for a in prometheus_alerts() if a["labels"]["alertname"] == "HmapDeadLetter"
                      and a["state"] == "firing"]
            time.sleep(2)
        check(bool(firing), "Prometheus: the HmapDeadLetter alert is firing")
    before = len(demo.call("GET", f"/tasks/{tid}")["executions"])  # type: ignore[index]
    out = demo.call("POST", f"/ops/replay/{tid}", {"reason": "the source site is back (demo)"})
    task = demo.wait(f"/tasks/{tid}", lambda t: t["state"] in ("COMPLETED", "DEAD_LETTERED", "FAILED"),
                     "the new attempt", timeout=60)
    check(out["replay"] == 1 and task["state"] == "COMPLETED" and len(task["executions"]) == before + 1,  # type: ignore[index]
          f"the replay ran as a NEW attempt (execution {len(task['executions'])}) and finished")
    replayed = [e for e in events(opid) if e["event_type"] == "task.replayed"]
    check(bool(replayed) and replayed[0]["data"]["reason"].startswith("the source site"),
          "task.replayed records who replayed it and why")
    if OBS:
        trace_id = why["trace"]["trace_ids"][0]  # type: ignore[index]
        time.sleep(3)                                            # the batch exporter sends every second
        spans = [s for d in jaeger_trace(trace_id)["data"] for s in d["spans"]]
        names = {s["operationName"] for s in spans}
        print(f"    Jaeger trace {trace_id}: {len(spans)} spans: {sorted(names)[:8]}")
        check(any(n.startswith("manager.assign") for n in names) and any(n.startswith("agent.handle") for n in names),
              "Jaeger shows the task's trace: Manager -> bus -> agent (http://127.0.0.1:16686/trace/" + trace_id + ")")
        ext = next(t for t in demo.call("GET", f"/projects/{mpid}/tasks") if t["capability"] == "document.extract")  # type: ignore[union-attr]
        ext_why = demo.call("GET", f"/ops/explain/{ext['task_id']}")
        ex_spans = [s for d in jaeger_trace(ext_why["trace"]["trace_ids"][0])["data"] for s in d["spans"]]  # type: ignore[index]
        ex_names = {s["operationName"] for s in ex_spans}
        check(any(n.startswith("chat ") for n in ex_names) and any(n.startswith("refine") for n in ex_names),
              f"the checked extraction's trace includes the model calls and the refinement loop ({len(ex_spans)} "
              "spans)")

    print("\nSprint 4 demo PASS. In the dashboard: a project's Refinement tab shows each check's rounds, problems by "
          "kind, the score curve and what changed; the Operations page explains failures and replays dead letters.")


if __name__ == "__main__":
    main()
