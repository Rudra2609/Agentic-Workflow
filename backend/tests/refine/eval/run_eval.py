"""Ablation harness (Sprint 4 item 4.11): base vs Self-Refine vs Self-Refine + Reflexion on Member 2's and Member 3's
gold sets, scored with their own metrics, plus iterations, tokens, model calls, latency, stop reasons and how often
the judge's findings were right (critic calibration against the gold labels).

    cd backend
    uv run python -m tests.refine.eval.run_eval --suite all --producer replay      # recorded answers, no network
    uv run python -m tests.refine.eval.run_eval --suite all --producer rules       # harder: rule-made outputs
    HMAP_LLM_RECORD_MISSING=refine uv run python -m tests.refine.eval.run_eval ...  # record missing refine answers
    uv run python -m tests.refine.eval.run_eval --suite plan --refine-local --mode live   # local model, NOT recorded

``--producer``: where the output to refine comes from — ``replay`` (Members 2/3's recorded cloud answers), ``rules``
(no model: their rule-based fallbacks; more room to improve) or ``local`` (their pipeline on the local model, live).
The refinement itself uses the ``refine`` plug-in's replay cache (``samples/llm_cache/refine/``). Results go to
``samples/refine/eval_results/<name>.json``.
"""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from hmap.agents.doc_intel.cache import MemoryCache
from hmap.agents.doc_intel.pipeline import run_pipeline
from hmap.agents.refine import InMemoryStore, RefineContext, Refiner, ReflectionMemory, default_policy
from hmap.agents.refine.adapters import extraction as ex
from hmap.agents.refine.adapters import plan as pa
from hmap.agents.refine.core import SEVERITY_RANK, RefinementResult
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.llm.base import LLMClient
from hmap.core.llm.gateway import Gateway
from tests.doc_intel.eval import run_eval as m2
from tests.doc_intel.eval.metrics import PRF as PRF2
from tests.doc_intel.eval.metrics import score_document
from tests.planning.eval import run_eval as m3
from tests.planning.eval.metrics import PRF as PRF3

RESULTS = REPO_ROOT / "samples" / "refine" / "eval_results"
CONDITIONS = ("base", "self_refine", "reflexion")


def gateway(mode: str, plugin: str, local_only: bool = False) -> LLMClient:
    settings = Settings.from_env().model_copy(update={"llm_mode": mode})
    gw = Gateway(settings).for_plugin(plugin)
    return gw.local_only() if local_only else gw


@dataclass
class Run:
    condition: str
    seconds: float = 0.0
    iterations: int = 0
    tokens: int = 0
    calls: int = 0
    stop: str = "-"
    base_score: float | None = None
    best_score: float | None = None
    judge: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)


def loop_stats(res: RefinementResult, seconds: float, condition: str) -> Run:
    return Run(condition=condition, seconds=round(seconds, 2), iterations=res.iterations, tokens=res.usage.tokens,
               calls=res.usage.calls, stop=res.stop_reason, base_score=res.base_score, best_score=res.best_score,
               strategies=[a.strategy or "-" for a in res.attempts[1:]],
               errors=([res.error] if res.error else []) + sorted({e for a in res.attempts for e in a.critic_errors}))


async def refine(setup_critics: list[Any], reviser: Any, inp: Any, output: Any, llm: LLMClient | None,
                 condition: str, key: str) -> tuple[RefinementResult, float]:
    memory = ReflectionMemory(key, InMemoryStore()) if condition == "reflexion" else None
    refiner = Refiner(critics=setup_critics, reviser=reviser, stop=default_policy(), memory=memory,
                      producer_name="gold producer")
    started = time.perf_counter()
    res = await refiner.run(inp, RefineContext(llm=llm), output=output)
    return res, time.perf_counter() - started


# ---------------------------------------------------------------------------------------------- extraction


