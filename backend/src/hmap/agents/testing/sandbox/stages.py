"""Runs INSIDE the sandbox container (plan D3, D5); copied into the image as ``/opt/hmap/stages.py`` (both the
Python and the Node image). Standard library only: it must not import ``hmap``.

    python /opt/hmap/stages.py <base64 JSON plan>      # the workspace arrives as a tar on stdin

The plan is ``{"steps": [...], "limits": {"nproc": n, "as_mb": m}}`` (or just the list of steps), each step
``{name, kind, args, timeout, needs, stdin, coverage}``. Every step runs with per-process limits (``setrlimit``:
processes, address space) on top of the container's cgroup limits; under gVisor those cgroup limits apply to
gVisor's own kernel, so these are what stop a fork bomb or a memory hog without killing the whole run. Each step
runs in its own process group with its own time limit; a step whose ``needs`` did not all pass is skipped. One line
``HMAP_RESULTS <json>`` is printed at the end: per step the exit code, time-out flag, capped output and the small
report files it produced (JUnit XML, coverage JSON, bandit JSON).
"""

import base64
import contextlib
import json
import os
import signal
import subprocess
import sys
import tarfile
import threading
import time
from typing import Any

WORK = "/work"
OUT = "/tmp/hmap"
STEP_OUTPUT_CAP = 16_000
FILE_CAP = 200_000

IMPORT_CHECK = '''import importlib, sys, traceback
sys.path.insert(0, ".")
bad = 0
for name in sys.argv[1:]:
    try:
        importlib.import_module(name)
    except SystemExit:
        pass
    except BaseException:
        bad += 1
        print(f"import {name} failed:")
        traceback.print_exc(limit=-8)
sys.exit(1 if bad else 0)
'''


def cap(text: str, limit: int = STEP_OUTPUT_CAP) -> str:
    return text if len(text) <= limit else text[: limit // 2] + "\n...[output cut]...\n" + text[-limit // 2:]


def command(step: dict[str, Any]) -> list[str]:
    kind, args, name = step["kind"], list(step.get("args") or []), step["name"]
    py = sys.executable
    if kind == "ruff":
        return ["ruff", "check", "--no-cache", "--isolated", "--select", "E4,E7,E9,F", "--output-format", "concise",
                *(args or ["."])]
    if kind == "mypy":
        return ["mypy", "--no-color-output", "--hide-error-context", "--no-error-summary", "--cache-dir", f"{OUT}/mypy",
                *(args or ["."])]
    if kind == "compile":
        return [py, "-m", "py_compile", *args]
    if kind == "imports":
        with open(f"{OUT}/import_check.py", "w", encoding="utf-8") as fh:
            fh.write(IMPORT_CHECK)
        return [py, f"{OUT}/import_check.py", *args]
    if kind == "pytest":
        base = ["-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "-rfE", f"--junitxml={OUT}/{name}.xml",
                *args]
        if step.get("coverage"):
            return ["coverage", "run", f"--data-file={OUT}/.coverage", "--omit=*/test*,*/conftest.py", *base]
        return [py, *base]
    if kind == "bandit":
        return ["bandit", "-q", "-r", ".", "-f", "json", "-o", f"{OUT}/{name}.json", "-x",
                "./tests,./test,./.tmp", *args]
    if kind == "script":
        return [py, *args]
    node_bin = "/opt/hmap/node_modules/.bin"
    if kind == "eslint":
        return [f"{node_bin}/eslint", "--no-config-lookup", "-c", "/opt/hmap/eslint.config.mjs", "--format", "json",
                "-o", f"{OUT}/{name}.json", "--no-warn-ignored", *args]
    if kind == "node_check":
        return ["sh", "-c", 'for f in "$@"; do node --check "$f" || exit 1; done', "node-check", *args]
    if kind == "tsc":
        return [f"{node_bin}/tsc", "--noEmit", "--pretty", "false", "--target", "es2022", "--module", "nodenext",
                "--moduleResolution", "nodenext", "--allowImportingTsExtensions", "--skipLibCheck", "--types", "node",
                "--typeRoots", "/opt/hmap/node_modules/@types", *args]
    if kind == "node_test":
        strip = ["--experimental-strip-types"] if any(a.endswith((".ts", ".mts", ".cts")) for a in args) else []
        return ["node", *strip, "--test", "--test-reporter=junit", f"--test-reporter-destination={OUT}/{name}.xml",
                "--test-reporter=spec", "--test-reporter-destination=stdout", *args]
    raise ValueError(f"unknown step kind {kind}")


LIMITS: dict[str, int] = {}


def set_limits() -> None:
    """Runs in the child before exec: per-process limits (processes for this user, address space)."""
    import resource
    if LIMITS.get("nproc"):
        resource.setrlimit(resource.RLIMIT_NPROC, (LIMITS["nproc"], LIMITS["nproc"]))
    if LIMITS.get("as_mb"):
        size = LIMITS["as_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (size, size))


def run_step(step: dict[str, Any]) -> dict[str, Any]:
    cmd = command(step)
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=WORK, stdin=subprocess.PIPE if step.get("stdin") else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                            preexec_fn=set_limits)   # per child; the runner is single-threaded at this point
    head, tail = bytearray(), bytearray()
    total = [0]

    def drain() -> None:   # keep the first and last bytes only: a 200 MB flood must not fill this process's memory
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read(65536), b""):  # type: ignore[union-attr]
            total[0] += len(chunk)
            room = STEP_OUTPUT_CAP // 2 - len(head)
            if room > 0:
                head.extend(chunk[:room])
                chunk = chunk[room:]
            tail.extend(chunk)
            del tail[:-STEP_OUTPUT_CAP // 2]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    if proc.stdin is not None:
        with contextlib.suppress(BrokenPipeError):
            proc.stdin.write((step.get("stdin") or "").encode())
            proc.stdin.close()
    timed_out = False
    try:
        proc.wait(timeout=float(step["timeout"]))
    except subprocess.TimeoutExpired:
        timed_out = True
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)       # also children left behind by a finished process
    proc.wait()
    reader.join(timeout=5)
    out = bytes(head) + (b"\n...[output cut]...\n" if total[0] > len(head) + len(tail) else b"") + bytes(tail)
    files = {}
    if step["kind"] == "pytest" and step.get("coverage") and not timed_out:
        subprocess.run(["coverage", "json", f"--data-file={OUT}/.coverage", "-o", f"{OUT}/{step['name']}.cov.json",
                        "-q"], cwd=WORK, capture_output=True, timeout=30)
    for suffix in (".xml", ".json", ".cov.json"):
        path = f"{OUT}/{step['name']}{suffix}"
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                files[suffix] = fh.read(FILE_CAP)
    return {"name": step["name"], "exit_code": None if timed_out else proc.returncode, "timed_out": timed_out,
            "output": cap((out or b"").decode("utf-8", "replace")), "seconds": round(time.monotonic() - started, 3),
            "cmd": " ".join(cmd[:12]), "files": files, "skipped": False}


