#!/usr/bin/env python3
"""Seed a running platform for a live demo: sign in (creating the account the first time), create a project,
upload the sample assignment and stop at the human approval gate, so the presenter approves the plan in the
dashboard and the audience watches the tasks run.

Usage: scripts/seed.sh [API base URL, default http://127.0.0.1:8000] [document, default samples/demo/...]
Account: HMAP_SEED_EMAIL / HMAP_SEED_PASSWORD (default demo@example.test / "hmap local demo"; local demo only —
sign in to the dashboard with the same account to see the project).
(Full one-command demo packaging with reset is Member 9's Sprint 9 work.)
"""

import mimetypes
import os
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # reuse its tiny HTTP helpers


def main() -> None:
    demo.API = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/") + "/api"
    doc = Path(sys.argv[2]) if len(sys.argv) > 2 else demo.DOC
    try:
        demo.call("GET", "/health")
    except OSError:
        raise SystemExit(f"FAIL: API not reachable at {demo.API} (start it with `make api`)") from None
    email = os.environ.get("HMAP_SEED_EMAIL", "demo@example.test")
    password = os.environ.get("HMAP_SEED_PASSWORD", "hmap local demo")
    try:
        demo.call("POST", "/auth/login", {"email": email, "password": password})
    except urllib.error.HTTPError:
        demo.sign_up("Demo presenter", email, password)
    pid = demo.call("POST", "/projects", {"name": f"Demo: {doc.stem.replace('_', ' ')}"})["project_id"]  # type: ignore[index]
    ctype = mimetypes.guess_type(doc.name)[0] or "application/octet-stream"
    boundary = "hmapseedboundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{doc.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + doc.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    demo.call("POST", f"/projects/{pid}/documents", raw=body, content_type=f"multipart/form-data; boundary={boundary}")
    demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("AWAITING_APPROVAL", "FAILED"), "the plan", timeout=600)
    state = demo.call("GET", f"/projects/{pid}")["state"]  # type: ignore[index]
    print(f"project {pid}: {state}")
    print(f"open http://127.0.0.1:3000/projects/{pid} and approve the plan")


if __name__ == "__main__":
    main()
