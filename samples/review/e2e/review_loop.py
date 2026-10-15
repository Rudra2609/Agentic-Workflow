#!/usr/bin/env python3
"""Review -> failure analysis -> recovery loop, prototype (Member 10, prepared ahead of Sprint 10 items 10.4-10.6 and
10.11). Plain Python 3.11, no model, no project code.

    python3 samples/review/e2e/review_loop.py multi_client_unsupported      # one scenario, step by step
    python3 samples/review/e2e/check_e2e.py                                  # all scenarios vs expected

``base.json`` is the TCP-chat golden scenario: 10 requirements, a 7-task graph (research, verify, server, client,
test, docs, review), the coverage matrix (requirement -> tasks) and the evidence when everything passes. Each
scenario in ``scenarios.json`` overrides the evidence per round (what the world looks like after each revision).

Per round:
1. verdict per requirement with the objective-first rules judge (``calibration/check_calibration.py``);
2. classify each failure: MISSING, INCORRECT, UNTESTED, UNSUPPORTED_CLAIM, DOC_MISMATCH;
3. attribute it to the responsible task through the coverage matrix (+ which file failed / which task makes the
   missing deliverable);
4. plan the minimal recovery: one revision per responsible task, a rerun for a first-time timeout, a replan for a
   requirement no task covers, and re-run only the revised tasks' downstream tasks;
5. stop: PASS, or ESCALATE to a human on plateau (same failures as last round), oscillation (a failure set seen
   before) or the round budget.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "calibration"))
from check_calibration import rules  # noqa: E402

# failure category -> capability of the task that must fix it
FIXER = {"INCORRECT": "code.", "UNTESTED": "test.", "UNSUPPORTED_CLAIM": "research.", "DOC_MISMATCH": "docs."}


@dataclass
class Failure:
    req: str
    verdict: str
    category: str
    task: str | None
    why: str


@dataclass
class Plan:
    actions: list[tuple[str, str]] = field(default_factory=list)  # (revise|rerun|replan, task or requirement)
    rerun: list[str] = field(default_factory=list)  # downstream tasks to execute again (review always re-runs)


class Project:
    def __init__(self, base: dict, coverage_override: dict) -> None:
        self.reqs = base["requirements"]
        self.tasks = {t["id"]: t for t in base["tasks"]}
        self.coverage = {**base["coverage"], **coverage_override}
        self.passing = base["passing"]

    def downstream(self, task: str) -> set[str]:
        out, todo = set(), [task]
        while todo:
            cur = todo.pop()
            for t in self.tasks.values():
                if cur in t["deps"] and t["id"] not in out:
                    out.add(t["id"])
                    todo.append(t["id"])
        return out - {"T-rev"}

    def evidence(self, overrides: dict) -> dict[str, dict]:
        return {r: overrides.get(r, self.passing[r]) for r in self.reqs}

    # --- failure analysis ----------------------------------------------------------------------------------------
    def classify(self, req: str, ev: dict) -> tuple[str, str]:
        if missing := [d["name"] for d in ev["deliverables"] if not d["present"]]:
            return "MISSING", f"deliverable {', '.join(missing)} not produced"
        if bad := [t for t in ev["tests"] if req in t["covers"] and t["status"] != "passed"]:
            return "INCORRECT", "; ".join(f"{t['name']} {t['status']} ({t['module']})" for t in bad)
        if bad := [v["claim"] for v in ev["verification"] if v["verdict"] != "supported"]:
            return "UNSUPPORTED_CLAIM", "not supported: " + "; ".join(bad)
        if ev["doc_ungrounded"]:
            return "DOC_MISMATCH", "ungrounded in the docs: " + "; ".join(ev["doc_ungrounded"])
        return "UNTESTED", "no test, verification or deliverable shows it"

    def attribute(self, req: str, category: str, ev: dict) -> str | None:
        """The responsible task: among the tasks covering ``req``, the one that can fix this kind of failure."""
        covering = [self.tasks[t] for t in self.coverage.get(req, [])]
        if not covering:
            return None  # a planning gap: nobody was asked to do this
        if category == "MISSING":
            missing = {d["name"] for d in ev["deliverables"] if not d["present"]}
            owners = [t["id"] for t in self.tasks.values() if missing & set(t["outputs"])]
            return owners[0] if owners else covering[0]["id"]
        candidates = [t for t in covering if t["capability"].startswith(FIXER[category])]
        if category == "INCORRECT":  # the code task that produced the failing file
            files = {t["module"] for t in ev["tests"] if req in t["covers"] and t["status"] != "passed"}
            exact = [t for t in candidates if files & set(t["outputs"])]
            candidates = exact or candidates
        return candidates[0]["id"] if candidates else covering[0]["id"]

    def review(self, overrides: dict) -> list[Failure]:
        failures = []
        for req, ev in self.evidence(overrides).items():
            verdict = rules({"requirement": {"id": req}, "evidence": ev})
            if verdict != "PASS":
                category, why = self.classify(req, ev)
                failures.append(Failure(req, verdict, category, self.attribute(req, category, ev), why))
        return failures

    # --- recovery ------------------------------------------------------------------------------------------------
    def plan(self, failures: list[Failure], overrides: dict, first_round: bool) -> Plan:
        plan, revised = Plan(), []
        for f in failures:
            if f.task is None:
                action = ("replan", f.req)
            elif first_round and "timeout" in f.why:  # a first timeout may be the slow laptop, not the code
                action = ("rerun", "T-test")
            else:
                action = ("revise", f.task)
            if action not in plan.actions:
                plan.actions.append(action)
        for kind, target in plan.actions:
            if kind == "revise":
                revised.append(target)
        rerun = {t for kind, target in plan.actions if kind != "replan" for t in self.downstream(target)}
        rerun |= {target for kind, target in plan.actions if kind == "rerun"}
        plan.rerun = sorted(rerun - set(revised), key=list(self.tasks).index)
        return plan


def run(scenario: dict, base: dict, verbose: bool = False) -> dict:
    project = Project(base, scenario["coverage_override"])
    seen: list[set] = []
    first: dict = {}
    for rnd in range(len(scenario["rounds"]) + 1):
        overrides = scenario["rounds"][min(rnd, len(scenario["rounds"]) - 1)]
        failures = project.review(overrides)
        key = {(f.req, f.category) for f in failures}
        if verbose:
            print(f"round {rnd}: " + ("all requirements PASS" if not failures else "; ".join(
                f"{f.req} {f.verdict} {f.category} -> {f.task or 'no task'} ({f.why})" for f in failures)))
        if not failures:
            return {**first, "outcome": "PASS", "rounds": rnd}
        reason = ("plateau" if seen and key == seen[-1] else "oscillation" if key in seen else
                  "budget" if rnd >= scenario["budget"] else None)
        if reason:
            if verbose:
                print(f"  ESCALATE to a human: {reason}")
            return {**first, "outcome": "ESCALATE", "rounds": rnd, "reason": reason}
        seen.append(key)
        plan = project.plan(failures, overrides, first_round=rnd == 0)
        if verbose:
            print(f"  plan: {', '.join(f'{k} {t}' for k, t in plan.actions)}; re-run {', '.join(plan.rerun) or '-'}"
                  " + review")
        if rnd == 0:
            first = {"failures": [[f.req, f.category, f.task] for f in failures],
                     "actions": [list(a) for a in plan.actions], "rerun": plan.rerun}
    raise AssertionError("unreachable: the last round repeats until a stop rule fires")


def load() -> tuple[dict, list[dict]]:
    return (json.loads((HERE / "base.json").read_text(encoding="utf-8")),
            json.loads((HERE / "scenarios.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    base, scenarios = load()
    chosen = [s for s in scenarios if len(sys.argv) < 2 or s["id"] == sys.argv[1]]
    for s in chosen:
        print(f"== {s['id']}: {s['description']}")
        print(json.dumps(run(s, base, verbose=True)))
