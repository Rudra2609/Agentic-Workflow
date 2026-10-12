#!/usr/bin/env python3
"""Run every check a professional would run before committing / handing off, and print one summary table.

    scripts/precommit.sh                         # full local check
    scripts/precommit.sh --fast                  # skip slow tests + frontend build (what the git hook runs)
    scripts/precommit.sh --member 3 --base ../hmap_handoff/sprint-2_2026-10-20   # + ownership + regression attribution
    scripts/precommit.sh --member 3 --git-staged # ownership of the files staged in git (read-only `git diff --cached`)

Steps: secret scan · ruff · mypy · backend tests (unit, contract snapshot, plug-in conformance, e2e; integration
tests run when Postgres/RabbitMQ are up) · frontend lint/typecheck/tests(/build) · ownership · regression attribution.
Exit code 0 only if every executed step passed.
"""

import argparse
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND, FRONTEND, SCRIPTS = ROOT / "backend", ROOT / "frontend", ROOT / "scripts"


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run(name: str, cmd: list[str], cwd: Path, results: list[tuple[str, str, float, str]]) -> bool:
    print(f"\n=== {name}: {' '.join(cmd)}", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    out = (proc.stdout + proc.stderr).strip()
    tail = "\n".join(out.splitlines()[-25:])
    print(tail)
    status = "PASS" if proc.returncode == 0 else "FAIL"
    last = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "")
    results.append((name, status, time.time() - t0, last[:110]))
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--member", type=int)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--base", type=Path)
    g.add_argument("--base-ref")
    ap.add_argument("--git-staged", action="store_true")
    args = ap.parse_args()
    results: list[tuple[str, str, float, str]] = []

    run("secret scan", [str(SCRIPTS / "secret_scan.sh")], ROOT, results)
    run("ruff", ["uv", "run", "ruff", "check", "src", "tests", "../scripts", "--exclude", "../scripts/model_bakeoff.py",
                 "--exclude", "../scripts/finetune_trial.py"], BACKEND, results)
    run("mypy", ["uv", "run", "mypy", "src/hmap"], BACKEND, results)
    infra = port_open(5433) and port_open(5672)
    marker = ["-m", "not slow"] if args.fast else []
    run(f"backend tests ({'with' if infra else 'WITHOUT'} Docker infra)",
        ["uv", "run", "pytest", "-q", "-p", "no:logging", *marker], BACKEND, results)
    if (FRONTEND / "node_modules").is_dir() and shutil.which("npm"):
        for script in ["lint", "typecheck", "test"] + ([] if args.fast else ["build"]):
            run(f"frontend {script}", ["npm", "run", "--silent", script], FRONTEND, results)
    elif FRONTEND.is_dir():
        results.append(("frontend", "SKIP", 0.0, "node_modules missing (npm install in frontend/)"))
    if args.member and (args.base or args.git_staged):
        if args.git_staged:
            files = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT, text=True,
                                   capture_output=True).stdout.split()
            run("ownership", [str(SCRIPTS / "ownership_check.sh"), "--member", str(args.member), "--files", *files]
                if files else ["true"], ROOT, results)
        else:
            run("ownership", [str(SCRIPTS / "ownership_check.sh"), "--member", str(args.member),
                              "--base", str(args.base)], ROOT, results)
    if args.base or args.base_ref:
        base = ["--base", str(args.base)] if args.base else ["--base-ref", args.base_ref]
        extra = ["--", "-m", "not slow"] if args.fast else []
        run("regression attribution", [str(SCRIPTS / "regression_check.sh"), *base,
                                       *(["--member", str(args.member)] if args.member else []), *extra],
            ROOT, results)

    width = max(len(r[0]) for r in results)
    print("\n" + "=" * 100 + "\nPRE-COMMIT SUMMARY")
    for name, status, secs, last in results:
        print(f"  {status:4s}  {name:{width}s}  {secs:6.1f}s  {last}")
    failed = [r for r in results if r[1] == "FAIL"]
    print("=" * 100 + ("\nALL CHECKS PASSED" if not failed else f"\n{len(failed)} CHECK(S) FAILED"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
