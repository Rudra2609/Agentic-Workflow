"""The ≤ 10-line integration dry run for Member 5 (docs/members/4/integration.md), executed: a research agent that
opts in to refinement with a citation check and a rubric judge. Only the lines marked ``# +n`` are refinement code."""

import json
from typing import Any, ClassVar

from hmap.agents.refine import (
    Criterion,
    Issue,
    LLMRubricCritic,
    ProgrammaticCritic,
    RefinementMixin,
    RefineSetup,
    Rubric,
    TargetedReviser,
)
from hmap.agents.refine.critics.rubric import RubricAnswer
from hmap.agents.refine.revisers.targeted import PatchAnswer
from hmap.core.contracts import TaskAssign, TaskResult
from hmap.core.ids import new_execution_id, new_task_id
from hmap.core.llm import FakeLLM
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.services.artifact.memory import InMemoryArtifactStore
from hmap.services.context.memory import InMemoryContextStore

RESEARCH_RUBRIC = Rubric(name="research", subject="a short research report with cited claims", criteria=(
    Criterion("Q1", "Is every claim supported by one of the listed sources?", 1.0, "HALLUCINATION"),))


def check_citations(report: dict[str, Any], _input: Any) -> list[Issue]:
    return [Issue(category="OMISSION", severity="major", location=f"/claims/{i}", description="claim has no source",
                  fix_hint="add a source id") for i, c in enumerate(report["claims"]) if not c.get("sources")]


class ResearchAgent(RefinementMixin, BaseAgent):                                    # +1
    name = "research-dry-run"
    capabilities: ClassVar[tuple[str, ...]] = ("research.run",)

    def refine_setup(self, task: TaskAssign, ctx: AgentContext) -> RefineSetup:     # +2
        return RefineSetup(artifact_type="research-report", load=json.loads,       # +3
                           critics=[ProgrammaticCritic(check_citations),           # +4
                                    LLMRubricCritic(RESEARCH_RUBRIC)],             # +5
                           reviser=TargetedReviser())                              # +6

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        report = {"claims": [{"text": "TCP is reliable", "sources": ["S1"]}, {"text": "UDP is not", "sources": []}]}
        ref = await ctx.put_json(report, artifact_type="research-report")
        return await self.refine(task, ctx.result([ref]), ctx)                     # +7


async def test_member5_dry_run_in_seven_lines() -> None:
    llm = (FakeLLM(default=None)
           .on_schema(RubricAnswer, {"criteria": [{"id": "Q1", "score": 3}], "issues": []},
                      {"criteria": [{"id": "Q1", "score": 5}], "issues": []})
           .on_schema(PatchAnswer, {"patches": [{"op": "replace", "path": "/claims/1/sources",
                                                 "value_json": '["S2"]'}]}))
    task = TaskAssign(task_id=new_task_id(), execution_id=new_execution_id(), capability="research.run",
                      objective="research", acceptance_criteria=[], context_refs=[], project_id="P-DRY", refine=True)
    store = InMemoryArtifactStore()
    ctx = AgentContext(task=task, agent_id="research-1", llm=llm, artifacts=store, context=InMemoryContextStore(),
                       logger=None)
    result = await ResearchAgent().handle(task, ctx)
    report_ref, trace_ref = result.artifact_refs
    assert trace_ref.artifact_type == "refinement-trace" and report_ref.version == 2      # improved version stored
    assert json.loads(await store.get(report_ref, project_id="P-DRY"))["claims"][1]["sources"] == ["S2"]
    off = task.model_copy(update={"refine": False})                                     # off: nothing happens
    ctx_off = AgentContext(task=off, agent_id="research-1", llm=llm, artifacts=store, context=InMemoryContextStore(),
                           logger=None)
    assert [r.artifact_type for r in (await ResearchAgent().handle(off, ctx_off)).artifact_refs] == ["research-report"]
