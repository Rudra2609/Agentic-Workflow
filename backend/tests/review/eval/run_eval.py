"""Evaluation of the final review & recovery (Sprint 10 item 10.13, plan D19). Writes
``samples/review/eval_results/<name>.json``.

    uv run python -m tests.review.eval.run_eval                                  # rules only, no model
    uv run python -m tests.review.eval.run_eval --judge --mode record --name cloud   # + the judge (team keys)
    uv run python -m tests.review.eval.run_eval --judge --name cloud             # replay the recorded answers
    uv run python -m tests.review.eval.run_eval --judge --local-only --mode live --name local   # local model

1. **Judge vs human labels** on the calibration set (``samples/review/calibration/items.jsonl``): accuracy, Cohen's
   kappa, confusion matrix, per trap, for (a) the objective checks alone, (b) checks + the judge for what they leave
   UNDECIDED (the platform's configuration), (c) the judge alone on every item (what the model itself can do);
   **bias probes** on (a) and (c): padded producer note (verbosity), reversed evidence (order), and for (c) the
   order-sensitive flag. Human-vs-human kappa when a second labeller's file exists (``labels_second.jsonl``).
2. **Attribution** on the seeded failures (``samples/review/e2e``): category + responsible task right, vs the naive
   "first covering task" baseline.
3. **Recovery**: scenarios that end as expected, recovered (PASS) vs escalated with the right reason, average
   rounds.
4. **Golden scenarios**: rounds, revisions, outcome and wall time of the recorded end-to-end runs
   (``samples/review/e2e/final_*.json``, written by ``scripts/demo_final.sh --json=...``).
"""

import argparse
import asyncio
import copy
import json
from collections import Counter
from typing import Any

from hmap.agents.review import checks
from hmap.agents.review.aggregate import combine
from hmap.agents.review.judge import Judge
from hmap.core.config import Settings
from hmap.core.llm.gateway import Gateway
from tests.review.helpers import CAL, E2E, SAMPLES, calibration, item_of, run_scenario, scenarios

OUT = SAMPLES / "eval_results"
LABELS = ("PASS", "PARTIAL", "FAIL")
FILLER = (" This implementation is complete, robust and production ready, follows industry best practice, and has"
          " been carefully reviewed; every edge case is handled.")


def kappa(gold: list[str], pred: list[str]) -> float:
    n = len(gold)
    observed = sum(g == p for g, p in zip(gold, pred, strict=True)) / n
    cg, cp = Counter(gold), Counter(pred)
    expected = sum(cg[x] * cp[x] for x in LABELS) / (n * n)
    return round(1.0 if expected == 1 else (observed - expected) / (1 - expected), 3)


def score(items: list[dict[str, Any]], pred: list[str]) -> dict[str, Any]:
    gold = [i["label"] for i in items]
    by_trap: dict[str, list[int]] = {}
    for i, p in zip(items, pred, strict=True):
        h = by_trap.setdefault(i["trap"], [0, 0])
        h[0] += p == i["label"]
        h[1] += 1
    conf = Counter(f"{g}->{p}" for g, p in zip(gold, pred, strict=True))
    return {"n": len(items), "accuracy": round(sum(g == p for g, p in zip(gold, pred, strict=True)) / len(items), 3),
            "kappa": kappa(gold, pred), "confusion": dict(sorted(conf.items())),
            "fail_as_pass": conf.get("FAIL->PASS", 0),
            "by_trap": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_trap.items())},
            "misses": [{"id": i["id"], "req": i["requirement"]["id"], "label": i["label"], "got": p, "trap": i["trap"]}
                       for i, p in zip(items, pred, strict=True) if p != i["label"]]}


