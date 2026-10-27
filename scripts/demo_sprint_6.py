#!/usr/bin/env python3
"""Sprint 6 demo (Member 6: research verification + security), all over the API, offline (recorded answers).

The mid-evaluation storyline (docs/sprints/mid-evaluation.md §1, minutes 1-13 minus the failure injection, which is
scripts/demo_chaos.sh):

1. the three mid-eval inputs (native PDF, scanned PDF, DOCX) are read and their requirements extracted;
2. TCP chat assignment: requirements -> plan -> a person approves -> research -> **verification**: every finding is
   checked (quote in the saved page, quote states the finding, other sources) -> at least one finding is flagged ->
   **follow-up research** on the gap -> **re-check** -> the rest of the plan (stubs) -> project complete;
3. the security layer: every agent registered with a signed message; the policy table; nothing refused.

Talks to a running API (default http://127.0.0.1:8768; demo_sprint_6.sh starts one). Exits non-zero if a check fails.
With ``HMAP_DEMO_EMAIL`` / ``HMAP_DEMO_PASSWORD`` set it signs in to that account instead of creating one, so the
projects appear in the presenter's dashboard (``make demo`` then ``uv run --no-project --python 3.11
scripts/demo_sprint_6.py http://127.0.0.1:8000``).
"""

import os
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait
import demo_sprint_2 as docs  # upload + check helpers

DEMO = Path(__file__).resolve().parents[1] / "samples" / "demo"
check = docs.check
CHIP = {"VERIFIED": "verified", "UNSUPPORTED": "UNSUPPORTED", "CONFLICTING": "CONFLICTING",
        "NEEDS_MORE_RESEARCH": "NEEDS MORE RESEARCH"}
DONE = ("COMPLETED", "FAILED", "DEAD_LETTERED", "CANCELLED")


def show_check(pid: str, task_id: str) -> dict:
    d = demo.call("GET", f"/verify/runs/{pid}/{task_id}")
    s = d["summary"]  # type: ignore[index]
    print(f"    round {s['round']}: {s['claims']} findings -> {s['verified']} verified, {s['unsupported']} unsupported,"
          f" {s['conflicting']} conflicting, {s['needs_more']} need more research "
          f"({s['model_calls']} model calls, {s['seconds']:.1f} s)")
    for c in d["trace"]["claims"]:  # type: ignore[index]
        print(f"      [{CHIP[c['verdict']]:>19s} {round(c['confidence'] * 100):3d}%] {c['claim_id']}: {c['text'][:90]}")
        if c["verdict"] != "VERIFIED":
            print(f"          why: {c['explanation'][:160]}")
    return d  # type: ignore[return-value]


