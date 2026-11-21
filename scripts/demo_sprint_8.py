#!/usr/bin/env python3
"""Sprint 8 demo (Member 8: automated testing & execution), all over the API, offline (recorded answers).

The spec's full-loop scenario: the coding agent writes a TCP chat server; the test step runs it in the sandbox
with the assignment's multi-client acceptance test; the test fails (the server misses ``/who``); the failures go
back to the coding agent as a ``code.revise``; the code is tested again and passes.

1. ``code.implement`` (greenfield: TCP chat server) -> ``test.run`` (depends on it, with the acceptance test)
2. the first test run fails in the integration stage, with category, file/line and a hint per failure
3. the loop: ``code.revise`` (parent = the coding step) + a new ``test.run``, at most 2 rounds -> the last re-test
   passes -> the loop stops
4. ``test.completed`` events, the Testing tab's API (stage timeline, loop rounds, the full log)

Talks to a running API (default http://127.0.0.1:8770; demo_sprint_8.sh starts one). Exits non-zero if a check fails.
"""

import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait
import demo_sprint_2 as docs  # check helper

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "samples" / "testing" / "demo" / "test_chat_integration.py"
check = docs.check
DONE = ("COMPLETED", "FAILED", "DEAD_LETTERED", "CANCELLED")

OBJECTIVE = ("Write a multi-client TCP chat server in server.py, started as `python server.py --port <port>` and "
             "listening on 127.0.0.1. Clients are named client1, client2, ... in the order they connect. Every line a "
             "client sends goes to every OTHER connected client as '<name>: <text>'. Use one thread per client.")
CRITERIA = ["`python server.py --port <port>` listens on 127.0.0.1:<port> and serves many clients at once",
            "clients are named client1, client2, ... in connection order",
            "each line is sent to every other client as '<name>: <text>' (not back to the sender)"]
TEST_CRITERIA = [*CRITERIA, ("'/who' is answered only to the sender with 'online: ' and the client names, sorted "
                             "and joined with ', '; it is not broadcast")]


def show(pid: str, task_id: str) -> dict:
    d = demo.call("GET", f"/testing/runs/{pid}/{task_id}")
    s = d["summary"]  # type: ignore[index]
    stages = " ".join(f"{k}:{v}" for k, v in s["stages"].items())
    print(f"    [{'PASSED' if s['passed'] else 'FAILED':>6s}] round {s['loop_round']} ({s['backend']}): "
          f"{s['tests'] - s['tests_failed']}/{s['tests']} tests; {stages}")
    for f in d["trace"]["failures"][:4]:  # type: ignore[index]
        where = f"{f['file']}:{f['line']}" if f["file"] and f["line"] else (f["test"] or f["stage"])
        print(f"             {f['category']:9s} {where}: {f['message'][:90]}")
        if f["hint"]:
            print(f"               hint ({f['hint_by']}): {f['hint'][:110]}")
    return d  # type: ignore[return-value]


