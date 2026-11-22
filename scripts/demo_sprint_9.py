#!/usr/bin/env python3
"""Sprint 9 demo (Member 9: technical documentation), all over the API, offline (recorded answers).

The spec's scenario: code -> docs -> grounding report; inject a false claim -> flagged.

1. ``docs.generate`` on the TCP chat project (the code a coding step left: ``samples/docgen/repos/tcp_chat``, given
   with the task): README, API, architecture (Mermaid + graph), code summaries, report sections
2. the accuracy report: every claim checked against the code, the documented examples run in the sandbox, nothing
   ungrounded shipped; ``docs.completed`` event; the Docs tab's API
3. inject false claims (Redis, a wrong port, a flag the code does not have) -> all flagged with the reason; the true
   sentence next to them is not
4. the code changes (a new ``--max-clients`` option) -> ``docs.update``: only the documents whose facts changed are
   rewritten, and the new option is documented

Talks to a running API (default http://127.0.0.1:8771; demo_sprint_9.sh starts one). Exits non-zero if a check fails.
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
REPO = ROOT / "samples" / "docgen" / "repos" / "tcp_chat"
check = docs.check
DONE = ("COMPLETED", "FAILED", "DEAD_LETTERED", "CANCELLED")
FALSE = ("The server stores the chat history in Redis. It listens on port 6000. Start it with "
         "`python server.py --tls`. Clients send `/nick NAME` to choose a nickname.")


def code() -> dict[str, str]:
    return {p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8") for p in sorted(REPO.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.name != "README.md"}


def run(pid: str, capability: str, objective: str, files: dict[str, str]) -> dict:
    t = demo.call("POST", f"/projects/{pid}/tasks", {"capability": capability, "objective": objective,
                                                     "acceptance_criteria": ["every documented claim is grounded"],
                                                     "inputs": {"files": files, "repo_name": "tcp_chat"}})
    task = demo.wait(f"/tasks/{t['task_id']}", lambda x: x["state"] in DONE, capability, timeout=900)  # type: ignore
    check(task["state"] == "COMPLETED", f"{capability} completed ({task['executions'][-1]['outcome']})")  # type: ignore
    return demo.call("GET", f"/docgen/bundles/{pid}/{t['task_id']}")  # type: ignore[return-value,index]


def show(d: dict) -> None:
    s, acc = d["summary"], d["accuracy"]
    print(f"    {len(s['documents'])} documents ({', '.join(s['documents'])}); {acc['grounded']}/{acc['checked']} "
          f"claims grounded ({acc['grounded_pct']} %), {len(acc['removed'])} removed, {acc['unverified']} not "
          f"verified; coverage {acc['coverage_pct']} %; {s['model_calls']} model calls"
          + ("; FACTS ONLY (no model)" if s["degraded"] else ""))
    for c in acc["removed"][:3]:
        print(f"      removed: {c['kind']} {c['text']!r}: {c['why'][:90]}")
    for e in acc["examples"][:6]:
        state = {True: "ran ok", False: "FAILED", None: e["action"]}[e["ok"]]
        print(f"      example {e['code'].splitlines()[0][:50]!r}: {state} ({e['why'][:60]})")


def main() -> None:
    root = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8771").rstrip("/")
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
        demo.sign_up("Sprint 9 demo", f"sprint9-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    check(caps.get("docs.generate") == "real", "docs.generate is served by the real documentation agent")

    print("\n1. Documentation of the TCP chat project (the code a coding step left)")
    pid = demo.call("POST", "/projects", {"name": "Sprint 9 demo: TCP chat docs"})["project_id"]  # type: ignore[index]
    first = run(pid, "docs.generate", "Write the README, API docs, architecture and code summaries", code())
    show(first)
    acc = first["accuracy"]
    check(set(first["documents"]) >= {"readme", "api", "architecture", "summaries", "report"}, "all five documents")
    check(acc["ungrounded"] == 0, "nothing ungrounded is shipped (the final gate)")
    check(acc["grounded_pct"] >= 95, f"faithfulness {acc['grounded_pct']} % >= 95 %")
    check(any(e["ok"] is True for e in acc["examples"]), "a documented command ran in the sandbox")
    readme = first["documents"]["readme"]
    check("```mermaid" in first["documents"]["architecture"] and first["graph"]["nodes"], "architecture diagram")
    check("--nick" in readme and "5050" in readme, "README documents the real flag and port")
    print("    README starts: " + " ".join(readme.split("\n\n")[1].split())[:160])
    events = demo.call("GET", f"/events?project_id={pid}&limit=500")
    done = [e["data"] for e in events if e["event_type"] == "docs.completed"]  # type: ignore[union-attr,index]
    check(len(done) == 1 and done[0]["mode"] == "software", "docs.completed event (for the final review)")

    print("\n2. Inject false claims into the README and check them")
    checked = demo.call("POST", f"/docgen/check/{pid}", {"markdown": readme + "\n" + FALSE + "\n"})
    claims = checked["accuracy"]["claims"]  # type: ignore[index]
    bad = {c["text"] for c in claims if c["verdict"] == "ungrounded"}
    for c in claims:
        if c["verdict"] == "ungrounded":
            print(f"    FLAGGED {c['kind']:8s} {c['text']!r}: {c['why'][:90]}")
    check("Redis" in bad, "Redis is flagged: nothing in the code uses it")
    check("port 6000" in bad, "port 6000 is flagged: the code listens on 5050")
    check(any("--tls" in b for b in bad), "--tls is flagged: server.py has no such option")
    check(not any("/nick" in b for b in bad), "the true sentence (/nick) is not flagged")

    print("\n3. The code changes (a --max-clients option) -> docs.update")
    changed = code()
    changed["server.py"] = changed["server.py"].replace(
        'if __name__ == "__main__":\n    serve()',
        'if __name__ == "__main__":\n    import argparse\n\n    parser = argparse.ArgumentParser()\n'
        '    parser.add_argument("--max-clients", type=int, default=32)\n    parser.parse_args()\n    serve()', 1)
    check(changed["server.py"] != code()["server.py"], "server.py got a new option")
    second = run(pid, "docs.update", "Update the documentation after the code change", changed)
    show(second)
    t = second["trace"]
    check(t["previous_bundle"] == first["summary"]["task_id"], "the update starts from the first bundle")
    check("readme" in t["changed_sections"] and "api" not in t["changed_sections"],
          f"only the documents whose facts changed were rewritten ({', '.join(t['changed_sections'])})")
    check("--max-clients" in second["documents"]["readme"], "the new option is documented")
    print("\nSprint 9 demo: OK")


if __name__ == "__main__":
    main()
