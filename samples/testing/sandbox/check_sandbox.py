#!/usr/bin/env python3
"""Prove every sandbox limit with an attack (Member 8, Sprint 8 item 8.1 "escape/abuse tests"). Needs Docker.

    python3 samples/testing/sandbox/check_sandbox.py           # builds the image once, runs 8 cases, prints a table

Each case in ``abuse/`` tries one thing a bad program would do; the check passes only if the sandbox stopped it.
Exit code 1 if any limit failed.
"""

import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_sandbox import Limits, Result, ensure_image, run

ABUSE = Path(__file__).resolve().parent / "abuse"

CASES: list[tuple[str, str, Limits, Callable[[Result], bool]]] = [
    ("ok", "a normal program runs and its output comes back", Limits(timeout_s=20),
     lambda r: r.exit_code == 0 and "hello from the sandbox" in r.output),
    ("network", "no network: DNS and a direct IP connection both fail", Limits(timeout_s=30),
     lambda r: "NETWORK_BLOCKED" in r.output),
    ("write_outside", "read-only filesystem: only the code copy (/work) and /tmp are writable", Limits(timeout_s=20),
     lambda r: "WRITES_CONFINED" in r.output),
    ("not_root", "runs as an unprivileged user, not root", Limits(timeout_s=20),
     lambda r: "NOT_ROOT" in r.output),
    ("fork_bomb", "process limit: a fork bomb is stopped (pids-limit 64)", Limits(timeout_s=30),
     lambda r: "FORK_LIMITED" in r.output and not r.timed_out),
    ("infinite_loop", "time limit: an endless loop is killed after the timeout", Limits(timeout_s=5),
     lambda r: r.timed_out and r.seconds < 20),
    ("memory_hog", "memory limit: allocating without end is stopped (256 MB, no swap)",
     Limits(timeout_s=30, memory="256m"),
     lambda r: (r.oom_killed or r.exit_code in (137, 1)) and not r.timed_out),
    ("big_output", "output limit: only the first 64 KB of a 200 MB flood are kept",
     Limits(timeout_s=60, max_output=64_000),
     lambda r: r.output_truncated and len(r.output.encode()) <= 64_000),
]


def main() -> int:
    ensure_image()
    failed = 0
    print(f"{'case':14s} {'result':6s} {'exit':>5s} {'time':>6s}  what it proves / evidence")
    for name, what, limits, ok in CASES:
        r = run(ABUSE / name, script="main.py", limits=limits)
        passed = ok(r)
        failed += not passed
        evidence = "" if r.output_truncated else (r.output.strip().splitlines() or [""])[-1][:60]
        extra = (" timed out" if r.timed_out else "") + (" OOM-killed" if r.oom_killed else "") + \
            (f"output {r.output_bytes // 1_000_000} MB, kept {len(r.output.encode()) // 1000} KB"
             if r.output_truncated else "")
        print(f"{name:14s} {'PASS' if passed else 'FAIL':6s} {r.exit_code!s:>5s} {r.seconds:5.1f}s  "
              f"{what} [{evidence}{extra}]")
    print(f"\n{len(CASES) - failed}/{len(CASES)} limits hold")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
