#!/usr/bin/env python3
"""Sprint 5 demo (Member 5: autonomous research), all over the API, offline (cached corpus + recorded answers).

1. The TCP chat assignment: PDF -> requirements -> plan -> a person approves -> the plan's research step runs: it
   splits the questions into sub-questions, searches the saved pages, quotes sources word for word, tracks coverage
   and stops; ``research.completed`` is published; verification (still a stub) and the rest of the plan follow.
2. Every quote is checked against the saved page it came from (the evidence viewer's highlight).
3. An ad-hoc question asked from the Research tab, answered offline from the corpus.

Talks to a running API (default http://127.0.0.1:8767; demo_sprint_5.sh starts one). Exits non-zero if a check fails.
"""

import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait
import demo_sprint_2 as docs  # upload + check helpers

GOLD = Path(__file__).resolve().parents[1] / "samples" / "doc_intel" / "gold" / "docs"
check = docs.check
STOP = {"all_covered": "every sub-question answered", "low_novelty": "nothing new was turning up",
        "max_rounds": "maximum rounds reached", "budget": "budget used", "no_sources": "no usable source found"}


def events(pid: str) -> list[dict]:
    return demo.call("GET", f"/events?project_id={pid}&limit=2000")  # type: ignore[return-value]


def show(pid: str, task_id: str) -> dict:
    d = demo.call("GET", f"/research/runs/{pid}/{task_id}")
    r = d["report"]  # type: ignore[index]
    t = d["trace"]  # type: ignore[index]
    print(f"    {len(r['questions'])} question(s) -> {len(r['sub_questions'])} sub-questions; "
          f"{len(t['rounds'])} round(s); stopped: {STOP.get(r['stop_reason'], r['stop_reason'])} "
          f"({t['model_calls']} model calls, {t['tokens']} tokens)")
    numbers: dict[str, int] = {}
    ev = {e["id"]: e for e in r["evidence"]}
    for qn, q in enumerate(r["questions"]):
        print(f"    Q{qn + 1}: {q}")
        for s in [s for s in r["sub_questions"] if s["question"] == qn]:
            print(f"      [{s['status']:9s} {round(s['coverage'] * 100):3d}%] {s['text'][:100]}")
            for c in r["claims"]:
                if any(ev[i]["sub_question"] == s["id"] for i in c["evidence_ids"] if i in ev):
                    refs = []
                    for i in c["evidence_ids"]:
                        url = ev[i]["url"]
                        numbers.setdefault(url, len(numbers) + 1)
                        refs.append(f"[{numbers[url]}]")
                    print(f"          - {c['text'][:110]} {''.join(dict.fromkeys(refs))}")
    print("    sources:")
    for s in r["sources"]:
        b = s["score_breakdown"]
        print(f"      [{numbers.get(s['url'], '-')}] {s['title'][:60]} ({s['kind']}, via {s['provider']}) score "
              f"{s['score'] or 0:.2f} = relevance {b.get('relevance', 0):.2f} x quality {b.get('authority', 0):.2f} "
              f"x recency {b.get('recency', 0):.2f} x novelty {b.get('novelty', 0):.2f}")
    return d  # type: ignore[return-value]


def quotes_verified(pid: str, task_id: str, report: dict) -> tuple[int, int]:
    ok = 0
    for e in report["evidence"]:
        page = demo.call("GET", f"/research/pages/{pid}/{e['page_artifact']['artifact_id']}?task_id={task_id}")
        span = next((s for s in page["spans"] if s["evidence_id"] == e["id"]), None)  # type: ignore[index]
        if span and page["text"][span["start"]:span["end"]] == e["quote"] and \
                page["content_sha256"] == e["content_sha256"]:  # type: ignore[index]
            ok += 1
    return ok, len(report["evidence"])


