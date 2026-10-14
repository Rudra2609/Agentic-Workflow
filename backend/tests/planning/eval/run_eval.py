"""Evaluation harness for planning (spec item 3.14). Runs the real planner on every gold case and prints validity,
coverage, flags, step matching, dependency precision / recall, must-edge recall, invented capabilities and latency.

    cd backend
    uv run python -m tests.planning.eval.run_eval --mode rules            # no model: template + rule planner
    uv run python -m tests.planning.eval.run_eval --mode replay           # recorded answers (no network, no keys)
    uv run python -m tests.planning.eval.run_eval --mode record           # live models (cloud first), recorded
    uv run python -m tests.planning.eval.run_eval --mode live --local-only   # local qwen3.5:9b only, NOT recorded

Results go to ``samples/planning/eval_results/<name>.json`` (``--name``, default: the mode).
"""

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from typing import Any

from hmap.agents.planning.decompose import ResultCache
from hmap.agents.planning.pipeline import PlanResult, make_plan
from hmap.agents.planning.replan import replan
from hmap.agents.planning.validate import WORK_PHASES, check, errors
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.contracts.domain import RequirementSet
from hmap.core.llm.base import LLMClient
from hmap.core.llm.gateway import Gateway

from .metrics import PRF, PlanScore, score_plan

GOLD = REPO_ROOT / "samples" / "planning" / "gold"
RESULTS = REPO_ROOT / "samples" / "planning" / "eval_results"


