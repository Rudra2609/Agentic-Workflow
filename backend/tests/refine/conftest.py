"""Shared helpers for the refinement tests: scripted critics / revisers, and gold outputs made by Members 2 and 3's
rule-based fallbacks (no model, no network)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from hmap.agents.refine.core import Attempt, Critique, Issue, RefineContext, Revision, Strategy


def issue(category: str = "OMISSION", severity: str = "major", location: str | None = "/items",
          description: str = "something is missing", evidence: str | None = None) -> Issue:
    return Issue(category=category, severity=severity, description=description,  # type: ignore[arg-type]
                 location=location, evidence=evidence)


@dataclass
class ScriptedCritic:
    """Returns the scripted critiques in order (the last one repeats)."""

    critiques: list[Critique]
    name: str = "scripted"
    kind: Literal["programmatic", "llm"] = "programmatic"
    covers: frozenset[str] = frozenset()
    calls: int = 0

    async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique:
        c = self.critiques[min(self.calls, len(self.critiques) - 1)]
        self.calls += 1
        ctx.cancelled()
        return c


@dataclass
class ScoreByOutput:
    """Score = a table lookup on the output (a number); a minor issue while below 0.9 (minor: it does not cap the
    composite score)."""

    table: dict[Any, float]
    name: str = "by-output"
    kind: Literal["programmatic", "llm"] = "programmatic"
    covers: frozenset[str] = frozenset()

    async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique:
        score = self.table.get(output, 0.0)
        issues = [] if score >= 0.9 else [issue(severity="minor")]
        return Critique(score=score, issues=issues, critic=self.name)


@dataclass
class CountingReviser:
    """Output n -> n + 1; records the strategy it was asked for."""

    name: str = "counter"
    strategies: list[str] = field(default_factory=list)

    async def revise(self, output: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *,
                     task_input: Any = None, strategy: Strategy = "targeted") -> Revision:
        self.strategies.append(strategy)
        return Revision(output=output + 1, notes=[f"{output} -> {output + 1}"], applied=1)


_EXTRACTIONS: dict[str, tuple[Any, Any]] = {}
_PLANS: dict[str, tuple[Any, Any, Any]] = {}


async def rules_extraction(case_id: str) -> tuple[Any, Any]:
    """(RequirementSet, DocumentModel) from Member 2's rule pass on a gold document (cached per session)."""
    if case_id not in _EXTRACTIONS:
        from hmap.agents.doc_intel.cache import MemoryCache
        from hmap.agents.doc_intel.pipeline import run_pipeline
        from tests.doc_intel.eval.run_eval import gold_cases, inputs_for

        case = gold_cases([case_id])[0]
        result = await run_pipeline(f"P-{case_id}", inputs_for(case), None, cache=MemoryCache(), use_llm=False)
        _EXTRACTIONS[case_id] = (result.requirement_set, result.document_model)
    return _EXTRACTIONS[case_id]


async def rules_plan(case_id: str) -> tuple[Any, Any, Any]:
    """(TaskGraph, PlanReport, RequirementSet) from Member 3's rule planner on a gold case (cached per session)."""
    if case_id not in _PLANS:
        from tests.planning.eval.run_eval import gold_cases, plan_case

        case = gold_cases([case_id])[0]
        result, _ = await plan_case(case, None)
        _PLANS[case_id] = (result.graph, result.report, case["requirement_set"])
    return _PLANS[case_id]