def main() -> None:
    root = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8770").rstrip("/")
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
        demo.sign_up("Sprint 8 demo", f"sprint8-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    for cap in ("code.implement", "code.revise", "test.run"):
        check(caps.get(cap) == "real", f"{cap} is served by a real agent")

    print("\n1. Coding step (TCP chat server) -> test step with the assignment's multi-client acceptance test")
    pid = demo.call("POST", "/projects", {"name": "Sprint 8 demo: TCP chat tests"})["project_id"]  # type: ignore[index]
    code = demo.call("POST", f"/projects/{pid}/tasks", {"capability": "code.implement", "objective": OBJECTIVE,
                                                        "acceptance_criteria": CRITERIA})
    test = demo.call("POST", f"/projects/{pid}/tasks", {
        "capability": "test.run", "objective": "Test the TCP chat server with several clients",
        "acceptance_criteria": TEST_CRITERIA, "depends_on": [code["task_id"]],  # type: ignore[index]
        "inputs": {"tests": {"tests/acceptance/test_chat_integration.py": ACCEPTANCE.read_text(encoding="utf-8")}}})
    first = demo.wait(f"/tasks/{test['task_id']}", lambda t: t["state"] in DONE, "the first test run",  # type: ignore
                      timeout=900)
    check(first["state"] == "COMPLETED", "the test step completed")
    print("\n2. First test run")
    d1 = show(pid, first["task_id"])
    s1 = d1["summary"]
    check(not s1["passed"], "the first run failed")
    check(s1["stages"].get("integration") == "failed", "the failure is in the integration stage (3 TCP clients)")
    integ = [f for f in d1["trace"]["failures"] if f["stage"] == "integration"]
    check(bool(integ) and all(f["hint"] for f in integ), "every integration failure has a category and a hint")
    check(d1["report"]["passed"] is False and d1["report"]["exec_log_ref"], "TestReport: passed=false + exec log")

    print("\n3. The loop: failures -> code.revise -> test again")

    def settled(tasks: list) -> bool:
        tests = [t for t in tasks if t["capability"] == "test.run"]
        busy = any(t["state"] not in DONE for t in tasks)
        last = max(tests, key=lambda t: ((t.get("inputs") or {}).get("loop") or {}).get("round", 0))
        return not busy and len(tests) > 1 and last["state"] in DONE
    tasks = demo.wait(f"/projects/{pid}/tasks", settled, "the test -> fix -> re-test loop", timeout=1500)
    time.sleep(1.5)                                    # the last hook (no further revision) has run
    tasks = demo.wait(f"/projects/{pid}/tasks", settled, "the loop", timeout=300)
    revise = sorted((t for t in tasks if t["capability"] == "code.revise"), key=lambda t: t["created_at"])
    retests = sorted((t for t in tasks if t["capability"] == "test.run" and (t.get("inputs") or {}).get("loop")),
                     key=lambda t: t["inputs"]["loop"]["round"])
    check(len(revise) >= 1 and all(t["state"] == "COMPLETED" for t in revise),
          f"{len(revise)} code.revise step(s), all completed")
    check(revise[0]["parent_task_id"] == code["task_id"], "the first revision revises the coding step")  # type: ignore
    check([t["inputs"]["loop"]["round"] for t in retests] == list(range(1, len(retests) + 1)),
          f"{len(retests)} re-test round(s), each waiting for its revision")
    for n, (rv, rt) in enumerate(zip(revise, retests, strict=False), 1):
        r = demo.call("GET", f"/coding/runs/{pid}/{rv['task_id']}")
        print(f"\n    fix {n}: the coding agent changed {r['summary']['files_changed']}:")  # type: ignore[index]
        for line in r["diff"].splitlines()[:14]:  # type: ignore[index]
            print(f"      {line}")
        check(rt["depends_on"] == [rv["task_id"]], f"re-test round {n} waited for fix {n}")
        last = show(pid, rt["task_id"])
    check(last["summary"]["passed"], "the last re-test passes: the loop stops")
    check(len(retests) <= 2, "within the round limit (HMAP_TESTING_MAX_ROUNDS=2)")

    print("\n4. Events and the Testing tab")
    events = demo.call("GET", f"/events?project_id={pid}&limit=2000")
    done = [e["data"] for e in events if e["event_type"] == "test.completed"]  # type: ignore[union-attr]
    check(len(done) == len(retests) + 1 and [d["passed"] for d in sorted(done, key=lambda d: d["loop_round"])][-1],
          f"test.completed for every round ({len(done)}), the last one passed")
    loop = demo.call("GET", f"/testing/runs/{pid}/{first['task_id']}")["loop"]
    check([r["loop_round"] for r in loop] == list(range(len(retests) + 1)),  # type: ignore
          "the Testing tab shows every round of the loop")
    with demo.OPENER.open(f"{demo.API}/testing/runs/{pid}/{first['task_id']}/log", timeout=30) as r:
        log = r.read().decode()
    check("=== [integration]" in str(log) and "/work/" not in str(log), "the full log, without sandbox paths")
    backend = d1["summary"]["backend"]
    print(f"    sandbox: {backend}" + ("" if backend == "docker" else " (Docker not running: the local jailed runner)"))

    web = os.environ.get("HMAP_PUBLIC_URL", "http://localhost:3000")
    print(f"\nSprint 8 demo PASS. In the dashboard ({web}/projects/{pid}): the Testing tab shows the stage timeline, "
          "the failures with hints, the test -> fix -> re-test rounds and the full log.")


if __name__ == "__main__":
    main()
