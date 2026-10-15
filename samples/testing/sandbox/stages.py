"""Runs inside the sandbox: static checks (ruff), security (bandit), unit tests (pytest), each with its own time
limit, and prints one JSON summary line. The workspace arrives as a tar on stdin (see run_sandbox.py)."""

import json
import subprocess
import sys
import tarfile
import time

STAGE_TIMEOUT = {"static": 30, "security": 30, "unit": 15}


def stage(name: str, cmd: list[str]) -> dict:
    started = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd="/work", capture_output=True, text=True, timeout=STAGE_TIMEOUT[name])
        out = (p.stdout + p.stderr)[-4000:]
        return {"stage": name, "exit_code": p.returncode, "timed_out": False, "output": out,
                "seconds": round(time.monotonic() - started, 2)}
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"") + (exc.stderr or b"")).decode(errors="replace")[-4000:] \
            if isinstance(exc.stdout, bytes) else str(exc.stdout or "")[-4000:]
        return {"stage": name, "exit_code": None, "timed_out": True, "output": out,
                "seconds": round(time.monotonic() - started, 2)}


def main() -> None:
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as tar:
        tar.extractall("/work", filter="data")
    stages = sys.argv[1:] or ["static", "security", "unit"]
    results = []
    if "static" in stages:
        # explicit rules (not ruff's defaults, which change between versions): syntax, undefined / unused names,
        # bare except, statement problems
        results.append(stage("static", ["ruff", "check", "--no-cache", "--isolated", "--select", "E4,E7,E9,F",
                                        "--output-format", "concise", "."]))
    if "security" in stages:
        results.append(stage("security", ["bandit", "-q", "-r", ".", "-x", "./test_*.py", "-f", "txt"]))
    if "unit" in stages:
        results.append(stage("unit", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x",
                                      "--tb=line", "."]))
    print("HMAP_STAGES " + json.dumps(results))


if __name__ == "__main__":
    main()