def extract(stream: Any) -> None:
    """Regular files only, relative paths only (no "..", no links): the workspace tar is untrusted. Done by hand
    because the Node image's Python (Debian 3.11.2) predates ``extractall(filter="data")``."""
    with tarfile.open(fileobj=stream, mode="r|") as tar:
        for member in tar:
            name = member.name
            if not member.isfile() or name.startswith("/") or ".." in name.split("/") or "\0" in name:
                continue
            target = os.path.join(WORK, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                continue
            with open(target, "wb") as fh:
                fh.write(src.read())


def main() -> None:
    plan = json.loads(base64.b64decode(sys.argv[1]).decode())
    if isinstance(plan, dict):
        LIMITS.update({k: int(v) for k, v in (plan.get("limits") or {}).items() if v})
        plan = plan["steps"]
    if LIMITS.get("as_mb"):
        # glibc reserves a 64 MB malloc arena per thread: with an address-space cap, 20 threads would not start
        os.environ["MALLOC_ARENA_MAX"] = "2"
    os.makedirs(OUT, exist_ok=True)
    extract(sys.stdin.buffer)
    results: list[dict[str, Any]] = []
    passed: set[str] = set()
    for step in plan:
        if any(n not in passed for n in step.get("needs") or []):
            results.append({"name": step["name"], "skipped": True, "exit_code": None, "timed_out": False,
                            "output": "", "seconds": 0.0, "cmd": "", "files": {}})
            continue
        try:
            res = run_step(step)
        except Exception as exc:   # a missing tool must not hide the other steps
            res = {"name": step["name"], "skipped": False, "exit_code": 127, "timed_out": False,
                   "output": f"could not run: {exc}", "seconds": 0.0, "cmd": "", "files": {}}
        if res["exit_code"] == 0:
            passed.add(step["name"])
        results.append(res)
    sys.stdout.write("HMAP_RESULTS " + json.dumps(results) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
