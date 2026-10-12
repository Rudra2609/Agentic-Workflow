#!/usr/bin/env python3
"""Make the folder snapshot that goes to the next member (doc 03 §2).

    scripts/make_handoff.sh 1            -> ../hmap_handoff/sprint-1_<date>/  (+ MANIFEST.json)

Excludes environments, caches, data, logs, reports, .env (secrets) and model files. MANIFEST.json records every
file's SHA-256 so the next member's changes can be checked later without git (ownership + regression reports).
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hmaptools.regression import copy_tree  # noqa: E402
from hmaptools.secrets import scan  # noqa: E402
from hmaptools.tree import write_manifest  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("sprint")
ap.add_argument("--dest", type=Path, default=ROOT.parent / "hmap_handoff")
args = ap.parse_args()

if findings := scan(ROOT):
    print("refusing to hand off: possible secrets in the tree (run scripts/secret_scan.sh)", file=sys.stderr)
    raise SystemExit(1)
target = args.dest / f"sprint-{args.sprint}_{dt.date.today().isoformat()}"
if target.exists():
    print(f"{target} already exists - remove it or choose another --dest", file=sys.stderr)
    raise SystemExit(1)
args.dest.mkdir(parents=True, exist_ok=True)
copy_tree(ROOT, target)
m = write_manifest(target, {"sprint": args.sprint, "created": dt.datetime.now().isoformat(timespec="seconds")})
print(f"handoff snapshot: {target}\nmanifest: {m}")