def judge_calibration_extraction(res: RefinementResult, case: dict[str, Any]) -> dict[str, int]:
    """Judge findings on the FIRST attempt vs the gold labels: an omission is right when its evidence sentence is a
    gold item that the output misses; a "not an item" finding is right when the item matches no gold item."""
    from hmap.agents.doc_intel.extract.quotes import overlap

    first = res.attempts[0]
    judge = next((p for p in first.parts if p.critic == "judge"), None)
    out = {"omission_right": 0, "omission_wrong": 0, "drop_right": 0, "drop_wrong": 0, "other": 0}
    if judge is None:
        return out
    gold = [g["text"] for k in ("requirements", "constraints") for g in case[k]] + \
        [g.get("_match") or g["text"] for g in case["deliverables"]]
    rs = first.output
    listed = [ex.item_text(it) for _, it in ex.items(rs)] + [it.source_ref.quote or "" for _, it in ex.items(rs)
                                                            if it.source_ref]
    for issue in judge.issues:
        if issue.category == "OMISSION" and issue.evidence:
            is_gold = any(overlap(g, issue.evidence) >= 0.6 for g in gold)
            missing = not any(overlap(issue.evidence, x) >= 0.75 for x in listed if x)
            out["omission_right" if is_gold and missing else "omission_wrong"] += 1
        elif issue.category == "HALLUCINATION" and issue.location:
            item = next((it for _, it in ex.items(rs) if it.id == issue.location), None)
            if item is None:
                continue
            is_gold = any(overlap(g, ex.item_text(item)) >= 0.6 or overlap(ex.item_text(item), g) >= 0.6
                          for g in gold)
            out["drop_wrong" if is_gold else "drop_right"] += 1
        else:
            out["other"] += 1
    return out


def agreement(res: RefinementResult) -> dict[str, int]:
    """Judge vs programmatic critics on the first attempt: items (ids) each flags with a major+ issue."""
    first = res.attempts[0]
    prog = {i.location for p in first.parts if p.critic != "judge" for i in p.issues
            if SEVERITY_RANK[i.severity] >= 2 and i.location}
    judge = {i.location for p in first.parts if p.critic == "judge" for i in p.issues
             if SEVERITY_RANK[i.severity] >= 2 and i.location}
    return {"both": len(prog & judge), "programmatic_only": len(prog - judge), "judge_only": len(judge - prog)}


async def extraction_suite(args: argparse.Namespace, refine_llm: LLMClient | None) -> dict[str, Any]:
    producer_llm = None
    if args.producer == "replay":
        producer_llm = gateway("replay", "doc_intel")
    elif args.producer == "local":
        producer_llm = gateway("live", "doc_intel", local_only=True)
    cases_out: dict[str, Any] = {}
    totals: dict[str, dict[str, PRF2]] = {c: {f: PRF2() for f in m2.FIELDS} for c in CONDITIONS}
    prio: dict[str, list[int]] = {c: [0, 0] for c in CONDITIONS}
    runs: dict[str, list[Run]] = {c: [] for c in CONDITIONS[1:]}
    for case in m2.gold_cases(args.only):
        started = time.perf_counter()
        result = await run_pipeline(f"P-EVAL-{case['id']}", m2.inputs_for(case), producer_llm, cache=MemoryCache(),
                                    use_llm=producer_llm is not None)
        produce_s = time.perf_counter() - started
        inp = ex.build_input(result.document_model)
        per: dict[str, Any] = {}
        outputs = {"base": (result.requirement_set, None)}
        for condition in CONDITIONS[1:]:
            res, secs = await refine(ex.extraction_critics(inp), ex.ExtractionReviser(), inp,
                                     result.requirement_set, refine_llm, condition, "document.extract")
            outputs[condition] = (res.final_output, res)
            run = loop_stats(res, secs, condition)
            run.judge = {**judge_calibration_extraction(res, case), **agreement(res)}
            runs[condition].append(run)
        for condition, (rs, res) in outputs.items():
            s = score_document(json.loads(json.dumps(case)), rs, result.document_model, produce_s)
            for f in m2.FIELDS:
                totals[condition][f].add(s.fields[f])
            prio[condition][0] += s.priority_correct
            prio[condition][1] += s.priority_total
            per[condition] = {"f1": {f: round(s.fields[f].f1, 3) for f in m2.FIELDS},
                              "tp_fp_fn": {f: [s.fields[f].tp, s.fields[f].fp, s.fields[f].fn] for f in m2.FIELDS},
                              "priority": f"{s.priority_correct}/{s.priority_total}", "misses": s.misses,
                              "extras": s.extras}
            if res is not None:
                per[condition]["loop"] = runs[condition][-1].__dict__
        cases_out[case["id"]] = per
        line = " ".join(f"{c}: R {per[c]['f1']['requirements']:.2f} C {per[c]['f1']['constraints']:.2f} "
                        f"P {per[c]['priority']}" for c in CONDITIONS)
        print(f"{case['id']:<18} {line}", flush=True)
    summary = {}
    for c in CONDITIONS:
        summary[c] = {"f1": {f: round(totals[c][f].f1, 3) for f in m2.FIELDS},
                      "precision": {f: round(totals[c][f].precision, 3) for f in m2.FIELDS},
                      "recall": {f: round(totals[c][f].recall, 3) for f in m2.FIELDS},
                      "priority_accuracy": round(prio[c][0] / max(1, prio[c][1]), 3)}
        if c in runs:
            summary[c]["loop"] = aggregate(runs[c])
    return {"summary": summary, "cases": cases_out}


