"""``RefineAgent`` (Sprint 4 item 4.12): the standalone ``refine.run`` capability, for the Manager (or a person, from
the Refinement tab) to check and improve an existing artifact.

Input: ``artifact_refs`` = the artifact to refine first (``inputs["artifact_id"]`` picks another), plus its context
(a ``requirement-set`` needs the ``document-model``; a ``task-graph`` needs the ``requirement-set`` and the
``plan-report``). ``inputs``: ``kind`` (``requirement-set`` | ``task-graph`` | ``generic``, default: the artifact's
type), ``rubric`` (generic: ``[{id, question, weight, category}]``), ``contract`` (generic: a ``DOMAIN_MODELS`` name
the result must validate as), ``stop_policy`` (``{"max_iters": 3, "threshold": 0.9, ...}``), ``reflexion`` (bool).

Output: the improved artifact (the next version of the same artifact, only when it scored higher) and a
``refinement-trace``. Idempotent: a redelivered task with the same input artifact and settings returns the stored
result without a second loop (in-memory cache by content hash, plan D10).
"""

import json
from collections import OrderedDict
from typing import Any, ClassVar

from hmap.agents.refine.adapters import extraction, plan
from hmap.agents.refine.core import Critique, RefineContext, digest
from hmap.agents.refine.critics import GENERIC_RUBRIC, Criterion, LLMRubricCritic, ProgrammaticCritic, Rubric
from hmap.agents.refine.integration import RefineSetup, refine_result
from hmap.agents.refine.revisers import SchemaReviser, StrategicReviser, TargetedReviser
from hmap.agents.refine.stop import policy_from_dict
from hmap.core.contracts import ArtifactRef, TaskAssign, TaskResult
from hmap.core.contracts.capabilities import REFINE_RUN
from hmap.core.contracts.domain import DOMAIN_MODELS, RequirementSet
from hmap.core.errors import ErrorCode, HmapError
from hmap.core.runtime.base import AgentContext, BaseAgent

CONTEXT_TYPES = {"document-model", "plan-report"}


def _invalid(message: str) -> HmapError:
    return HmapError(message, code=ErrorCode.INVALID_TASK, retryable=False)


def _rubric(raw: Any) -> Rubric:
    if not isinstance(raw, list) or not raw:
        return GENERIC_RUBRIC
    criteria = []
    for n, c in enumerate(raw[:8], start=1):
        if isinstance(c, dict) and str(c.get("question", "")).strip():
            criteria.append(Criterion(str(c.get("id") or f"C{n}"), str(c["question"])[:400],
                                      float(c.get("weight", 1.0)), str(c.get("category", "REQUIREMENT_VIOLATION"))))
    if not criteria:
        return GENERIC_RUBRIC
    return Rubric(name="custom", subject=GENERIC_RUBRIC.subject, criteria=tuple(criteria),
                  location_hint=GENERIC_RUBRIC.location_hint)


def generic_setup(artifact_type: str, contract: str | None, rubric: Rubric, objective: str,
                  stop: dict[str, Any] | None, reflexion: bool) -> RefineSetup:
    model = DOMAIN_MODELS.get(contract) if contract else None

    def load(data: bytes) -> Any:
        return model.model_validate_json(data) if model is not None else json.loads(data)

    def contract_check(output: Any, task_input: Any) -> Critique | list[Any]:
        if model is None:
            return []
        try:
            model.model_validate(output.model_dump() if hasattr(output, "model_dump") else output)
        except Exception as exc:
            from hmap.core.contracts.domain import Issue

            return [Issue(category="SCHEMA", severity="critical", location="/",
                          description=f"the result does not validate as {contract}", evidence=str(exc)[:200])]
        return []

    def render(output: Any, task_input: Any) -> str:
        from hmap.agents.refine.core import canonical

        return f"Objective: {task_input}\n\nResult (JSON):\n{canonical(output)}"

    targeted = TargetedReviser(load=model.model_validate if model is not None else None,
                               render_input=lambda i: f"Objective: {i}")
    revisers: dict[str, Any] = {"targeted": targeted}
    if model is not None:
        revisers["full"] = SchemaReviser(model, render_input=lambda i: f"Objective: {i}")
    return RefineSetup(artifact_type=artifact_type, load=load,
                       critics=[ProgrammaticCritic(contract_check, name="contract", covers={"SCHEMA"}),
                                LLMRubricCritic(rubric, render=render, name="judge")],
                       reviser=StrategicReviser(revisers), stop=policy_from_dict(stop), task_input=objective,
                       reflexion=reflexion, memory_key=f"refine.run:{artifact_type}", subject=artifact_type)


