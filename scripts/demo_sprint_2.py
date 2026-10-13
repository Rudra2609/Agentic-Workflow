#!/usr/bin/env python3
"""Sprint 2 demo (Member 2, document intelligence): upload documents -> requirements with sources, over the API.

1. A three-part assignment uploaded as folders (Part A PDF, Part B DOCX, Part C Markdown): every requirement keeps
   its folder, and the marking criteria add up to the stated total.
2. A scanned, skewed PDF: the page is read by OCR (the vision model's recorded answer in replay mode).
Then it edits one requirement (a new version) and prints where to see it all in the dashboard.

Talks to a running API (default http://127.0.0.1:8766; demo_sprint_2.sh starts one). Exits non-zero if a check fails.
"""

import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sprint_1 as demo  # tiny HTTP helpers: call, sign_up, wait

GOLD = Path(__file__).resolve().parents[1] / "samples" / "doc_intel" / "gold" / "docs"
MEDIA = {".pdf": "application/pdf", ".md": "text/markdown",
         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def upload(pid: str, files: list[tuple[str, Path]]) -> None:
    """``files``: (relative path incl. folder, file on disk), sent as a multipart folder upload."""
    boundary = "hmapdemo" + secrets.token_hex(6)
    parts: list[bytes] = []
    for rel, path in files:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{path.name}\"\r\n"
                     f"Content-Type: {MEDIA[path.suffix]}\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"paths\"\r\n\r\n{rel}\r\n".encode())
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    demo.call("POST", f"/projects/{pid}/documents", raw=body, content_type=f"multipart/form-data; boundary={boundary}")


def check(ok: bool, what: str) -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {what}")
    if not ok:
        raise SystemExit(1)


def show(rs: dict) -> None:
    for r in rs["requirements"]:
        ref = r["source_ref"]
        where = f"{ref.get('folder') + '/' if ref.get('folder') else ''}page {ref.get('page') or '-'}"
        print(f"    {r['id']:4s} {r['priority']:6s} {r['confidence']:.2f}  {r['text'][:70]}  ({where})")
    print(f"    marking: {[(e['criterion'], e['max_marks']) for e in rs['evaluation_criteria']]} "
          f"total {rs['total_marks']}")
    for q in rs["open_questions"]:
        print(f"    question: {q}")


def run_project(name: str, files: list[tuple[str, Path]]) -> tuple[str, dict]:
    pid = demo.call("POST", "/projects", {"name": name})["project_id"]  # type: ignore[index]
    t0 = time.time()
    upload(pid, files)
    demo.wait(f"/projects/{pid}", lambda p: p["state"] in ("AWAITING_APPROVAL", "FAILED"), "the requirements",
              timeout=600)
    got = demo.call("GET", f"/doc_intel/requirements/{pid}")
    print(f"\n{name}: requirements in {time.time() - t0:.1f} s")
    show(got["requirement_set"])  # type: ignore[index]
    return pid, got  # type: ignore[return-value]


def main() -> None:
    demo.API = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766").rstrip("/") + "/api"
    for _ in range(120):  # the API (with its agents) takes a few seconds to start
        try:
            demo.call("GET", "/health")
            break
        except OSError:
            time.sleep(0.5)
    demo.sign_up("Sprint 2 demo", f"sprint2-demo-{secrets.token_hex(4)}@example.test", secrets.token_urlsafe(16))
    caps = {c["capability"]: c["status"] for c in demo.call("GET", "/agents/capabilities")}  # type: ignore[union-attr]
    check(caps.get("document.extract") == "real", "document.extract is served by the real doc_intel agent")

    parts = [("Part A/part_a.pdf", GOLD / "g08_multipart" / "Part A" / "part_a.pdf"),
             ("Part B/part_b.docx", GOLD / "g08_multipart" / "Part B" / "part_b.docx"),
             ("Part C/part_c.md", GOLD / "g08_multipart" / "Part C" / "part_c.md")]
    pid, got = run_project("Sprint 2 demo: hostel booking (3 parts)", parts)
    rs = got["requirement_set"]
    check({r["source_ref"]["folder"] for r in rs["requirements"]} == {"Part A", "Part B", "Part C"},
          "every requirement keeps its folder (Part A / B / C)")
    check(all(r["source_ref"]["quote"] for r in rs["requirements"]), "every requirement quotes its source")
    check(rs["total_marks"] == sum(e["max_marks"] for e in rs["evaluation_criteria"]) == 50,
          "marking criteria add up to the stated 50 marks")
    events = [e["event_type"] for e in demo.call("GET", f"/events?project_id={pid}")]  # type: ignore[union-attr]
    check("project.requirements_ready" in events, "project.requirements_ready was published for the planner")

    edited = dict(rs)
    edited["requirements"] = [dict(r) for r in rs["requirements"]]
    edited["requirements"][0]["text"] += " (checked by the team)"
    saved = demo.call("PUT", f"/doc_intel/requirements/{pid}", {
        "artifact_id": got["artifact"]["artifact_id"], "base_version": got["artifact"]["version"],
        "requirement_set": edited})
    check(saved["artifact"]["version"] == 2, "a human edit is stored as version 2 (version 1 kept)")  # type: ignore[index]

    scan_pid, scan = run_project("Sprint 2 demo: scanned assignment",
                                 [("library_assignment_scan.pdf",
                                   GOLD / "g04_scanned" / "library_assignment_scan.pdf")])
    model = demo.call("GET", f"/doc_intel/document-model/{scan_pid}")
    pages = model["documents"][0]["pages"]  # type: ignore[index]
    check(all(p["ocr"] for p in pages) and pages[0]["ocr_engine"] in ("vision", "tesseract"),
          f"the scanned page went through OCR ({pages[0]['ocr_engine']})")
    check(len(scan["requirement_set"]["requirements"]) >= 5, "requirements were read from the scan")

    print("\nSprint 2 demo PASS. In the dashboard (sign in as yourself, upload the same files), open a project's "
          "Requirements tab and click Source on any item to see it highlighted on the page.")


if __name__ == "__main__":
    main()
