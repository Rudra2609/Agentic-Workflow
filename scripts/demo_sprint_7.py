#!/usr/bin/env python3
"""Sprint 7 demo (Member 7: autonomous coding), all over the API, offline (recorded answers).

1. TCP chat assignment: requirements -> plan -> a person approves -> research + verification -> the **design** step
   (``code.implement``) starts from an empty folder, picks the TCP server/client template and adapts it -> each
   **implementation** step changes the project's code (the workspace head) -> checks run in the jailed runner ->
   ``code.completed`` events -> the rest of the plan (stubs) -> project complete;
2. "Request changes" on an implementation step -> a ``code.revise`` step starting from the project's current code
   -> its own diff, checks pass;
3. the diff, the tool-call log and the code are in the project's Coding tab.

Talks to a running API (default http://127.0.0.1:8769; demo_sprint_7.sh starts one). Exits non-zero if a check fails.
"""

import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait
import demo_sprint_2 as docs  # upload + check helpers

DEMO = Path(__file__).resolve().parents[1] / "samples" / "demo"
check = docs.check
DONE = ("COMPLETED", "FAILED", "DEAD_LETTERED", "CANCELLED")
CODE = ("code.implement", "code.revise")


def show_run(pid: str, task_id: str) -> dict:
    d = demo.call("GET", f"/coding/runs/{pid}/{task_id}")
    s = d["summary"]  # type: ignore[index]
    checks = ", ".join(f"{k} {v}" for k, v in s["checks"].items())
    print(f"    [{s['outcome'] or s['status']:>8s}] {s['capability']} {task_id[-6:]}: {s['objective'][:80]}")
    print(f"             {len(s['files_changed'])} file(s) changed {s['files_changed'][:4]}; checks: {checks}; "
          f"{s['model_calls']} model calls, {s['tokens']} tokens; stop: {s['stop_reason']}"
          + (f"; template {s['template']}" if s["template"] else ""))
    return d  # type: ignore[return-value]


def main() -> None:
    root = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8769").rstrip("/")
    demo.API = root + "/api"
    for _ in range(120):
        try:
            demo.call("GET", "/health")
            break
        except OSError:
            time.sleep(0.5)
    if os.environ.get("HMAP_DEMO_EMAIL") and os.environ.get("HMAP_DEMO_PASSWORD"):
        demo.call("POST", "/auth/login", {"email": os.environ["HMAP_DEMO_EMAIL"],
                                          "password": os.environ["HMAP_DEMO_PASSWORD"]})
    else:
        demo.sign_up("Sprint 7 demo", f"sprint7-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    for cap in ("document.extract", "plan.generate", "research.run", "verify.claims", "code.implement"):
        check(caps.get(cap) == "real", f"{cap} is served by a real agent")

    print("\n1. TCP chat assignment: plan -> approve -> research -> verify -> design + implementation (coding agent)")
    pid = demo.call("POST", "/projects", {"name": "Sprint 7 demo: TCP chat"})["project_id"]  # type: ignore[index]
    docs.upload(pid, [("tcp_chat_assignment.pdf", DEMO / "tcp_chat_assignment.pdf")])
    project = demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("AWAITING_APPROVAL", "FAILED"), "the plan",
                        timeout=600)
    check(project["state"] == "AWAITING_APPROVAL", "the plan waits for a person")
    plan = demo.call("GET", f"/planning/plan/{pid}")
    demo.call("POST", f"/planning/plan/{pid}/approve", {"approved": True,
                                                         "graph_version": plan["graph"]["version"]})  # type: ignore[index]
    final = demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("COMPLETED", "FAILED"), "the whole plan",
                      timeout=1200)
    check(final["state"] == "COMPLETED", "project complete (coding steps real, test/docs/review still stubs)")
    tasks = demo.call("GET", f"/projects/{pid}/tasks")
    code_tasks = [t for t in tasks if t["capability"] in CODE]  # type: ignore[union-attr]
    check(len(code_tasks) >= 2, f"{len(code_tasks)} coding steps ran (design + implementation)")
    check(all(t["state"] == "COMPLETED" for t in code_tasks), "every coding step completed")
    runs = {r["task_id"]: r for r in demo.call("GET", f"/coding/runs/{pid}")}  # type: ignore[union-attr]
    details = [show_run(pid, t["task_id"]) for t in sorted(code_tasks, key=lambda t: runs[t["task_id"]]["updated_at"])]
    design = details[0]["summary"]
    check(design["template"] == "tcp_server_client", "the design step started from the TCP server/client template")
    check(all(d["summary"]["checks"].get("compile") == "passed" for d in details), "every step's code compiles")
    head = demo.call("GET", f"/coding/heads/{pid}")
    files = {f["path"] for f in head["files"]}  # type: ignore[index]
    check({"server.py", "client.py"} <= files, f"the project's code (head v{head['version']}): {sorted(files)}")
    events = demo.call("GET", f"/events?project_id={pid}&limit=2000")
    done = [e for e in events if e["event_type"] == "code.completed"]  # type: ignore[union-attr]
    check(len(done) == len(code_tasks), f"code.completed published for every coding step ({len(done)})")
    log = details[-1]["trace"]
    print(f"    last step's tool calls: {len(log['steps'])} model calls, {len(log['edits'])} edits "
          f"({sum(not e['ok'] for e in log['edits'])} refused), {len(log['commands'])} commands")

    print("\n2. Request changes -> code.revise (starts from the project's current code)")
    target = next(d for d in reversed(details) if d["summary"]["capability"] == "code.implement")
    tid = target["summary"]["task_id"]
    r = demo.call("POST", f"/coding/runs/{pid}/{tid}/revise",
                  {"required_changes": ["Add a /who command: the server replies only to the sender with 'online: ' "
                                        "followed by the connected client names, sorted and comma-separated; the "
                                        "/who line itself is not broadcast"]})
    rev = demo.wait(f"/tasks/{r['task_id']}", lambda t: t["state"] in DONE, "the revision", timeout=600)  # type: ignore
    check(rev["state"] == "COMPLETED", "the revision step completed")
    rd = show_run(pid, rev["task_id"])
    check(rd["summary"]["revision_round"] == 1 and rd["trace"]["base"] == "head",
          "revision round 1, started from the project head")
    check("server.py" in rd["summary"]["files_changed"], "the revision changed server.py")
    print("    its diff:")
    for line in rd["diff"].splitlines()[:24]:
        print(f"      {line}")
    server = demo.call("GET", f"/coding/runs/{pid}/{rev['task_id']}/files?path=server.py")["text"]  # type: ignore
    check("/who" in server, "the revised code handles /who")
    check(demo.call("GET", f"/coding/heads/{pid}")["version"] > head["version"], "the project head moved")  # type: ignore

    web = os.environ.get("HMAP_PUBLIC_URL", "http://localhost:3000")
    print(f"\nSprint 7 demo PASS. In the dashboard ({web}/projects/{pid}): the Coding tab shows every coding step's "
          "tool-call log, the diff, the command output, and a 'Request changes' box.")


if __name__ == "__main__":
    main()
