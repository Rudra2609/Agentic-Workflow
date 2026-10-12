#!/usr/bin/env python3
"""Check that a change only touches the given member's paths (ownership.toml).

    scripts/ownership_check.sh --member 3 --base ../hmap_handoff/sprint-2_2026-10-20
    scripts/ownership_check.sh --member 3 --files backend/src/hmap/agents/planning/agent.py docs/README.md

Exit 0 = ok (sign-off notes are warnings), 1 = another member's or an unowned path was changed.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hmaptools import ownership as own_mod  # noqa: E402
from hmaptools import tree  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--member", type=int, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--base", type=Path, help="base tree folder (handoff snapshot)")
    g.add_argument("--files", nargs="+", help="explicit list of changed paths (e.g. from `git diff --name-only`)")
    args = ap.parse_args()
    own = own_mod.Ownership.load(ROOT / "ownership.toml")
    changed = args.files if args.files else tree.diff(tree.load_manifest(args.base), tree.manifest(ROOT)).changed
    rep = own_mod.check(own, args.member, changed)
    for path, kind, owner in rep.rows:
        mark = {"own": "ok ", "common": "ok ", "shared": "!! ", "cross_cutting": "!! "}.get(kind, "XX ")
        print(f"{mark} {kind:13s} {'M' + str(owner) if owner else '--':4s} {path}")
    print(f"\n{len(rep.rows)} changed, {len(rep.errors)} error(s), {len(rep.needs_signoff)} need Member 1 sign-off")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
