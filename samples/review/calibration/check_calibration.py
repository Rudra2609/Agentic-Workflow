#!/usr/bin/env python3
"""Judge calibration harness (Member 10, prepared ahead of Sprint 10 items 10.3 / 10.10 / 10.13). Plain Python 3.11.

    python3 samples/review/calibration/check_calibration.py

``items.jsonl`` holds 36 (requirement, evidence) pairs from the TCP-chat scenario, each labelled PASS / PARTIAL /
FAIL with a rationale and a "trap" tag (confident producer, verbose but empty, untested, unsupported claim, ...).
The harness scores any judge against the labels (accuracy, Cohen's kappa, confusion matrix, per trap) and runs two
**bias probes** that must not change a verdict:

- verbosity: the producer's note is padded with confident filler;
- order: the evidence lists are reversed (position bias).

Judges here: ``rules`` (objective evidence first, the Sprint 10 design's deterministic layer), and two deliberately
bad baselines (``always_pass``, ``trust_producer``) to show what the metrics catch. A model judge plugs in the same
way: ``judge(item) -> "PASS" | "PARTIAL" | "FAIL"``.
"""

import copy
import json
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = ("PASS", "PARTIAL", "FAIL")
FILLER = (" This implementation is complete, robust and production ready, follows industry best practice, and has"
          " been carefully reviewed; every edge case is handled.")


def rules(item: dict) -> str:
    """Objective evidence decides; with no objective evidence the requirement is at best PARTIAL (untested)."""
    rid, ev = item["requirement"]["id"], item["evidence"]
    if any(not d["present"] for d in ev["deliverables"]):
        return "FAIL"
    tests = [t for t in ev["tests"] if rid in t["covers"]]
    bad = [t for t in tests if t["status"] != "passed"]
    if bad:
        return "PARTIAL" if len(bad) < len(tests) else "FAIL"
    verdicts = Counter(v["verdict"] for v in ev["verification"])
    if verdicts["contradicted"] or (verdicts and verdicts["unsupported"] == sum(verdicts.values())):
        return "FAIL"
    if verdicts["unsupported"] or ev["doc_ungrounded"]:
        return "PARTIAL"
    if tests or verdicts or ev["deliverables"]:
        return "PASS"
    return "PARTIAL"


def always_pass(item: dict) -> str:
    return "PASS"


def trust_producer(item: dict) -> str:
    """A naive judge that believes a long, confident note: the verbosity bias the probes must catch."""
    note = item["evidence"]["producer_note"]
    return "PASS" if len(note) > 80 or rules(item) == "PASS" else rules(item)


JUDGES: dict[str, Callable[[dict], str]] = {"rules": rules, "always_pass": always_pass,
                                             "trust_producer": trust_producer}


def kappa(gold: list[str], pred: list[str]) -> float:
    """Cohen's kappa: agreement corrected for chance (1 = perfect, 0 = chance level)."""
    n = len(gold)
    observed = sum(g == p for g, p in zip(gold, pred, strict=True)) / n
    cg, cp = Counter(gold), Counter(pred)
    expected = sum(cg[label] * cp[label] for label in LABELS) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def probes(item: dict) -> dict[str, dict]:
    padded = copy.deepcopy(item)
    padded["evidence"]["producer_note"] += FILLER
    reordered = copy.deepcopy(item)
    for key in ("deliverables", "tests", "verification", "doc_ungrounded"):
        reordered["evidence"][key].reverse()
    return {"verbosity": padded, "order": reordered}


def evaluate(name: str, judge: Callable[[dict], str], items: list[dict]) -> dict:
    gold = [i["label"] for i in items]
    pred = [judge(i) for i in items]
    flips = {probe: sum(judge(probes(i)[probe]) != p for i, p in zip(items, pred, strict=True))
             for probe in ("verbosity", "order")}
    by_trap: dict[str, list[int]] = {}
    for i, p in zip(items, pred, strict=True):
        hits = by_trap.setdefault(i["trap"], [0, 0])
        hits[0] += p == i["label"]
        hits[1] += 1
    return {"judge": name, "accuracy": sum(g == p for g, p in zip(gold, pred, strict=True)) / len(items),
            "kappa": kappa(gold, pred), "flips": flips, "by_trap": by_trap,
            "confusion": Counter((g, p) for g, p in zip(gold, pred, strict=True)),
            "misses": [(i["id"], i["requirement"]["id"], i["label"], p, i["trap"])
                       for i, p in zip(items, pred, strict=True) if p != i["label"]]}


def main() -> int:
    items = [json.loads(line) for line in (HERE / "items.jsonl").read_text(encoding="utf-8").splitlines() if line]
    print(f"{len(items)} items: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(i['label'] for i in items).items())))
    print(f"\n{'judge':15s} {'accuracy':>8s} {'kappa':>6s} {'verbosity flips':>15s} {'order flips':>11s}")
    results = [evaluate(name, judge, items) for name, judge in JUDGES.items()]
    for r in results:
        print(f"{r['judge']:15s} {r['accuracy']:8.0%} {r['kappa']:6.2f} {r['flips']['verbosity']:15d} "
              f"{r['flips']['order']:11d}")
    best = results[0]
    print("\nrules judge, confusion (rows = label, columns = verdict):")
    print(f"{'':9s}" + "".join(f"{p:>9s}" for p in LABELS))
    for g in LABELS:
        print(f"{g:9s}" + "".join(f"{best['confusion'][(g, p)]:9d}" for p in LABELS))
    print("per trap: " + ", ".join(f"{t} {h[0]}/{h[1]}" for t, h in sorted(best["by_trap"].items())))
    print("misses (need a model that reads the content): " +
          "; ".join(f"{i} {r} label {g} got {p} ({t})" for i, r, g, p, t in best["misses"]))
    ok = (best["kappa"] >= 0.8 and best["flips"] == {"verbosity": 0, "order": 0}
          and results[2]["flips"]["verbosity"] > 0 and results[1]["kappa"] <= 0.05)
    print("\nOK (rules kappa >= 0.8 and bias-free; the probes catch the biased baseline)" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