class _Lru:
    def __init__(self, size: int = 256) -> None:
        self.size, self.data = size, OrderedDict[str, list[dict[str, Any]]]()

    def get(self, key: str) -> list[dict[str, Any]] | None:
        if key in self.data:
            self.data.move_to_end(key)
            return self.data[key]
        return None

    def put(self, key: str, value: list[dict[str, Any]]) -> None:
        self.data[key] = value
        while len(self.data) > self.size:
            self.data.popitem(last=False)


class RefineAgent(BaseAgent):
    name = "refiner"
    capabilities = (REFINE_RUN,)
    max_slots = 1
    version = "4.0"
    done: ClassVar[_Lru] = _Lru()

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        inputs = task.inputs or {}
        refs = list(task.artifact_refs)
        wanted = inputs.get("artifact_id")
        target = next((r for r in refs if r.artifact_id == wanted), None) if wanted else \
            next((r for r in refs if r.artifact_type not in CONTEXT_TYPES), None)
        if target is None:
            raise _invalid("refine.run needs the artifact to refine in artifact_refs")
        kind = str(inputs.get("kind") or target.artifact_type)
        stop = inputs.get("stop_policy") if isinstance(inputs.get("stop_policy"), dict) else None
        reflexion = bool(inputs.get("reflexion", True))
        key = digest(ctx.project_id, target.sha256, kind, inputs.get("rubric"), inputs.get("contract"), stop, reflexion)
        if (cached := self.done.get(key)) is not None:
            return ctx.result([ArtifactRef.model_validate(r) for r in cached], summary="already checked (same input)")
        await ctx.progress(5, f"Checking the {kind}")
        setup = await self._setup(kind, target, refs, task, ctx, stop, reflexion)
        result = await refine_result(task, ctx.result([target], summary=f"checked {kind}"), ctx, setup)
        self.done.put(key, [r.model_dump(mode="json") for r in result.artifact_refs])
        return result

    async def _setup(self, kind: str, target: ArtifactRef, refs: list[ArtifactRef], task: TaskAssign,
                     ctx: AgentContext, stop: dict[str, Any] | None, reflexion: bool) -> RefineSetup:
        policy = policy_from_dict(stop)
        if kind == "requirement-set":
            dm = next((r for r in refs if r.artifact_type == "document-model"), None)
            if dm is None:
                raise _invalid("refining a requirement-set needs its document-model artifact")
            from hmap.agents.doc_intel.model import DocumentModel

            model = await ctx.get_json(dm, DocumentModel)
            return extraction.extraction_setup(extraction.build_input(model), stop=policy, reflexion=reflexion)
        if kind == "task-graph":
            rs = next((r for r in refs if r.artifact_type == "requirement-set"), None)
            report = next((r for r in refs if r.artifact_type == "plan-report"), None)
            if rs is None or report is None:
                raise _invalid("refining a task-graph needs its requirement-set and plan-report artifacts")
            from hmap.agents.planning.model import PlanReport

            inp = plan.PlanInput(requirements=await ctx.get_json(rs, RequirementSet),
                                 report=await ctx.get_json(report, PlanReport))
            return plan.plan_setup(inp, stop=policy, reflexion=reflexion)
        inputs = task.inputs or {}
        objective = task.objective + ("\nAcceptance criteria: " + "; ".join(task.acceptance_criteria)
                                      if task.acceptance_criteria else "")
        contract = inputs.get("contract") if isinstance(inputs.get("contract"), str) else None
        return generic_setup(target.artifact_type, contract, _rubric(inputs.get("rubric")), objective, stop,
                             reflexion)


__all__ = ["RefineAgent", "RefineContext", "generic_setup"]
