#!/usr/bin/env python3
"""End-to-end golden scenarios (Member 10, Sprint 10 items 10.15-10.17), all over the API.

1. ``tcp``    — "TCP chat app" (guide §32): the assignment PDF -> requirements -> plan (auto-approved) -> research ->
   verify -> code -> test (-> Member 8's fix loop) -> docs -> final review; failures go back to the step that caused
   them and the review runs again until PASS, or a person is asked with the reason.
2. ``essay``  — a non-code report assignment: research -> verify -> outline -> sections -> document -> review.
3. ``change`` — the TCP chat again, with a person's change request while it runs ("do not use asyncio") -> Member 3's
   replan from that point; finished steps are kept (same task, not run again) and the review checks the request.

Every scenario checks that no capability is served by a stub, that each stage really ran, and reports the review
rounds (verdicts, failures with the responsible step, what was re-run, the stop reason). Exits non-zero on a failed
check. Talks to a running API (default http://127.0.0.1:8772; ``demo_final.sh`` starts one).

    python scripts/demo_final.py [API] [--only tcp,essay,change] [--json out.json]
"""

import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait
import demo_sprint_2 as docs  # upload + check helpers

ROOT = Path(__file__).resolve().parents[1]
TCP_PDF = ROOT / "samples" / "demo" / "tcp_chat_assignment.pdf"
ESSAY = ROOT / "samples" / "review" / "e2e" / "essay" / "assignment.md"
SETTLED = ("COMPLETED", "FAILED", "CANCELLED", "REVIEWING")
TIMEOUT = float(os.environ.get("DEMO_FINAL_TIMEOUT_S", "2400"))
check = docs.check
CHANGE = "Do not use asyncio; use one thread per client instead."


