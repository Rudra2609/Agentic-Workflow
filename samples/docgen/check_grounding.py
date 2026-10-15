#!/usr/bin/env python3
"""End-to-end check of the documentation-grounding prototype (Member 9, prepared ahead of Sprint 9 items 9.1-9.6 and
9.12). Plain Python 3.11, no Docker, no model, no project code.

    python3 samples/docgen/check_grounding.py

1. Facts + Mermaid for each sample repo -> ``out/<repo>/facts.json``, ``out/<repo>/architecture.mmd``.
2. The hand-written README of each repo must be 100 % grounded (no false alarm).
3. A facts-first draft README (``draft_readme.py``) must be 100 % grounded -> ``out/<repo>/README.draft.md``.
4. Every seeded false claim in ``seeded.json`` (one sentence appended to a correct README) must be flagged; the
   behaviour claims are reported as known misses (out of reach for rules).
Exit code 1 if any of 2-4 fails.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from draft_readme import draft  # noqa: E402
from grounding import Checker  # noqa: E402
from inspect_repo import inspect, mermaid  # noqa: E402

REPOS = HERE / "repos"
OUT = HERE / "out"


def main() -> int:
    failures = 0
    checkers, readmes = {}, {}
    print(f"{'repo':12s} {'claims':>6s} {'grounded':>8s} {'draft claims':>12s} {'draft grounded':>14s}")
    for repo in sorted(p for p in REPOS.iterdir() if p.is_dir()):
        facts = inspect(repo)
        out = OUT / repo.name
        out.mkdir(parents=True, exist_ok=True)
        (out / "facts.json").write_text(json.dumps(facts, indent=1) + "\n", encoding="utf-8")
        (out / "architecture.mmd").write_text(mermaid(facts), encoding="utf-8")
        checker = checkers[repo.name] = Checker(facts)
        readmes[repo.name] = (repo / "README.md").read_text(encoding="utf-8")
        hand = checker.check(readmes[repo.name])
        drafted = draft(facts)
        (out / "README.draft.md").write_text(drafted, encoding="utf-8")
        auto = checker.check(drafted)
        for label, claims in (("README.md", hand), ("draft", auto)):
            for c in claims:
                if not c.grounded:
                    failures += 1
                    print(f"  FALSE ALARM in {repo.name} {label}: {c.kind} {c.text!r} ({c.why})")
        print(f"{repo.name:12s} {len(hand):6d} {sum(c.grounded for c in hand):8d} {len(auto):12d} "
              f"{sum(c.grounded for c in auto):14d}")

    seeded = json.loads((HERE / "seeded.json").read_text(encoding="utf-8"))
    by_cat: dict[str, list[int]] = {}
    print(f"\n{'repo':11s} {'seeded claim':20s} {'category':9s} {'caught':6s}  flagged as")
    for s in seeded:
        claims = checkers[s["repo"]].check(readmes[s["repo"]].rstrip() + "\n\n" + s["sentence"] + "\n")
        bad = [c for c in claims if not c.grounded]
        caught = any(s["expect"] in c.text for c in bad) if s["expect"] else bool(bad)
        expected = s["expect"] is not None
        failures += caught != expected
        hits = by_cat.setdefault(s["category"], [0, 0])
        hits[0] += caught
        hits[1] += 1
        flagged = "; ".join(f"{c.kind} {c.text!r}: {c.why}" for c in bad)[:90] or "-"
        mark = ("yes" if caught else "NO") if expected else ("miss" if not caught else "hit?")
        print(f"{s['repo']:11s} {s['id']:20s} {s['category']:9s} {mark:6s}  {flagged}")
    rule = [s for s in seeded if s["expect"]]
    caught_rule = sum(by_cat[c][0] for c in by_cat if c != "BEHAVIOUR")
    print("\nper category: " + ", ".join(f"{c} {h[0]}/{h[1]}" for c, h in sorted(by_cat.items())))
    print(f"seeded false claims caught: {caught_rule}/{len(rule)}; behaviour claims (needs a model): "
          f"{by_cat.get('BEHAVIOUR', [0, 0])[0]}/{by_cat.get('BEHAVIOUR', [0, 0])[1]} (expected 0, known limit)")
    print("OK" if not failures else f"FAILED ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
