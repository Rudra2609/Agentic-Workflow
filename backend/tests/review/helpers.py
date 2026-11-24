"""Shared helpers for the review tests and the eval: the calibration set (``samples/review/calibration``) and the
seeded end-to-end failures (``samples/review/e2e``) as real :class:`Item`\\ s / :class:`Bundle`\\ s, and a scenario
runner that drives the real modules (checks -> aggregate -> failures -> plan_round -> stop) round by round."""

import json
from pathlib import Path
from typing import Any

from hmap.agents.review import checks
from hmap.agents.review.aggregate import blocking, combine
from hmap.agents.review.evidence import Bundle
from hmap.agents.review.failure import analyse
from hmap.agents.review.model import Decided, Evidence, Item, TaskInfo, Verdict
from hmap.agents.review.recovery import plan_round
from hmap.agents.review.stop import signature

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "samples" / "review"
CAL = SAMPLES / "calibration"
E2E = SAMPLES / "e2e"


def calibration() -> list[dict[str, Any]]:
    return [json.loads(line) for line in (CAL / "items.jsonl").read_text(encoding="utf-8").splitlines() if line]


def item_of(raw: dict[str, Any]) -> Item:
    req = raw["requirement"]
    return Item(id=req["id"], text=req["text"], acceptance=req.get("acceptance", ""),
                evidence=Evidence.model_validate(raw["evidence"]))


def rules_verdict(item: Item) -> Verdict:
    """The deterministic layer alone (no judge): UNDECIDED -> PARTIAL ("not judged")."""
    return combine(checks.run(item).verdict, None)[0]


def decide(items: list[Item], judge: Any = None) -> list[Decided]:
    out = []
    for item in items:
        c = checks.run(item)
        jv = judge(item) if judge is not None and c.verdict == "UNDECIDED" else None
        v, src = combine(c.verdict, jv)
        out.append(Decided(item=item, check=c, verdict=v, source=src, rationale="; ".join(c.reasons)))  # type: ignore[arg-type]
    return out


# ---------------------------------------------------------------- seeded scenarios

def scenarios() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return (json.loads((E2E / "base.json").read_text(encoding="utf-8")),
            json.loads((E2E / "scenarios.json").read_text(encoding="utf-8")))


def bundle(base: dict[str, Any], coverage_override: dict[str, list[str]], overrides: dict[str, Any]) -> Bundle:
    tasks = {t["id"]: TaskInfo(task_id=t["id"], plan_task_id=t["id"], capability=t["capability"],
                               depends_on=list(t["deps"]), title=t["id"]) for t in base["tasks"]}
    coverage = {**base["coverage"], **coverage_override}
    changed = {f: t["id"] for t in base["tasks"] if t["capability"].startswith("code.") for f in t["outputs"]}
    test_task = next(t["id"] for t in base["tasks"] if t["capability"] == "test.run")
    items = []
    for rid, text in base["requirements"].items():
        ev = dict(overrides.get(rid, base["passing"][rid]))
        ev["tests"] = [{**t, "task_id": test_task} for t in ev.get("tests", [])]
        items.append(Item(id=rid, text=text, covering=list(coverage.get(rid, [])),
                          evidence=Evidence.model_validate(ev)))
    return Bundle(items=items, tasks=tasks, graph=None, requirements=None, mode="software", changed_by=changed)


def run_scenario(s: dict[str, Any], base: dict[str, Any], *, max_rounds: int | None = None,
                 naive: bool = False) -> dict[str, Any]:
    """Round by round as the Manager would: review -> plan -> (the scripted world after the fix) -> review ..."""
    history: list[list[str]] = []
    first: dict[str, Any] = {}
    budget = s["budget"] if max_rounds is None else max_rounds
    for rnd in range(len(s["rounds"]) + 1):
        overrides = s["rounds"][min(rnd, len(s["rounds"]) - 1)]
        b = bundle(base, s["coverage_override"], overrides)
        decided = decide(b.items)
        failures = analyse(blocking(decided), b)
        if naive:   # the baseline the eval compares with: the first covering task, whatever failed
            for f in failures:
                d = next(x for x in decided if x.item.id == f.item_id)
                f.task_id = d.item.covering[0] if d.item.covering else None
                f.confidence = 1.0
        rp = plan_round(failures, decided, b, review_task_id="T-rev", round_=rnd, history=history,
                        max_rounds=budget, min_confidence=0.6)
        if rnd == 0:
            first = {"failures": [[f.item_id, f.category, f.task_id] for f in failures],
                     "actions": [[p.action, p.task_id if p.action != "replan" else
                                  p.required_changes[0].split(" ")[0]] for p in rp.plans],
                     "rerun": sorted({*rp.rerun, *[p.task_id for p in rp.plans if p.action == "rerun"]},
                                     key=list(b.tasks).index)}
        if not failures:
            return {**first, "outcome": "PASS", "rounds": rnd}
        if rp.recommendation == "ESCALATE":
            reason = (rp.stop_reason or "").split(":")[0].replace("round budget", "budget")
            return {**first, "outcome": "ESCALATE", "rounds": rnd, "reason": reason}
        history.append(signature([(f.item_id, f.category) for f in failures]))
    raise AssertionError("unreachable: the last round repeats until a stop rule fires")
