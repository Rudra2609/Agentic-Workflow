#!/usr/bin/env python3
"""Run the known-good module and every seeded variant through the sandbox stage pipeline (static = ruff, security =
bandit, unit = pytest), classify each outcome with simple rules, and compare with ``labels.json`` (Member 8,
prepared ahead of Sprint 8 items 8.8 / 8.12). Needs Docker.

    python3 samples/testing/seeded_failures/check_seeded.py

The good version must pass every stage; each variant must be classified as its label. This is a first, rule-only
version of the Sprint 8 failure classifier; the real one adds file/line hints and the ``classify`` model.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "sandbox"))
from run_sandbox import Limits, Result, ensure_image, run  # noqa: E402


def classify(r: Result) -> str:
    stages = {s["stage"]: s for s in r.stages}
    unit = stages.get("unit")
    if r.timed_out or unit is None:
        return "TIMEOUT" if r.timed_out else "ENV"
    out = unit["output"]
    if unit["timed_out"]:
        return "TIMEOUT"
    if "SyntaxError" in out:
        return "SYNTAX"
    if "ModuleNotFoundError" in out or "ImportError" in out:
        return "IMPORT"
    if unit["exit_code"] not in (0, None):
        if "AssertionError" in out or "DID NOT RAISE" in out or "assert " in out:
            return "ASSERTION"
        return "CRASH"
    if stages.get("security", {}).get("exit_code", 0) != 0:
        return "SECURITY"
    if stages.get("static", {}).get("exit_code", 0) != 0:
        return "LINT"
    return "PASS"


def evaluate(module: Path) -> tuple[str, Result]:
    with tempfile.TemporaryDirectory(prefix="hmap-seeded-") as tmp:
        work = Path(tmp)
        shutil.copy(module, work / "chatproto.py")
        shutil.copy(HERE / "good" / "test_chatproto.py", work / "test_chatproto.py")
        r = run(work, limits=Limits(timeout_s=90))
    return classify(r), r


def main() -> int:
    ensure_image()
    labels = json.loads((HERE / "labels.json").read_text(encoding="utf-8"))
    rows = [{"variant": "good", "category": "PASS", "stage": "all", "description": "the known-good version"},
            *labels]
    right = 0
    print(f"{'variant':20s} {'expected':10s} {'got':10s} {'ok':3s} {'secs':>5s}  description")
    for row in rows:
        path = HERE / ("good" if row["variant"] == "good" else f"variants/{row['variant']}") / "chatproto.py"
        got, r = evaluate(path)
        ok = got == row["category"]
        right += ok
        print(f"{row['variant']:20s} {row['category']:10s} {got:10s} {'yes' if ok else 'NO':3s} {r.seconds:5.1f}  "
              f"{row['description']}")
    print(f"\n{right}/{len(rows)} classified as labelled (the good version must pass: "
          f"{'yes' if rows[0]['category'] == 'PASS' else '?'})")
    return 0 if right == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
