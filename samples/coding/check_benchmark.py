#!/usr/bin/env python3
"""Coding mini-benchmark check (Member 7, prepared ahead of Sprint 7 items 7.12 / 7.13). Plain Python 3.11.

    python3 samples/coding/check_benchmark.py

Each task in ``tasks/<id>/`` has ``task.json`` (objective + acceptance criteria, what the agent sees),
``starter/`` (the workspace it starts from), ``hidden_tests/`` (never shown to the agent) and ``gold.edits`` (a
reference solution written as SEARCH/REPLACE blocks). For every task the check proves the benchmark is fair:

1. the **starter fails** the hidden tests (the task is not already solved);
2. the **gold edits apply** through ``edits.py`` in a jailed ``Workspace`` and then **pass** the hidden tests
   (the task is solvable in the agent's own edit format);
3. for modify / bug-fix tasks, the **locator** ranks the files to edit (top-1 / top-3).

Greenfield-from-template tasks (Sprint 7: ``"template"`` in ``task.json``) have no ``starter/``: the fairness check
starts from that template (the agent itself starts from an empty workspace and must pick the template). Decoy tasks
(``"decoy": true``) are bigger repositories with look-alike files: their locator score is reported separately and
does not gate the check. The model-driven agent runs on the same tasks in ``backend/tests/coding/eval/run_eval.py``.
"""

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parents[1] / "backend" / "src" / "hmap" / "agents" / "coding" / "templates"
sys.path.insert(0, str(HERE))
from edits import apply_text  # noqa: E402
from locate import rank_folder  # noqa: E402
from workspace import Workspace  # noqa: E402

TEST_CMD = ["python3", "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"]


def hidden_run(task: Path, workspace: Path) -> tuple[bool, str]:
    for test in (task / "hidden_tests").glob("test_*.py"):
        shutil.copy(test, workspace / test.name)
    r = Workspace(workspace).run(TEST_CMD, timeout=30)
    last = (r.output.strip().splitlines() or ["(no output)"])[-1]
    return r.exit_code == 0, "timed out" if r.timed_out else last


def make_starter(task: Path, meta: dict, dest: Path) -> None:
    if meta.get("template"):
        shutil.copytree(TEMPLATES / meta["template"], dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("template.json", "__pycache__"))
    else:
        shutil.copytree(task / "starter", dest, dirs_exist_ok=True)


def main() -> int:
    tasks = sorted(p for p in (HERE / "tasks").iterdir() if (p / "task.json").exists())
    ok_all, loc = 0, {"top1": 0, "top3": 0, "n": 0}
    decoy = {"top1": 0, "top3": 0, "n": 0}
    print(f"{'task':26s} {'kind':14s} {'starter':12s} {'gold edits':12s} {'hidden tests':12s} {'locator':8s} secs")
    for task in tasks:
        meta = json.loads((task / "task.json").read_text(encoding="utf-8"))
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="hmap-code-") as a, tempfile.TemporaryDirectory(prefix="hmap-code-") as b:
            make_starter(task, meta, Path(a))
            starter_pass, _ = hidden_run(task, Path(a))
            make_starter(task, meta, Path(b))
            located = "-"
            if meta["kind"] != "greenfield":
                ranked = [p for p, _ in rank_folder(Path(b), meta["objective"])]
                top1 = ranked[0] in meta["files_to_edit"]
                top3 = set(meta["files_to_edit"]) <= set(ranked[:3])
                bucket = decoy if meta.get("decoy") else loc
                bucket["top1"] += top1
                bucket["top3"] += top3
                bucket["n"] += 1
                located = f"{'1' if top1 else '-'}/{'3' if top3 else '-'}"
            try:
                applied = apply_text(Workspace(Path(b)), (task / "gold.edits").read_text(encoding="utf-8"))
                edit_ok = set(applied.files) == set(meta["files_to_edit"]) and not applied.notes
                edit_msg = f"{len(applied.files)} file(s)" if edit_ok else f"files {applied.files} {applied.notes}"
            except Exception as exc:  # noqa: BLE001 - report any failure in the table
                edit_ok, edit_msg = False, f"ERROR {exc}"[:40]
            gold_pass, last = hidden_run(task, Path(b)) if edit_ok else (False, "-")
        ok = not starter_pass and edit_ok and gold_pass
        ok_all += ok
        kind = meta["kind"] + ("+tpl" if meta.get("template") else "") + ("+decoy" if meta.get("decoy") else "")
        print(f"{meta['id']:26s} {kind:14s} {'fails (ok)' if not starter_pass else 'PASSES?!':12s} "
              f"{edit_msg:12s} {'pass' if gold_pass else 'FAIL ' + last:12s} {located:8s} "
              f"{time.monotonic() - t0:4.1f}" + ("" if ok else "   <-- NOT OK"))
    print(f"\n{ok_all}/{len(tasks)} tasks fair: starter fails, gold edits apply cleanly, hidden tests then pass")
    print(f"locator on {loc['n']} modify/bug-fix tasks: top-1 {loc['top1']}/{loc['n']}, "
          f"top-3 {loc['top3']}/{loc['n']}")
    print(f"BM25 locator on {decoy['n']} decoy repositories: top-1 {decoy['top1']}/{decoy['n']}, "
          f"top-3 {decoy['top3']}/{decoy['n']} (reported, not gated: the agent adds embeddings + rerank)")
    good = ok_all == len(tasks) and loc["top3"] == loc["n"]
    print("OK" if good else "FAILED")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