def _references() -> dict[str, dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("planning_gold_references", GOLD / "references.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("planning_gold_references", module)
    spec.loader.exec_module(module)
    refs: dict[str, dict[str, Any]] = module.REFERENCES
    return refs


def gold_cases(only: list[str] | None = None) -> list[dict[str, Any]]:
    out = []
    for case_id, reference in _references().items():
        if only and not any(o in case_id for o in only):
            continue
        rs = RequirementSet.model_validate_json((GOLD / "inputs" / f"{case_id}.requirement_set.json").read_text())
        sections = json.loads((GOLD / "inputs" / f"{case_id}.sections.json").read_text())
        out.append({"id": case_id, "requirement_set": rs, "document_model": sections, "reference": reference})
    return out


def make_llm(mode: str, local_only: bool) -> LLMClient | None:
    if mode == "rules":
        return None
    settings = Settings.from_env().model_copy(update={"llm_mode": mode})
    gw = Gateway(settings).for_plugin("planning")
    return gw.local_only() if local_only else gw


async def plan_case(case: dict[str, Any], llm: LLMClient | None, *, cache: ResultCache | None = None) -> tuple[
        PlanResult, float]:
    started = time.perf_counter()
    result = await make_plan(case["requirement_set"], llm, document_model=case["document_model"],
                             use_llm=llm is not None, cache=cache)
    return result, time.perf_counter() - started


def score(case: dict[str, Any], result: PlanResult, seconds: float) -> PlanScore:
    return score_plan(case["id"], case["requirement_set"], result.graph, case["reference"],
                      flagged=result.report.flagged, repairs=len(result.report.repairs), seconds=seconds,
                      kind=result.kind)


# Replanning scenarios (spec 3.10): the plan's first steps are finished, then a person asks for a change.
# ``applied`` checks that the change happened in the unfinished part.
REPLANS: list[dict[str, Any]] = [
    {"case": "tcp_chat", "feedback": "Don't use threads; use asyncio for all networking.",
     "applied": lambda g, frozen: any("asyncio" in (t.title + t.description + " ".join(t.acceptance_criteria)).lower()
                                      for t in g.tasks if t.id not in frozen)},
    {"case": "long_lab", "feedback": "Merge the command-line interface steps into a single build step.",
     "applied": lambda g, frozen: sum(1 for t in g.tasks if t.phase == "implement"
                                      and {"R13", "R14", "R15"} & set(t.requirement_ids)) == 1},
]


async def replan_scenario(spec: dict[str, Any], llm: LLMClient | None,
                          plan_llm: LLMClient | None = None) -> dict[str, Any]:
    """``plan_llm`` makes the starting plan (default: ``llm``); ``--replans-only`` uses the recorded plans so only the
    replanning calls are recorded."""
    case = gold_cases([spec["case"]])[0]
    rs = case["requirement_set"]
    first, _ = await plan_case(case, plan_llm if plan_llm is not None else llm)
    builds = [t.id for t in first.graph.tasks if t.phase == "implement"]
    done = {"research", "verify", "design", *builds[:1]}
    states = {t.id: ("COMPLETED" if t.id in done else "CREATED") for t in first.graph.tasks}
    started = time.perf_counter()
    result = await replan(first.graph, rs, states=states, feedback=spec["feedback"], llm=llm, kind=first.kind,
                          previous=first.report)
    seconds = time.perf_counter() - started
    g = result.graph
    old = {t.id: t for t in first.graph.tasks}
    kept = all(any(n.id == tid and (n.title, n.requirement_ids, n.acceptance_criteria) == (
        old[tid].title, old[tid].requirement_ids, old[tid].acceptance_criteria) for n in g.tasks) for tid in done)
    covered = {r for t in g.tasks if t.phase in WORK_PHASES for r in t.requirement_ids} | set(result.report.flagged)
    return {"case": spec["case"], "feedback": spec["feedback"], "method": result.report.method,
            "fallbacks": result.report.fallbacks,
            "valid": not [i for i in errors(check(list(g.tasks), rs, flagged=result.report.flagged))
                          if i.code != "uncovered"],
            "finished_kept": kept, "covered": all(r.id in covered for r in rs.requirements),
            "applied": bool(spec["applied"](g, done)), "steps_before": len(first.graph.tasks),
            "steps_after": len(g.tasks), "repairs": result.report.repairs, "seconds": round(seconds, 2)}


def summarise(scores: list[PlanScore], results: dict[str, PlanResult]) -> dict[str, Any]:
    steps, deps, flags = PRF(), PRF(), PRF()
    for s in scores:
        steps.add(s.steps)
        deps.add(s.deps)
        flags.add(s.flags)
    n = max(1, len(scores))
    calls = sum(r.report.llm_calls for r in results.values())
    return {
        "cases": len(scores),
        "validity": round(sum(s.valid for s in scores) / n, 3),
        "coverage": round(sum(s.coverage for s in scores) / n, 3),
        "fully_covered_or_flagged": sum(1 for s in scores if not s.uncovered),
        "flags": {"precision": round(flags.precision, 3), "recall": round(flags.recall, 3)},
        "steps": {"precision": round(steps.precision, 3), "recall": round(steps.recall, 3), "f1": round(steps.f1, 3)},
        "dependencies": {"precision": round(deps.precision, 3), "recall": round(deps.recall, 3),
                         "f1": round(deps.f1, 3)},
        "must_edge_recall": round(sum(s.must_ok for s in scores) / max(1, sum(s.must_total for s in scores)), 3),
        "invented_capabilities": sum(s.invented for s in scores),
        "kind_correct": sum(s.kind_ok for s in scores),
        "repairs": sum(s.repairs for s in scores),
        "tasks_mean": round(sum(s.tasks for s in scores) / n, 1),
        "llm_calls": calls,
        "fallbacks": sum(len(r.report.fallbacks) for r in results.values()),
        "answered_by": _sum_counts(r.report.answered_by for r in results.values()),
        "seconds_total": round(sum(s.seconds for s in scores), 1),
        "seconds_mean": round(sum(s.seconds for s in scores) / n, 2),
    }


def _sum_counts(dicts: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("rules", "replay", "record", "live"), default="rules")
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--name")
    ap.add_argument("--replans-only", action="store_true",
                    help="only the replanning scenarios; the starting plans come from the recorded answers")
    args = ap.parse_args()
    if args.local_only and args.mode == "record":
        ap.error("never record local-only runs: replay keys do not include the model, so they would overwrite the "
                 "cloud recordings (use --mode live --local-only)")
    llm = make_llm(args.mode, args.local_only)
    if args.replans_only:
        plan_llm = make_llm("replay", False) if args.mode != "rules" else None
        for r in [await replan_scenario(spec, llm, plan_llm) for spec in REPLANS]:
            print(json.dumps({k: v for k, v in r.items() if k != "repairs"}))
        return
    scores: list[PlanScore] = []
    results: dict[str, PlanResult] = {}
    for case in gold_cases(args.only):
        result, seconds = await plan_case(case, llm)
        s = score(case, result, seconds)
        scores.append(s)
        results[case["id"]] = result
        print(f"{case['id']:<14} valid={s.valid!s:<5} tasks={s.tasks:<3} cover={s.coverage:.2f} "
              f"steps F1={s.steps.f1:.2f} deps P/R={s.deps.precision:.2f}/{s.deps.recall:.2f} "
              f"must={s.must_ok}/{s.must_total} flags={sorted(result.report.flagged)} "
              f"method={result.report.method} {s.seconds:.1f}s")
        for m in s.must_missed:
            print(f"    missed: {m}")
    summary = summarise(scores, results)
    replans = [] if args.only else [await replan_scenario(spec, llm) for spec in REPLANS]
    for r in replans:
        print(f"replan {r['case']:<10} valid={r['valid']} kept={r['finished_kept']} covered={r['covered']} "
              f"applied={r['applied']} method={r['method']} steps {r['steps_before']}->{r['steps_after']} "
              f"{r['seconds']}s")
    summary["replans"] = {"applied": sum(r["applied"] for r in replans),
                          "kept": sum(r["finished_kept"] for r in replans),
                          "valid": sum(r["valid"] for r in replans), "total": len(replans)}
    print(json.dumps(summary, indent=2))
    RESULTS.mkdir(parents=True, exist_ok=True)
    name = args.name or (f"{args.mode}-local" if args.local_only else args.mode)
    (RESULTS / f"{name}.json").write_text(json.dumps({
        "mode": args.mode, "local_only": args.local_only, "summary": summary, "replans": replans,
        "cases": [s.as_dict() for s in scores],
        "plans": {cid: {"tasks": [{"id": t.id, "title": t.title, "phase": t.phase, "capability": t.agent_capability,
                                   "requirements": t.requirement_ids, "after": t.depends_on} for t in r.graph.tasks],
                        "repairs": r.report.repairs, "questions": r.report.questions}
                  for cid, r in results.items()}}, indent=1) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