# ---------------------------------------------------------------------------------------------- plan


def judge_calibration_plan(res: RefinementResult, case: dict[str, Any]) -> dict[str, int]:
    """A judge's missing dependency "A -> B" is right when the reference plan orders the matched steps A before B."""
    import networkx as nx

    from tests.planning.eval.metrics import match_steps

    first = res.attempts[0]
    judge = next((p for p in first.parts if p.critic == "judge"), None)
    out = {"dependency_right": 0, "dependency_wrong": 0, "dependency_unmatched": 0, "other": 0}
    if judge is None:
        return out
    graph = first.output
    mapping = match_steps(list(graph.tasks), case["reference"]["steps"])
    ref_g: nx.DiGraph[str] = nx.DiGraph()
    for key, (_, _, after) in case["reference"]["steps"].items():
        ref_g.add_node(key)
        for a in after:
            ref_g.add_edge(a, key)
    for issue in judge.issues:
        ids = pa._IDS.findall(issue.location or "")
        if issue.category == "LOGIC" and "->" in (issue.location or "") and len(ids) == 2:
            a, b = mapping.get(ids[0]), mapping.get(ids[1])
            if a is None or b is None:
                out["dependency_unmatched"] += 1
            elif a in ref_g and b in ref_g and nx.has_path(ref_g, a, b):
                out["dependency_right"] += 1
            else:
                out["dependency_wrong"] += 1
        else:
            out["other"] += 1
    return out


async def plan_suite(args: argparse.Namespace, refine_llm: LLMClient | None) -> dict[str, Any]:
    producer_llm = None
    if args.producer == "replay":
        producer_llm = gateway("replay", "planning")
    elif args.producer == "local":
        producer_llm = gateway("live", "planning", local_only=True)
    cases_out: dict[str, Any] = {}
    agg: dict[str, dict[str, Any]] = {c: {"deps": PRF3(), "steps": PRF3(), "must_ok": 0, "must_total": 0,
                                          "valid": 0, "coverage": 0.0, "n": 0} for c in CONDITIONS}
    runs: dict[str, list[Run]] = {c: [] for c in CONDITIONS[1:]}
    for case in m3.gold_cases(args.only):
        result, produce_s = await m3.plan_case(case, producer_llm)
        inp_base = pa.PlanInput(requirements=case["requirement_set"], report=result.report)
        per: dict[str, Any] = {}
        outputs: dict[str, Any] = {"base": (result.graph, inp_base.report, None)}
        for condition in CONDITIONS[1:]:
            inp = pa.PlanInput(requirements=case["requirement_set"], report=result.report)
            res, secs = await refine(pa.plan_critics(), pa.plan_reviser(), inp, result.graph, refine_llm, condition,
                                     "plan.generate")
            outputs[condition] = (res.final_output, inp.report_for(res.final_output), res)
            run = loop_stats(res, secs, condition)
            run.judge = {**judge_calibration_plan(res, case), **agreement(res)}
            runs[condition].append(run)
        for condition, (graph, report, res) in outputs.items():
            scored = m3.PlanResult(graph=graph, report=report, kind=result.kind)
            s = m3.score(case, scored, produce_s)
            a = agg[condition]
            a["deps"].add(s.deps)
            a["steps"].add(s.steps)
            a["must_ok"] += s.must_ok
            a["must_total"] += s.must_total
            a["valid"] += int(s.valid)
            a["coverage"] += s.coverage
            a["n"] += 1
            per[condition] = {"valid": s.valid, "coverage": s.coverage, "deps_f1": round(s.deps.f1, 3),
                              "deps_p": round(s.deps.precision, 3), "deps_r": round(s.deps.recall, 3),
                              "must": f"{s.must_ok}/{s.must_total}", "must_missed": s.must_missed,
                              "steps_f1": round(s.steps.f1, 3), "tasks": s.tasks}
            if res is not None:
                per[condition]["loop"] = runs[condition][-1].__dict__
        cases_out[case["id"]] = per
        line = " ".join(f"{c}: deps {per[c]['deps_f1']:.2f} must {per[c]['must']}" for c in CONDITIONS)
        print(f"{case['id']:<14} {line}", flush=True)
    summary = {}
    for c in CONDITIONS:
        a = agg[c]
        summary[c] = {"validity": round(a["valid"] / max(1, a["n"]), 3),
                      "coverage": round(a["coverage"] / max(1, a["n"]), 3),
                      "dependencies": {"precision": round(a["deps"].precision, 3),
                                       "recall": round(a["deps"].recall, 3), "f1": round(a["deps"].f1, 3)},
                      "must_edge_recall": round(a["must_ok"] / max(1, a["must_total"]), 3),
                      "steps_f1": round(a["steps"].f1, 3)}
        if c in runs:
            summary[c]["loop"] = aggregate(runs[c])
    return {"summary": summary, "cases": cases_out}


