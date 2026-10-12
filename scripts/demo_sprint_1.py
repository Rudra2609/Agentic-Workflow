#!/usr/bin/env python3
"""Sprint 1 demo (DoD): upload a document -> stub pipeline -> human approval -> all tasks complete, all over the API.

Talks to a running API (default http://127.0.0.1:8765; demo_sprint_1.sh starts one). Signs up a throw-away demo
user first (the API requires an account), keeps its session cookie and sends the CSRF header. Prints a short
narrative and exits non-zero if any step fails, so check_sprint.sh can use it as a smoke test.
"""

import http.cookiejar
import json
import secrets
import sys
import time
import urllib.request
from pathlib import Path

API = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765").rstrip("/") + "/api"
DOC = Path(__file__).resolve().parents[1] / "samples" / "demo" / "tcp_chat_assignment.txt"


JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))


def call(method: str, path: str, body: dict | None = None, raw: bytes | None = None,
         content_type: str = "application/json") -> dict | list:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    csrf = next((c.value for c in JAR if c.name == "hmap_csrf"), "")
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": content_type, "X-CSRF-Token": csrf})
    with OPENER.open(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def sign_up(name: str, email: str, password: str) -> None:
    call("POST", "/auth/register", {"name": name, "email": email, "password": password})


def wait(path: str, pred, what: str, timeout: float = 60) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        body = call("GET", path)
        if pred(body):
            return body  # type: ignore[return-value]
        time.sleep(0.3)
    raise SystemExit(f"FAIL: timed out waiting for {what}")


def main() -> None:
    for _ in range(100):
        try:
            call("GET", "/health")
            break
        except OSError:
            time.sleep(0.3)
    else:
        raise SystemExit(f"FAIL: API not reachable at {API}")
    sign_up("Demo user", f"demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    agents = wait("/agents", lambda a: len(a) >= 9, "9 stub agents to register")
    print(f"1. {len(agents)} agents registered: " + ", ".join(sorted({c for a in agents for c in a['capabilities']})))
    pid = call("POST", "/projects", {"name": "TCP chat (demo)"})["project_id"]  # type: ignore[index]
    boundary = "hmapdemoboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{DOC.name}\"\r\n"
            f"Content-Type: text/plain\r\n\r\n").encode() + DOC.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    up = call("POST", f"/projects/{pid}/documents", raw=body, content_type=f"multipart/form-data; boundary={boundary}")
    art = up["artifact"]  # type: ignore[index]
    print(f"2. uploaded {DOC.name} -> artifact {art['artifact_id']} (sha256 {art['sha256'][:12]}…)")
    wait(f"/projects/{pid}", lambda p: p["state"] == "AWAITING_APPROVAL", "the plan to wait for approval")
    tasks = call("GET", f"/projects/{pid}/tasks")
    print(f"3. extraction + planning done ({len(tasks)} tasks so far); project waits for HUMAN APPROVAL")  # type: ignore[arg-type]
    call("POST", f"/projects/{pid}/approval", {"approved": True, "comment": "approved by demo script"})
    print("4. plan approved")
    wait(f"/projects/{pid}", lambda p: p["state"] == "COMPLETED", "the project to complete")
    tasks = call("GET", f"/projects/{pid}/tasks")
    events = call("GET", f"/events?project_id={pid}")
    bad = [t for t in tasks if t["state"] != "COMPLETED"]  # type: ignore[union-attr, index]
    if bad:
        raise SystemExit(f"FAIL: tasks not completed: {bad}")
    print(f"5. project COMPLETED: {len(tasks)} tasks, {len(events)} events")  # type: ignore[arg-type]
    for t in tasks:  # type: ignore[union-attr]
        print(f"   - {t['capability']:18s} {t['state']}")
    print("DEMO PASS")


if __name__ == "__main__":
    main()