def main() -> None:
    root = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8767").rstrip("/")
    demo.API = root + "/api"
    for _ in range(120):
        try:
            demo.call("GET", "/health")
            break
        except OSError:
            time.sleep(0.5)
    demo.sign_up("Sprint 5 demo", f"sprint5-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    check(caps.get("research.run") == "real", "research.run is served by the research agent (the stub stood down)")
    prov = demo.call("GET", "/research/providers")
    print(f"    research mode: {prov['mode']}; providers: {', '.join(prov['providers'])}; "  # type: ignore[index]
          f"offline corpus: {prov['corpus']['pages']} pages")  # type: ignore[index]

    # 1. the plan's research step
    print("\n1. TCP chat assignment: requirements -> plan -> approve -> research")
    pid = demo.call("POST", "/projects", {"name": "Sprint 5 demo: TCP chat"})["project_id"]  # type: ignore[index]
    docs.upload(pid, [("tcp_chat_assignment.pdf", GOLD / "g01_tcp_chat" / "tcp_chat_assignment.pdf")])
    project = demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("AWAITING_APPROVAL", "FAILED"), "the plan",
                        timeout=600)
    check(project["state"] == "AWAITING_APPROVAL", "the plan waits for a person")
    plan = demo.call("GET", f"/planning/plan/{pid}")
    steps = plan["graph"]["tasks"]  # type: ignore[index]
    research_steps = [t for t in steps if t["agent_capability"] == "research.run"]
    print(f"    the plan has {len(research_steps)} research step(s); questions: "
          f"{sum(len(t['research_questions']) for t in research_steps)}")
    demo.call("POST", f"/planning/plan/{pid}/approve", {"approved": True,
                                                         "graph_version": plan["graph"]["version"]})  # type: ignore[index]
    tasks = demo.wait(f"/projects/{pid}/tasks", lambda ts: any(t["capability"] == "research.run" and
                                                               t["state"] == "COMPLETED" for t in ts),
                      "the research step", timeout=600)
    rt = next(t for t in tasks if t["capability"] == "research.run" and t["state"] == "COMPLETED")
    d = show(pid, rt["task_id"])
    report = d["report"]
    check(bool(report["claims"]) and all(c["evidence_ids"] for c in report["claims"]),
          f"{len(report['claims'])} findings, each citing evidence")
    ok, total = quotes_verified(pid, rt["task_id"], report)
    check(total > 0 and ok == total, f"every quote is word for word in its saved page, hash matching ({ok}/{total})")
    done = [e for e in events(pid) if e["event_type"] == "research.completed"]
    check(bool(done) and done[0]["data"]["report_ref"]["artifact_type"] == "research-report",
          "research.completed was published with the report (for Member 6's verification)")
    final = demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("COMPLETED", "FAILED"), "the rest of the plan",
                      timeout=600)
    check(final["state"] == "COMPLETED", "verification (stub) and the remaining steps finished: project complete")

    # 2. an ad-hoc question from the Research tab
    print("\n2. A question asked from the Research tab (offline corpus)")
    q = "How does the asyncio event loop handle many network connections?"
    tid = demo.call("POST", f"/research/runs/{pid}", {"questions": [q]})["task_id"]  # type: ignore[index]
    demo.wait(f"/tasks/{tid}", lambda t: t["state"] in ("COMPLETED", "FAILED", "DEAD_LETTERED"), "the answer",
              timeout=300)
    d2 = show(pid, tid)
    ok2, total2 = quotes_verified(pid, tid, d2["report"])
    check(bool(d2["report"]["claims"]) and ok2 == total2, f"answered offline with {total2} verified quotes")
    runs = demo.call("GET", f"/research/runs/{pid}")
    check(len(runs) == 2, "the Research tab lists both research steps")  # type: ignore[arg-type]

    print("\nSprint 5 demo PASS. In the dashboard: the project's Research tab shows the sub-questions with coverage, "
          "the cited findings (click [n] to see the quote highlighted in the saved page), the sources with their "
          "scores and how each round searched.")


if __name__ == "__main__":
    main()