def probes(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    padded = copy.deepcopy(raw)
    padded["evidence"]["producer_note"] += FILLER
    reordered = copy.deepcopy(raw)
    for key in ("deliverables", "tests", "verification", "doc_ungrounded"):
        reordered["evidence"][key].reverse()
    return {"verbosity": padded, "order": reordered}


def rules_only(items: list[dict[str, Any]]) -> dict[str, Any]:
    def v(raw: dict[str, Any]) -> str:
        return combine(checks.run(item_of(raw)).verdict, None)[0]
    pred = [v(i) for i in items]
    flips = {p: sum(v(probes(i)[p]) != x for i, x in zip(items, pred, strict=True)) for p in ("verbosity", "order")}
    return {**score(items, pred), "probe_flips": flips,
            "undecided": sum(1 for i in items if checks.run(item_of(i)).verdict == "UNDECIDED")}


async def with_judge(items: list[dict[str, Any]], judge: Judge, *, everything: bool) -> dict[str, Any]:
    async def v(raw: dict[str, Any]) -> tuple[str, bool, bool]:
        item = item_of(raw)
        c = checks.run(item)
        if not everything and c.verdict != "UNDECIDED":
            return combine(c.verdict, None)[0], False, True
        jv, _, sensitive = await judge.verdict(item)
        if everything:
            return (jv or "PARTIAL"), sensitive, jv is not None
        return combine(c.verdict, jv)[0], sensitive, jv is not None
    res = [await v(i) for i in items]
    pred = [r[0] for r in res]
    out = {**score(items, pred), "order_sensitive": sum(1 for r in res if r[1]),
           "not_judged": sum(1 for r in res if not r[2])}
    if everything:
        padded = [await v(probes(i)["verbosity"]) for i in items]
        both = [(p[0], r[0]) for p, r in zip(padded, res, strict=True) if p[2] and r[2]]   # both calls answered
        out["probe_flips"] = {"verbosity": sum(a != b for a, b in both)}
        out["probe_pairs_judged"] = len(both)
        out["probe_flip_examples"] = [{"id": i["id"], "trap": i["trap"], "plain": r[0], "padded": p[0]}
                                      for i, p, r in zip(items, padded, res, strict=True)
                                      if p[2] and r[2] and p[0] != r[0]][:10]
    return out


def human_vs_human(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    second = CAL / "labels_second.jsonl"
    if not second.exists():
        return None
    other = {json.loads(line)["id"]: json.loads(line)["label"] for line in
             second.read_text(encoding="utf-8").splitlines() if line.strip()}
    both = [i for i in items if i["id"] in other]
    if not both:
        return None
    return {"n": len(both), "kappa": kappa([i["label"] for i in both], [other[i["id"]] for i in both]),
            "agreement": round(sum(i["label"] == other[i["id"]] for i in both) / len(both), 3)}


def attribution_and_recovery() -> dict[str, Any]:
    base, scen = scenarios()
    rows = []
    for s in scen:
        got = run_scenario(s, base)
        naive = run_scenario(s, base, naive=True)
        want = s["expect"]
        rows.append({"id": s["id"], "expected": want["outcome"] + (f" ({want['reason']})" if "reason" in want else ""),
                     "got": got["outcome"] + (f" ({got['reason']})" if "reason" in got else ""),
                     "attribution_ok": got["failures"] == want["failures"],
                     "naive_attribution_ok": naive["failures"] == want["failures"],
                     "plan_ok": got["actions"] == want["actions"] and got["rerun"] == want["rerun"],
                     "outcome_ok": got["outcome"] == want["outcome"] and got.get("reason") == want.get("reason"),
                     "rounds": got["rounds"], "failures": len(want["failures"])})
    n_fail = sum(r["failures"] for r in rows)
    return {"scenarios": rows,
            "attribution": {"correct_scenarios": sum(r["attribution_ok"] for r in rows), "of": len(rows),
                            "failures": n_fail,
                            "naive_correct_scenarios": sum(r["naive_attribution_ok"] for r in rows)},
            "recovery": {"as_expected": sum(r["outcome_ok"] and r["plan_ok"] for r in rows), "of": len(rows),
                         "recovered": sum(1 for r in rows if r["got"] == "PASS"),
                         "escalated": sum(1 for r in rows if r["got"].startswith("ESCALATE")),
                         "avg_rounds": round(sum(r["rounds"] for r in rows) / len(rows), 2)}}


def golden() -> dict[str, Any]:
    out: dict[str, Any] = {}
    live, replay = E2E / "final_live.json", E2E / "final_replay.json"
    if live.exists() and replay.exists():
        a, b = json.loads(live.read_text(encoding="utf-8")), json.loads(replay.read_text(encoding="utf-8"))
        out["replay_vs_live"] = {k: {"final_outcome_same": a[k]["project_state"] == b.get(k, {}).get("project_state"),
                                     "rounds_live": [r["recommendation"] for r in a[k]["rounds"]],
                                     "rounds_replay": [r["recommendation"] for r in b.get(k, {}).get("rounds", [])]}
                                 for k in a}
    for f in sorted(E2E.glob("final_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = {name: {"project_state": d.get("project_state"), "tasks": d.get("tasks"),
                              "review_rounds": len(d.get("rounds") or []),
                              "outcomes": [r.get("recommendation") for r in d.get("rounds") or []],
                              "revisions": sum(len(r.get("created") or []) for r in d.get("rounds") or []),
                              "stop_reason": (d.get("rounds") or [{}])[-1].get("stop_reason")}
                       for name, d in data.items()}
    return out


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    items = calibration()
    out: dict[str, Any] = {"name": args.name, "mode": args.mode if args.judge else "rules",
                           "calibration": {"items": len(items), "labels": dict(Counter(i["label"] for i in items)),
                                           "labelled_by": dict(Counter(i.get("labelled_by", "?") for i in items))},
                           "rules_only": rules_only(items), "human_vs_human": human_vs_human(items)}
    if args.judge:
        settings = Settings.from_env()
        gw = Gateway(settings.model_copy(update={"llm_mode": args.mode})).for_plugin("review")
        llm = gw.local_only() if args.local_only else gw
        out["rules_plus_judge"] = await with_judge(items, Judge(llm, samples=settings.review_judge_samples,
                                                                budget=10_000), everything=False)
        out["judge_only"] = await with_judge(items, Judge(llm, samples=2, budget=10_000), everything=True)
    out.update(attribution_and_recovery())
    out["golden"] = golden()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judge", action="store_true", help="also run the LLM judge (role judge)")
    ap.add_argument("--mode", choices=("replay", "live", "record"), default="replay")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--name", default="rules")
    args = ap.parse_args()
    res = asyncio.run(evaluate(args))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{args.name}.json"
    path.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    r = res["rules_only"]
    print(f"rules only: accuracy {r['accuracy']}, kappa {r['kappa']}, probe flips {r['probe_flips']}")
    for key in ("rules_plus_judge", "judge_only"):
        if key in res:
            j = res[key]
            print(f"{key}: accuracy {j['accuracy']}, kappa {j['kappa']}, FAIL->PASS {j['fail_as_pass']}, "
                  f"order-sensitive {j['order_sensitive']}, not judged {j['not_judged']}"
                  + (f", probe flips {j['probe_flips']}" if "probe_flips" in j else ""))
    a, rc = res["attribution"], res["recovery"]
    print(f"attribution: {a['correct_scenarios']}/{a['of']} scenarios (naive {a['naive_correct_scenarios']}); "
          f"recovery as expected {rc['as_expected']}/{rc['of']} (recovered {rc['recovered']}, escalated "
          f"{rc['escalated']}, avg rounds {rc['avg_rounds']})")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
