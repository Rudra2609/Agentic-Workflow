#!/usr/bin/env python3
"""Run every seeded end-to-end failure scenario through the review/recovery loop and compare with the expected
failure categories, responsible tasks, recovery actions, re-run set and outcome (Member 10, prepared ahead of
Sprint 10 item 10.11). Plain Python 3.11.

    python3 samples/review/e2e/check_e2e.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_loop import load, run  # noqa: E402

FIELDS = ("failures", "actions", "rerun", "outcome", "rounds", "reason")


def main() -> int:
    base, scenarios = load()
    right = {f: 0 for f in FIELDS}
    ok_all = 0
    print(f"{'scenario':26s} {'outcome':22s} {'rounds':>6s} {'ok':3s}  first plan")
    for s in scenarios:
        got, want = run(s, base), s["expect"]
        wrong = [f for f in FIELDS if got.get(f) != want.get(f)]
        for f in FIELDS:
            right[f] += f not in wrong
        ok_all += not wrong
        plan = ", ".join(f"{k} {t}" for k, t in got["actions"]) + (f"; re-run {', '.join(got['rerun'])}"
                                                                    if got["rerun"] else "")
        outcome = got["outcome"] + (f" ({got['reason']})" if got.get("reason") else "")
        print(f"{s['id']:26s} {outcome:22s} {got['rounds']:6d} {'yes' if not wrong else 'NO':3s}  {plan}"
              + (f"   WRONG {wrong}: got {[got.get(f) for f in wrong]} want {[want.get(f) for f in wrong]}"
                 if wrong else ""))
    attributed = sum(len(s["expect"]["failures"]) for s in scenarios)
    print(f"\n{ok_all}/{len(scenarios)} scenarios as expected; failure category + responsible task right in "
          f"{right['failures']}/{len(scenarios)} scenarios ({attributed} failures); recovery actions "
          f"{right['actions']}/{len(scenarios)}; outcome {right['outcome']}/{len(scenarios)}")
    recovered = sum(s["expect"]["outcome"] == "PASS" for s in scenarios)
    print(f"{recovered} recover to PASS, {len(scenarios) - recovered} escalate to a human with a reason")
    print("OK" if ok_all == len(scenarios) else "FAILED")
    return 0 if ok_all == len(scenarios) else 1


if __name__ == "__main__":
    sys.exit(main())
