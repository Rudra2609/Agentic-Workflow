#!/usr/bin/env python3
"""Failure-injection rounds against the running `make demo` stack (see demo_chaos.sh). Each round:

1. a research step that stays busy for a while (``stub_delay_s``: the platform's failure-injection hook);
2. as soon as it RUNS, ``kill -9`` the agents process (no goodbye: a crash);
3. the Manager notices the agent's lease expired, abandons that execution and schedules a retry;
4. a new agents process starts; the step runs again as a NEW execution on a new agent and completes; nothing is
   dead-lettered. (Started at once instead, the new agents would get the broker's redelivery of the unfinished
   assignment and finish the same execution: also a recovery, but not the lease-expiry path this shows.)
"""

import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait

STATE = Path(os.environ.get("HMAP_DEMO_STATE", Path(__file__).resolve().parents[1] / "data" / "demo"))
QUESTION = "How does the asyncio event loop handle many network connections?"   # recorded (Sprint 5 demo)


def kill_agents() -> int:
    pid = int((STATE / "agents.pid").read_text())
    subprocess.run(["pkill", "-KILL", "-P", str(pid)], check=False)
    os.kill(pid, signal.SIGKILL)
    subprocess.run(["pkill", "-KILL", "-f", "hmap-agents run --all"], check=False)
    return pid


def one_round(n: int) -> bool:
    print(f"\n--- round {n}")
    pid = demo.call("POST", "/projects", {"name": f"Chaos round {n}"})["project_id"]  # type: ignore[index]
    task = demo.call("POST", f"/projects/{pid}/tasks", {
        "capability": "research.run", "objective": f"Research: {QUESTION}",
        "inputs": {"research_questions": [QUESTION], "stub_delay_s": 6}})
    tid = task["task_id"]  # type: ignore[index]
    t = demo.wait(f"/tasks/{tid}", lambda t: t["state"] == "RUNNING", "the research step to start", timeout=120)
    first = t["executions"][-1]
    t0 = time.time()
    old = kill_agents()
    print(f"    killed the agents process {old} while execution {first['execution_id'][-8:]} ran on "
          f"{first['agent_id']}")
    print("    waiting for the Manager to notice (heartbeats stop -> lease expires -> execution abandoned)...")
    gone = demo.wait(f"/tasks/{tid}", lambda t: t["executions"][0]["status"] not in ("ACTIVE", "PENDING")
                     or len(t["executions"]) > 1, "the lease to expire", timeout=180)
    print(f"    after {time.time() - t0:.0f} s: execution #1 {gone['executions'][0]['status'].lower()}, step "
          f"{gone['state'].lower()}; starting a new agents process")
    subprocess.run(["bash", "-c", "restart_agents"], check=True)
    done = demo.wait(f"/tasks/{tid}", lambda t: t["state"] in ("COMPLETED", "FAILED", "DEAD_LETTERED"),
                     "the step to recover", timeout=240)
    exes = done["executions"]
    last = exes[-1]
    print(f"    {len(exes)} executions: " + ", ".join(f"#{e['attempt']} {e['status'].lower()} on {e['agent_id']}"
                                                   for e in exes) + f"; recovered in {time.time() - t0:.0f} s")
    ok = (done["state"] == "COMPLETED" and len(exes) >= 2 and last["status"] == "SUCCEEDED"
          and last["agent_id"] != first["agent_id"] and last["execution_id"] != first["execution_id"])
    dead = demo.call("GET", "/dead-letters")
    print(f"    {'OK' if ok else 'FAIL'}: retried as a new execution on a new agent; dead letters now: "
          f"{len(dead) if isinstance(dead, list) else dead}")
    return ok


def main() -> None:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    demo.API = "http://127.0.0.1:8000/api"
    demo.sign_up("Chaos demo", f"chaos-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    results = [one_round(n) for n in range(1, rounds + 1)]
    passed = sum(results)
    print(f"\nCHAOS: {passed}/{rounds} rounds recovered. Operations page: http://127.0.0.1:3000/features/ops "
          f"(why a step failed, dead letters); traces in Jaeger when `make obs-up` runs.")
    raise SystemExit(0 if passed == rounds else 1)


if __name__ == "__main__":
    main()