def aggregate(runs: list[Run]) -> dict[str, Any]:
    n = max(1, len(runs))
    stops: dict[str, int] = {}
    judge: dict[str, int] = {}
    strategies: dict[str, int] = {}
    for r in runs:
        stops[r.stop] = stops.get(r.stop, 0) + 1
        for k, v in r.judge.items():
            judge[k] = judge.get(k, 0) + v
        for s in r.strategies:
            strategies[s] = strategies.get(s, 0) + 1
    seconds = sorted(r.seconds for r in runs)
    return {"cases": len(runs), "iterations_mean": round(sum(r.iterations for r in runs) / n, 2),
            "tokens_total": sum(r.tokens for r in runs), "tokens_mean": round(sum(r.tokens for r in runs) / n),
            "calls_total": sum(r.calls for r in runs), "seconds_total": round(sum(seconds), 1),
            "seconds_median": seconds[len(seconds) // 2] if seconds else 0.0, "stop_reasons": stops,
            "improved": sum(1 for r in runs if (r.best_score or 0) > (r.base_score or 0)),
            "score_base_mean": round(sum(r.base_score or 0 for r in runs) / n, 3),
            "score_best_mean": round(sum(r.best_score or 0 for r in runs) / n, 3),
            "judge": judge, "strategies": strategies, "errors": [e for r in runs for e in r.errors]}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=("extraction", "plan", "all"), default="all")
    ap.add_argument("--producer", choices=("replay", "rules", "local"), default="replay")
    ap.add_argument("--mode", choices=("replay", "record", "live"), default="replay",
                    help="refine model calls: replay (default; HMAP_LLM_RECORD_MISSING=refine fills gaps), record, "
                         "live")
    ap.add_argument("--refine-local", action="store_true", help="refine with the local model only (never recorded)")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--name")
    args = ap.parse_args()
    if args.refine_local and args.mode == "record":
        ap.error("never record local-only runs: replay keys do not include the model (use --mode live)")
    refine_llm = gateway(args.mode, "refine", local_only=args.refine_local)
    out: dict[str, Any] = {"producer": args.producer, "mode": args.mode, "refine_local": args.refine_local}
    if args.suite in ("extraction", "all"):
        print("== extraction (Member 2 gold set)")
        out["extraction"] = await extraction_suite(args, refine_llm)
        print(json.dumps(out["extraction"]["summary"], indent=1))
    if args.suite in ("plan", "all"):
        print("== plan (Member 3 gold set)")
        out["plan"] = await plan_suite(args, refine_llm)
        print(json.dumps(out["plan"]["summary"], indent=1))
    name = args.name or f"{args.producer}" + ("-local" if args.refine_local else "") + \
        (f"-{args.suite}" if args.suite != "all" else "")
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(f"wrote {(RESULTS / f'{name}.json').relative_to(REPO_ROOT)}")
    if isinstance(refine_llm, Gateway):
        await refine_llm.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