def main() -> None:
    started = datetime.now(UTC).isoformat()
    root = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8768").rstrip("/")
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
        demo.sign_up("Sprint 6 demo", f"sprint6-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    for cap in ("document.extract", "plan.generate", "research.run", "verify.claims"):
        check(caps.get(cap) == "real", f"{cap} is served by a real agent")

    # 1. the three mid-eval inputs
    print("\n1. The mid-evaluation inputs: native PDF, scanned PDF, DOCX")
    for name in ("tcp_chat_assignment.pdf", "lab_manual_scanned.pdf", "requirements.docx"):
        p = demo.call("POST", "/projects", {"name": f"Sprint 6 inputs: {name}"})["project_id"]  # type: ignore[index]
        docs.upload(p, [(name, DEMO / name)])
        demo.wait(f"/projects/{p}/tasks", lambda ts: any(t["capability"] == "document.extract" and t["state"] in DONE
                                                         for t in ts), f"reading {name}", timeout=600)
        reqs = demo.call("GET", f"/doc_intel/requirements/{p}")["requirement_set"]["requirements"]  # type: ignore
        check(len(reqs) >= 3, f"{name}: {len(reqs)} requirements extracted")
        demo.call("POST", f"/projects/{p}/stop")

    # 2. research -> verification -> follow-up -> re-check
    print("\n2. TCP chat assignment: plan -> approve -> research -> verification -> follow-up -> re-check")
    pid = demo.call("POST", "/projects", {"name": "Sprint 6 demo: TCP chat"})["project_id"]  # type: ignore[index]
    docs.upload(pid, [("tcp_chat_assignment.pdf", DEMO / "tcp_chat_assignment.pdf")])
    project = demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("AWAITING_APPROVAL", "FAILED"), "the plan",
                        timeout=600)
    check(project["state"] == "AWAITING_APPROVAL", "the plan waits for a person")
    plan = demo.call("GET", f"/planning/plan/{pid}")
    demo.call("POST", f"/planning/plan/{pid}/approve", {"approved": True,
                                                         "graph_version": plan["graph"]["version"]})  # type: ignore[index]

    def checks(ts: list[dict]) -> list[dict]:
        return [t for t in ts if t["capability"] == "verify.claims"]

    tasks = demo.wait(f"/projects/{pid}/tasks", lambda ts: any(t["state"] == "COMPLETED" for t in checks(ts)),
                      "the verification step", timeout=600)
    first = next(t for t in checks(tasks) if t["state"] == "COMPLETED")
    d1 = show_check(pid, first["task_id"])
    flagged = [c for c in d1["trace"]["claims"] if c["verdict"] != "VERIFIED"]
    check(bool(d1["trace"]["claims"]), "every research finding was checked")
    check(bool(flagged), f"{len(flagged)} finding(s) flagged for a person to see")
    c1 = d1["trace"]["claims"][0]
    check(all(r["ok"] for a in c1["atoms"] for r in a["l1"]) or c1["verdict"] == "UNSUPPORTED",
          "L1: quotes checked word for word against the saved pages")
    def completed(evs: list[dict]) -> list[dict]:
        return [e for e in evs
                if e["event_type"] == "verification.completed" and e["aggregate_id"] == first["task_id"]]

    events = demo.wait(f"/events?project_id={pid}&limit=2000", lambda evs: bool(completed(evs)),
                       "verification.completed", timeout=60)
    done = completed(events)  # type: ignore[arg-type]
    summ = done[0]["data"]["summary"] if done else {}
    check(bool(done) and sum(summ.values()) == len(d1["trace"]["claims"]),
        "verification.completed was published with the summary")
    follow = done[0]["data"].get("follow_up")
    check(bool(follow), "the flagged findings became a follow-up research task (bounded: 1 round)")
    print(f"    follow-up questions: {d1['trace']['follow_up_questions']}")
    tasks = demo.wait(f"/projects/{pid}/tasks", lambda ts: any(t["task_id"] == follow["verify_task_id"]
                                                               and t["state"] in DONE for t in ts),
                      "the follow-up research and the re-check", timeout=600)
    recheck = next(t for t in tasks if t["task_id"] == follow["verify_task_id"])
    check(recheck["state"] == "COMPLETED", "the re-check finished")
    d2 = show_check(pid, recheck["task_id"])
    flagged2 = [c for c in d2["trace"]["claims"] if c["verdict"] != "VERIFIED"]
    print(f"    before the follow-up: {len(flagged)} of {len(d1['trace']['claims'])} findings flagged; after: "
          f"{len(flagged2)} of {len(d2['trace']['claims'])} (the follow-up report keeps the earlier evidence and adds "
          f"what it found on the gaps)")
    check(d2["summary"]["round"] == 1, "the re-check is round 1 (the loop stops there)")
    final = demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("COMPLETED", "FAILED"), "the rest of the plan",
                      timeout=600)
    check(final["state"] == "COMPLETED", "the remaining (stub) steps finished: project complete")
    time.sleep(1.0)
    ts = demo.call("GET", f"/projects/{pid}/tasks")
    check(len(checks(ts)) == 2, "no third round: the follow-up loop terminated")  # type: ignore[arg-type]

    # 3. the security layer
    print("\n3. Security: signed messages, policy table, audit")
    sec = demo.call("GET", "/verify/security")
    print(f"    keyring: {sec['keyring']}, keys {[k['kid'] for k in sec['keys']]}; "  # type: ignore[index]
          f"{len(sec['table'])} policy rows; {sec['registrations']} registrations audited; "  # type: ignore[index]
          f"refused (ever): {len(sec['refused'])}")  # type: ignore[index]
    check(sec["enforced"] and sec["registrations"] >= 1, "every agent registered with a signed message")  # type: ignore
    since = datetime.fromisoformat(started)
    refused = [e for e in sec["refused"] if datetime.fromisoformat(str(e["at"])) >= since]  # type: ignore[index]
    check(not refused, "no platform message was refused during this demo (the policy lets real agents work)")

    print("\nSprint 6 demo PASS. In the dashboard: the project's Verification tab shows every finding with its "
          "verdict, "
          "the quote next to the saved page, each layer's result, and the follow-up research it asked for.")


if __name__ == "__main__":
    main()