def tasks_of(pid: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = demo.call("GET", f"/projects/{pid}/tasks")  # type: ignore[assignment]
    return sorted(out, key=lambda t: str(t.get("created_at")))


def rounds_of(pid: str) -> dict[str, Any]:
    return demo.call("GET", f"/review/reports/{pid}")  # type: ignore[return-value]


def settle(pid: str, what: str) -> dict[str, Any]:
    return demo.wait(f"/projects/{pid}", lambda p: p["state"] in SETTLED, what, timeout=TIMEOUT)


def describe(pid: str) -> dict[str, Any]:
    """What ran, and every review round."""
    tasks = tasks_of(pid)
    caps: dict[str, list[str]] = {}
    for t in tasks:
        caps.setdefault(t["capability"], []).append(t["state"])
    body = rounds_of(pid)
    rounds = []
    for r in body["rounds"]:
        detail = demo.call("GET", f"/review/reports/{pid}/{r['task_id']}") if r.get("recommendation") else {}
        items = {i["item"]["id"]: i["verdict"] for i in (detail or {}).get("items", [])}  # type: ignore[union-attr]
        fails = [(f["requirement_id"], f["category"], f["responsible_task_id"])
                 for f in (detail or {}).get("report", {}).get("failures", [])]  # type: ignore[union-attr]
        rounds.append({"round": r["round"], "recommendation": r["recommendation"], "completeness": r["completeness"],
                       "failures": fails, "items": items, "stop_reason": r["stop_reason"],
                       "created": [(t["action"], t["capability"]) for t in r["created_tasks"]],
                       "stale_of": r.get("stale_of")})
    return {"project_state": body["project_state"], "capabilities": caps, "rounds": rounds,
            "tasks": len(tasks)}


def show(name: str, d: dict[str, Any], seconds: float) -> None:
    print(f"\n== {name}: project {d['project_state']} after {seconds:.0f} s, {d['tasks']} tasks")
    print("   ran: " + ", ".join(f"{c} x{len(s)}" for c, s in sorted(d["capabilities"].items())))
    for r in d["rounds"]:
        judged = {k: v for k, v in r["items"].items() if not k.startswith("E")}   # E*: marked, not passed
        n = len(judged)
        ok = sum(1 for v in judged.values() if v == "PASS")
        print(f"   review round {r['round']}: {r['recommendation']} ({ok}/{n} PASS, completeness "
              f"{r['completeness']})" + (" [re-check: the work changed]" if r["stale_of"] else ""))
        for rid, cat, task in r["failures"][:8]:
            print(f"     - {rid} {cat} -> {task or 'no step (replan)'}")
        if r["created"]:
            print("     next: " + ", ".join(f"{a} {c}" for a, c in r["created"]))
        if r["stop_reason"]:
            print(f"     stopped: {r['stop_reason']}")


PIPELINE = ("document.extract", "plan.generate", "research.run", "verify.claims", "code.implement", "test.run",
            "docs.generate", "review.final")


def no_stubs() -> None:
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    stubs = sorted(c for c in PIPELINE if caps.get(c) != "real")
    check(not stubs, f"every pipeline capability is served by a real agent ({len(PIPELINE)}; not real: "
                     f"{stubs or 'none'})")
    flagged = sorted(c for c, s in caps.items() if s == "stub" and c not in PIPELINE)
    if flagged:
        print(f"  (flagged stubs outside the pipeline: {', '.join(flagged)})")


def final_checks(d: dict[str, Any], stages: tuple[str, ...]) -> None:
    for cap in stages:
        check(any(s == "COMPLETED" for s in d["capabilities"].get(cap, [])), f"{cap} ran and completed")
    check(bool(d["rounds"]) and d["rounds"][-1]["recommendation"] is not None, "the final review ran")
    last = d["rounds"][-1]
    if d["project_state"] == "COMPLETED":
        check(last["recommendation"] == "PASS", "the project completed after a PASS review")
    else:
        check(d["project_state"] == "REVIEWING" and bool(last["stop_reason"]),
              f"the review asks a person, with the reason ({last['stop_reason']})")
    revised = [r for r in d["rounds"] if r["created"]]
    for r in revised:
        check(all(a in ("revise", "rerun", "replan", "review") for a, _ in r["created"]),
              f"round {r['round']}: only targeted revisions / re-runs were created")


def scenario_tcp() -> dict[str, Any]:
    pid = demo.call("POST", "/projects", {"name": "Final: TCP chat", "auto_approve": True})["project_id"]  # type: ignore
    t0 = time.time()
    docs.upload(pid, [("tcp_chat_assignment.pdf", TCP_PDF)])
    settle(pid, "the TCP chat project")
    d = describe(pid)
    show("Scenario 1: TCP chat (PDF -> ... -> review)", d, time.time() - t0)
    final_checks(d, ("document.extract", "plan.generate", "code.implement", "test.run", "docs.generate",
                     "review.final"))
    d["revision_happened"] = any(r["created"] for r in d["rounds"]) or "code.revise" in d["capabilities"]
    print(f"   a failure was found and fixed by a revision: {'yes' if d['revision_happened'] else 'no'}")
    return {"project_id": pid, **d}


def scenario_essay() -> dict[str, Any]:
    body = {"name": "Final: concurrency report", "auto_approve": True}
    pid = demo.call("POST", "/projects", body)["project_id"]  # type: ignore[index]
    t0 = time.time()
    docs.upload(pid, [("assignment.md", ESSAY)])
    settle(pid, "the report project")
    d = describe(pid)
    show("Scenario 2: report assignment (no code)", d, time.time() - t0)
    final_checks(d, ("document.extract", "plan.generate", "research.run", "verify.claims", "docs.generate",
                     "review.final"))
    check("code.implement" not in d["capabilities"], "no coding step in a report project")
    return {"project_id": pid, **d}


def scenario_change() -> dict[str, Any]:
    body = {"name": "Final: TCP chat + change request", "auto_approve": True}
    pid = demo.call("POST", "/projects", body)["project_id"]  # type: ignore[index]
    t0 = time.time()
    docs.upload(pid, [("tcp_chat_assignment.pdf", TCP_PDF)])
    demo.wait(f"/projects/{pid}/tasks", lambda ts: any(t["capability"] == "code.implement" and t["state"] in
                                                       ("RUNNING", "COMPLETED") for t in ts),
              "the first coding step", timeout=TIMEOUT)
    before = {t["task_id"]: t for t in tasks_of(pid) if t.get("plan_task_id") and t["state"] == "COMPLETED"}
    r = demo.call("POST", f"/planning/plan/{pid}/replan", {"feedback": CHANGE})
    print(f"\n   change request sent while coding ran ({len(before)} step(s) finished): {CHANGE!r} -> {r}")
    settle(pid, "the changed project")
    after = {t["task_id"]: t for t in tasks_of(pid)}
    d = describe(pid)
    show("Scenario 3: change request mid-run", d, time.time() - t0)
    check(any(t["capability"] == "plan.replan" and t["state"] == "COMPLETED" for t in after.values()),
          "the change request was planned in (plan.replan)")
    kept = [tid for tid in before if tid in after and not after[tid].get("replaced")
            and after[tid]["state"] == "COMPLETED"]
    check(len(kept) == len(before), f"finished steps are kept, not run again ({len(kept)}/{len(before)})")
    last = d["rounds"][-1] if d["rounds"] else {"items": {}}
    check(any(k.startswith("H") for k in last["items"]), "the final review checks the change request")
    final_checks(d, ("code.implement", "test.run", "review.final"))
    return {"project_id": pid, "kept": len(kept), **d}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--only=")), "tcp,essay,change")
    out = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--json=")), None)
    demo.API = (args[0] if args else "http://127.0.0.1:8772").rstrip("/") + "/api"
    for _ in range(240):
        try:
            demo.call("GET", "/health")
            break
        except OSError:
            time.sleep(0.5)
    demo.sign_up("Final demo", f"final-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    no_stubs()
    results: dict[str, Any] = {}
    runs = {"tcp": scenario_tcp, "essay": scenario_essay, "change": scenario_change}
    for name in only.split(","):
        results[name] = runs[name.strip()]()
    if out:
        Path(out).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print("\nFinal demo OK: " + ", ".join(f"{k} -> {v['project_state']}" for k, v in results.items()))


if __name__ == "__main__":
    main()
