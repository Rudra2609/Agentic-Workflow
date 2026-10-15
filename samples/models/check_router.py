#!/usr/bin/env python3
"""Does a router beat "one model for every role"? Offline answer from the bake-off results (Member 11, prepared
ahead of Sprint 11 item 11.7: "beats single-model on quality-per-latency or says honestly it doesn't"). Plain Python
3.11, reads only ``data/``.

    python3 samples/models/check_router.py

The benchmark table is chosen on one half of the items and scored on the other half (2 folds, averaged), so it is
not graded on the data it was picked with. Sanity check: the single-model policies must reproduce the bake-off
quality in docs/members/11/model-choice.md (0.833 and 0.827).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from router import ORDER, Cascade, Single, Table, load, simulate  # noqa: E402

MODELS = ["qwen3.5:9b", "qwen3.5:4b", "qwen3:8b", "qwen2.5-coder:7b", "llama3.1:8b"]


def folds(items: dict) -> list[tuple[list, list]]:
    keys = sorted(items)
    a = [k for t in ORDER for i, k in enumerate(sorted(k for k in keys if k[0] == t)) if i % 2 == 0]
    b = [k for k in keys if k not in a]
    return [(a, b), (b, a)]


def averaged(make, items, speed, ram):
    """Average a policy over the two folds (fit on one half, score on the other)."""
    runs = []
    for fit_keys, test_keys in folds(items):
        policy = make(fit_keys)
        runs.append(simulate(policy, items, test_keys, speed, ram))
    out = {k: sum(r[k] for r in runs) / len(runs) for k in ("quality", "seconds", "swaps", "calls")}
    return {**out, "policy": runs[0]["policy"], "log": runs[0]["log"], "tables": [getattr(make(f), "table", None)
                                                                                   for f, _ in folds(items)]}


def main() -> int:
    items, speed = load()
    every = sorted(items)
    base9 = simulate(Single("qwen3.5:9b"), items, every, speed)
    base4 = simulate(Single("qwen3.5:4b"), items, every, speed)
    sane = round(base9["quality"], 3) == 0.833 and round(base4["quality"], 3) == 0.827
    print(f"sanity: single-model quality reproduces the bake-off: 9b {base9['quality']:.3f}, 4b "
          f"{base4['quality']:.3f} -> {'yes' if sane else 'NO'}")

    ok = sane
    for ram in (16, 24):
        policies = [
            ("single qwen3.5:9b (today)", lambda _k: Single("qwen3.5:9b")),
            ("single qwen3.5:4b (lite)", lambda _k: Single("qwen3.5:4b")),
            ("table, Qwen 3.5 pair", lambda k: Table.fit(items, k, ["qwen3.5:9b", "qwen3.5:4b"])),
            ("table, all 5 models", lambda k: Table.fit(items, k, MODELS)),
            ("cascade 4b -> 9b", lambda _k: Cascade("qwen3.5:4b", "qwen3.5:9b")),
        ]
        print(f"\n{ram} GB laptop (9b + 4b together "
              f"{'fit' if ram >= 24 else 'do NOT fit'} next to the demo stack -> "
              f"{'no swap cost' if ram >= 24 else 'every model change is a cold load'}); scored on held-out halves")
        print(f"{'policy':28s} {'quality':>7s} {'s/project':>9s} {'swaps':>5s} {'calls':>5s}  vs today")
        results = []
        for label, make in policies:
            r = averaged(make, items, speed, ram)
            results.append((label, r))
        today = results[0][1]
        for label, r in results:
            dq, ds = r["quality"] - today["quality"], r["seconds"] / today["seconds"] - 1
            print(f"{label:28s} {r['quality']:7.3f} {r['seconds']:9.0f} {r['swaps']:5.1f} {r['calls']:5.2f}  "
                  f"{dq:+.3f} quality, {ds:+.0%} time")
        tables = results[2][1]["tables"]
        print("table picked on each half: " + " | ".join(", ".join(f"{t}={m.split(':')[1]}" for t, m in tab.items())
                                                       for tab in tables))
        cascade = results[4][1]
        if ram == 16 and cascade["log"]:
            print("decision log (cascade): " + "; ".join(f"{d.task} -> {d.model} ({d.reason})"
                                                         for d in cascade["log"][:2]))
        pareto = [label for label, r in results
                  if not any(o["quality"] >= r["quality"] and o["seconds"] <= r["seconds"]
                             and (o["quality"], o["seconds"]) != (r["quality"], r["seconds"]) for _, o in results)]
        print("not beaten on both quality and time by any other policy: " + ", ".join(pareto))
        ok = ok and "cascade 4b -> 9b" in pareto
    print("\ncaveats: in the bake-off the cascade's escalation signal for coding is the same test set that grades it (an\n"
          "upper bound); speeds were measured under swap pressure (model-choice.md); 88 items, so +/-0.01 is noise.")
    print("\nOK (simulation consistent with the bake-off)" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
