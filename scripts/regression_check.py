#!/usr/bin/env python3
"""Prove whether YOUR change broke a test: run the backend test suite on a base tree and on your tree and compare.

    scripts/regression_check.sh --base ../hmap_handoff/sprint-1_2026-10-12      # a handoff snapshot folder
    scripts/regression_check.sh --base-ref origin/main                           # or a git ref (read-only export)
    scripts/regression_check.sh --base <dir> --member 3 -- -m "not slow"         # + ownership check, pytest args

Exit code 0 = nothing broken by this change (pre-existing failures are reported but do not block); 1 = this change
broke at least one test; 2 = could not run. Reports go to reports/regression-<time>.{md,json}.
"""

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hmaptools import ownership as own_mod  # noqa: E402
from hmaptools import regression as reg  # noqa: E402
from hmaptools import report, tree  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--base", type=Path, help="base tree folder (e.g. the handoff snapshot you received)")
    g.add_argument("--base-ref", help="git ref to compare against (exported read-only with git archive)")
    ap.add_argument("--current", type=Path, default=ROOT, help="tree to check (default: this repo)")
    ap.add_argument("--member", type=int, help="also check that only this member's paths changed")
    ap.add_argument("--reruns", type=int, default=2, help="re-runs of suspicious tests to detect flakiness")
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    ap.add_argument("pytest_args", nargs="*", help="extra pytest args after --")
    args = ap.parse_args()

    scripts_dir = ROOT / "scripts"
    with tempfile.TemporaryDirectory(prefix="hmap-regress-") as tmp:
        tmp_path = Path(tmp)
        if args.base_ref:
            base_src = reg.export_git_ref(args.current, args.base_ref, tmp_path / "base-src")
            base_label = f"git:{args.base_ref}"
        else:
            base_src = args.base.resolve()
            base_label = str(base_src)
        if not (base_src / "backend").is_dir():
            print(f"base has no backend/ folder: {base_src}", file=sys.stderr)
            return 2
        # isolated copies: never create .venv or caches inside the user's snapshot or working tree
        base_tree = reg.copy_tree(base_src, tmp_path / "base")
        current_tree = reg.copy_tree(args.current, tmp_path / "current")
        print(f"[1/4] base:    {base_label}")
        print(f"[1/4] current: {args.current.resolve()}")
        tree_diff = tree.diff(tree.load_manifest(base_src), tree.manifest(args.current))
        print("[2/4] running tests on base ...", flush=True)
        try:
            base_run = reg.run_pytest(base_tree, args.pytest_args, scripts_dir, label="base")
            print("[3/4] running tests on current ...", flush=True)
            cur_run = reg.run_pytest(current_tree, args.pytest_args, scripts_dir, label="current")
        except (RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        items = reg.classify(base_run.results, cur_run.results)
        print(f"[4/4] re-running suspicious tests x{args.reruns} on both trees ...", flush=True)
        reg.confirm_with_reruns(items, base_tree, current_tree, scripts_dir, args.reruns)

    own_file = ROOT / "ownership.toml"
    own = own_mod.Ownership.load(own_file) if own_file.exists() else None
    own_report = own_mod.check(own, args.member, tree_diff.changed) if (own and args.member) else None
    md, _js = report.render(base_label=base_label, items=items, tree_diff=tree_diff, own=own, own_report=own_report,
                           env=reg.environment(), timings={"base": base_run.seconds, "current": cur_run.seconds},
                           out_dir=args.out)
    ok, why = reg.verdict(items)
    counts = reg.summarize(items)
    print("\n" + ("PASS" if ok else "FAIL") + f": {why}")
    print("  " + ", ".join(f"{k}={v}" for k, v in counts.items() if v))
    print(f"  report: {md}")
    if own_report and own_report.errors:
        print(f"  ownership: {len(own_report.errors)} file(s) outside Member {args.member}'s paths (see report)")
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
