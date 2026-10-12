"""Regression attribution: run the same test suite on a BASE tree and on the CURRENT tree and classify every test.

The question it answers before a commit/handoff: "did *my* change break this, or was it already broken?"

  NEW_FAILURE          passed on base, fails on current (confirmed by re-runs)       -> caused by this change
  NEW_TEST_FAILING     test only exists on current and fails                         -> caused by this change
  NEWLY_RUN_FAILING    skipped on base (e.g. no infra), fails on current             -> look at it
  PRE_EXISTING         fails on base and on current                                  -> NOT caused by this change
  FIXED                fails on base, passes on current
  FLAKY                inconsistent across re-runs on either tree                    -> not attributable
  NEWLY_SKIPPED        passed on base, skipped on current                            -> warning
  REMOVED              exists on base only                                           -> warning (deleted test?)
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from hmaptools.tree import EXCLUDE_DIRS, is_excluded

FAILING = {"failed", "error"}
BLOCKING = {"NEW_FAILURE", "NEW_TEST_FAILING"}
ORDER = ["NEW_FAILURE", "NEW_TEST_FAILING", "NEWLY_RUN_FAILING", "FLAKY", "PRE_EXISTING", "NEWLY_SKIPPED",
         "REMOVED", "FIXED", "PASSING"]


@dataclass
class RunResult:
    results: dict[str, str]
    exitstatus: int
    seconds: float
    command: list[str]


@dataclass
class Classified:
    nodeid: str
    category: str
    base: str | None
    current: str | None
    reruns_base: list[str] = field(default_factory=list)
    reruns_current: list[str] = field(default_factory=list)


def copy_tree(src: Path, dst: Path) -> Path:
    """Copy a source tree without environments/caches/data so tests run in a clean, isolated copy."""
    src = src.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        rel_dir = Path(directory).resolve().relative_to(src).as_posix()
        out = set()
        for n in names:
            rel = n if rel_dir == "." else f"{rel_dir}/{n}"
            if n in EXCLUDE_DIRS or (Path(directory, n).is_file() and is_excluded(rel)):
                out.add(n)
        return out

    shutil.copytree(src, dst, ignore=ignore, symlinks=False)
    return dst


def export_git_ref(repo: Path, ref: str, dst: Path) -> Path:
    """Read-only export of a git ref (no checkout, no commit, no change to the repo)."""
    dst.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", ref], check=True,
                             capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dst)], input=archive, check=True)
    return dst


def run_pytest(tree: Path, args: list[str], scripts_dir: Path, *, label: str, timeout_s: int = 3600) -> RunResult:
    backend = tree / "backend"
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_path = tmp.name
    env = {**os.environ, "HMAP_RESULTS_JSON": out_path,
           "PYTHONPATH": os.pathsep.join(filter(None, [str(scripts_dir), os.environ.get("PYTHONPATH", "")]))}
    env.pop("VIRTUAL_ENV", None)
    cmd = ["uv", "run", "--directory", str(backend), "--frozen", "pytest", "-p", "hmaptools.pytest_results",
           "-p", "no:cacheprovider", "-q", *args]
    if not (backend / "uv.lock").exists():
        cmd.remove("--frozen")
    t0 = time.time()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_s)
    seconds = time.time() - t0
    try:
        data = json.loads(Path(out_path).read_text() or "{}")
    except (OSError, json.JSONDecodeError):
        data = {}
    finally:
        Path(out_path).unlink(missing_ok=True)
    if not data:  # collection/import error: surface the output instead of pretending nothing failed
        tail = (proc.stdout + proc.stderr)[-3000:]
        raise RuntimeError(f"[{label}] pytest produced no results (exit {proc.returncode}). Output tail:\n{tail}")
    return RunResult(dict(data.get("results", {})), int(data.get("exitstatus", proc.returncode)), seconds, cmd)


def classify(base: dict[str, str], current: dict[str, str]) -> list[Classified]:
    out: list[Classified] = []
    for nodeid in sorted(set(base) | set(current)):
        b, c = base.get(nodeid), current.get(nodeid)
        if c is None:
            cat = "REMOVED"
        elif c in FAILING:
            if b is None:
                cat = "NEW_TEST_FAILING"
            elif b in FAILING:
                cat = "PRE_EXISTING"
            elif b == "skipped":
                cat = "NEWLY_RUN_FAILING"
            else:
                cat = "NEW_FAILURE"
        elif c == "skipped":
            cat = "NEWLY_SKIPPED" if b == "passed" else "PASSING"
        else:
            cat = "FIXED" if b in FAILING else "PASSING"
        out.append(Classified(nodeid, cat, b, c))
    return out


def confirm_with_reruns(items: list[Classified], base_tree: Path, current_tree: Path, scripts_dir: Path,
                        reruns: int) -> None:
    """Re-run suspicious tests on both trees; any inconsistency => FLAKY (not attributable to the change)."""
    suspects = [i for i in items if i.category in ("NEW_FAILURE", "FIXED", "PRE_EXISTING", "NEW_TEST_FAILING")]
    if not suspects or reruns <= 0:
        return
    ids = [i.nodeid for i in suspects]
    for _ in range(reruns):
        cur = run_pytest(current_tree, ids, scripts_dir, label="current-rerun").results
        base_ids = [i.nodeid for i in suspects if i.base is not None]
        bas = run_pytest(base_tree, base_ids, scripts_dir, label="base-rerun").results if base_ids else {}
        for i in suspects:
            i.reruns_current.append(cur.get(i.nodeid, "missing"))
            if i.base is not None:
                i.reruns_base.append(bas.get(i.nodeid, "missing"))
    for i in suspects:
        cur_all = [i.current or "missing", *i.reruns_current]
        base_all = [i.base, *i.reruns_base] if i.base is not None else []
        if len({o in FAILING for o in cur_all}) > 1 or len({o in FAILING for o in base_all}) > 1:
            i.category = "FLAKY"


def environment() -> dict[str, str]:
    return {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
            "uv": subprocess.run(["uv", "--version"], capture_output=True, text=True).stdout.strip()}


def summarize(items: list[Classified]) -> dict[str, int]:
    counts = {k: 0 for k in ORDER}
    for i in items:
        counts[i.category] += 1
    return counts


def verdict(items: list[Classified]) -> tuple[bool, str]:
    blocking = [i for i in items if i.category in BLOCKING]
    if blocking:
        return False, f"{len(blocking)} test(s) broken by this change"
    return True, "no test was broken by this change"
