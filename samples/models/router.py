#!/usr/bin/env python3
"""Router prototype + offline simulation on the bake-off results (Member 11, prepared ahead of Sprint 11 item 11.7).
Plain Python 3.11, reads only ``data/``.

Policies (each call gets a ``RouteDecision`` with a reason, as the Sprint 11 router will log and show):
- ``Single(model)``: one model for every role (today's default: ``qwen3.5:9b``);
- ``Table``: a role -> model table **chosen from benchmark data** (on one half of the items, scored on the other);
- ``Cascade(cheap, strong)``: try the cheap model; if a *self-checkable* signal fails (invalid JSON, the acceptance
  tests fail, the plan has a cycle or bad ids), retry on the strong model. No gold labels are used to decide.

Time = the model's measured seconds for that item + a **model swap** (cold load) whenever the next call needs a
different model and both cannot stay in memory together (``memory.py`` decides, per laptop size).
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from memory import model_budget_gb, predict_gb, specs

DATA = Path(__file__).resolve().parent / "data"
ROLES = {"extraction": "reasoner", "planning": "reasoner", "critique": "judge", "verify": "judge", "coding": "coder"}
WEIGHTS = {"extraction": 0.25, "planning": 0.20, "critique": 0.15, "verify": 0.15, "coding": 0.25}  # bake-off's
ORDER = list(WEIGHTS)  # one "project" = one call of each task type, in pipeline order


@dataclass
class RouteDecision:
    task: str
    model: str
    reason: str


def load() -> tuple[dict[tuple[str, str], dict[str, dict]], dict]:
    items: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for line in (DATA / "bakeoff_items.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        items[(r["set"], r["id"])][r["model"]] = r
    return items, json.loads((DATA / "speed.json").read_text(encoding="utf-8"))


def self_check_failed(r: dict) -> bool:
    """Signals the platform has at run time without gold labels."""
    return (not r.get("json_valid", True) or r.get("passed_all") is False or r.get("acyclic") is False
            or r.get("ids_ok") is False)


class Single:
    def __init__(self, model: str) -> None:
        self.model, self.name = model, f"single {model}"

    def route(self, task: str, results: dict[str, dict]) -> list[RouteDecision]:
        return [RouteDecision(task, self.model, "one model for every role")]


class Table:
    def __init__(self, table: dict[str, str], name: str = "table") -> None:
        self.table, self.name = table, name

    def route(self, task: str, results: dict[str, dict]) -> list[RouteDecision]:
        return [RouteDecision(task, self.table[task], f"benchmark table: best for {task} ({ROLES[task]})")]

    @classmethod
    def fit(cls, items: dict, keys: list, models: list[str], name: str = "table") -> "Table":
        """Per task type, the model with the best mean score on ``keys``; ties go to the faster model."""
        table = {}
        for task in ORDER:
            ks = [k for k in keys if k[0] == task]
            table[task] = max(models, key=lambda m: (round(sum(items[k][m]["score"] for k in ks) / len(ks), 3),
                                                     -sum(items[k][m]["total_s"] for k in ks)))
        return cls(table, name)


class Cascade:
    def __init__(self, cheap: str, strong: str) -> None:
        self.cheap, self.strong, self.name = cheap, strong, f"cascade {cheap} -> {strong}"

    def route(self, task: str, results: dict[str, dict]) -> list[RouteDecision]:
        first = RouteDecision(task, self.cheap, "cheap model first")
        if self_check_failed(results[self.cheap]):
            why = "acceptance tests failed" if results[self.cheap].get("passed_all") is False else "self-check failed"
            return [first, RouteDecision(task, self.strong, f"escalate: {why}")]
        return [first]


def fits_together(a: str, b: str, ram_gb: float) -> bool:
    s = specs()
    embed = s["nomic-embed-text:latest"]["file_bytes"] / 1e9
    return predict_gb(s[a]) + predict_gb(s[b]) + embed <= model_budget_gb(ram_gb)


def simulate(policy, items: dict, keys: list, speed: dict, ram_gb: float = 16) -> dict:
    """Quality = the bake-off's weighted mean score per task type (exactly comparable to model-choice.md).
    Time = mean seconds per project, where project i calls item i (cycling through each smaller set) of every task
    type in pipeline order and the loaded model carries over between calls and projects."""
    by_task = {t: sorted(k for k in keys if k[0] == t) for t in ORDER}
    quality = 0.0
    for task in ORDER:
        finals = [policy.route(task, items[k])[-1].model for k in by_task[task]]
        quality += WEIGHTS[task] * sum(items[k][m]["score"] for k, m in zip(by_task[task], finals, strict=True)) \
            / len(finals)
    projects = max(len(v) for v in by_task.values())
    seconds, swaps, calls, resident, log = 0.0, 0, 0, None, []
    for i in range(projects):
        for task in ORDER:
            key = by_task[task][i % len(by_task[task])]
            decisions = policy.route(task, items[key])
            for d in decisions:
                if resident and d.model != resident and not fits_together(d.model, resident, ram_gb):
                    seconds += speed[d.model]["cold_load_s"]
                    swaps += 1
                seconds += items[key][d.model]["total_s"]
                resident = d.model
                calls += 1
            if len(decisions) > 1 and len(log) < 4:
                log += decisions
    return {"policy": policy.name, "quality": quality, "seconds": seconds / projects, "swaps": swaps / projects,
            "calls": calls / projects, "log": log}
