"""``PlanningAgent`` (spec item 3.8): the real ``plan.generate`` and ``plan.replan`` capabilities. The Sprint-1 stub
stands down automatically (this plug-in has a higher priority).

``plan.generate`` — input: the ``requirement-set`` artifact (plus Member 2's ``document-model`` for section names);
optional ``inputs["capabilities"]`` narrows the whitelist. Output: a ``task-graph`` artifact (version 1, first — the
``pipeline`` plug-in submits it for approval) and its ``plan-report`` (artifact id ``<graph id>-report``).

``plan.replan`` — input: the current ``task-graph`` and ``requirement-set`` artifacts; ``inputs``: ``feedback``,
``failed`` (plan task ids), ``states`` (plan task id -> Manager state). Output: the next version of the same
``task-graph`` artifact and its report; the planning plug-in's hook hands it to ``Manager.replace_graph``.

Idempotent on redelivery: model answers are cached by prompt (in memory, like Member 2's agent: cached text must
not outlive a deleted project on disk), so a second delivery makes no second model call.
"""

import json
from collections import OrderedDict
from typing import Any, ClassVar

from hmap.agents.planning.model import PlanReport
from hmap.agents.planning.pipeline import make_plan
from hmap.agents.planning.replan import replan
from hmap.core.contracts import ArtifactRef, TaskAssign, TaskResult
from hmap.core.contracts.capabilities import PLAN_GENERATE, PLAN_REPLAN
from hmap.core.contracts.domain import RequirementSet, TaskGraph
from hmap.core.errors import ErrorCode, HmapError
from hmap.core.runtime.base import AgentContext, BaseAgent

GRAPH_TYPE = "task-graph"
REPORT_TYPE = "plan-report"


def report_id(graph_artifact_id: str) -> str:
    return f"{graph_artifact_id}-report"


class LruCache:
    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self._data: OrderedDict[str, str] = OrderedDict()

    async def get(self, key: str) -> str | None:
        value = self._data.get(key)
        if value is not None:
            self._data.move_to_end(key)
        return value

    async def put(self, key: str, value: str) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)


class _ProjectCache:
    def __init__(self, shared: LruCache, project_id: str) -> None:
        self.shared, self.prefix = shared, f"{project_id}:"

    async def get(self, key: str) -> str | None:
        return await self.shared.get(self.prefix + key)

    async def put(self, key: str, value: str) -> None:
        await self.shared.put(self.prefix + key, value)


def _invalid(message: str) -> HmapError:
    return HmapError(message, code=ErrorCode.INVALID_TASK, retryable=False)


def _ref(refs: list[ArtifactRef], artifact_type: str) -> ArtifactRef | None:
    return next((r for r in refs if r.artifact_type == artifact_type), None)


class PlanningAgent(BaseAgent):
    name = "planner"
    capabilities = (PLAN_GENERATE, PLAN_REPLAN)
    max_slots = 2
    version = "3.0"
    cache: ClassVar[LruCache] = LruCache()

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        if task.capability == PLAN_REPLAN:
            return await self._replan(task, ctx)
        return await self._generate(task, ctx)

    async def _generate(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        rs_ref = _ref(task.artifact_refs, "requirement-set")
        if rs_ref is None:
            raise _invalid("plan.generate needs a requirement-set artifact")
        rs = await ctx.get_json(rs_ref, RequirementSet)
        dm_ref = _ref(task.artifact_refs, "document-model")
        document_model: dict[str, Any] | None = None
        if dm_ref is not None:
            document_model = json.loads(await ctx.artifacts.get(dm_ref, project_id=ctx.project_id))
        caps = (task.inputs or {}).get("capabilities")
        await ctx.progress(2, f"Planning {len(rs.requirements)} requirements")
        result = await make_plan(rs, ctx.llm, document_model=document_model,
                                 capabilities=caps if isinstance(caps, list) else None,
                                 cache=_ProjectCache(self.cache, ctx.project_id), progress=ctx.progress,
                                 check_cancelled=ctx.check_cancelled,
                                 requirement_set_ref={"artifact_id": rs_ref.artifact_id, "version": rs_ref.version})
        graph = result.graph.model_copy(update={"project_id": ctx.project_id})
        graph_ref = await ctx.put_json(graph, artifact_type=GRAPH_TYPE)
        report_ref = await ctx.put_json(result.report, artifact_type=REPORT_TYPE,
                                        artifact_id=report_id(graph_ref.artifact_id))
        await ctx.progress(100, "Plan ready")
        return ctx.result([graph_ref, report_ref], summary=_summary(graph, result.report), evidence=_evidence(
            result.report))

    async def _replan(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        graph_ref = _ref(task.artifact_refs, GRAPH_TYPE)
        rs_ref = _ref(task.artifact_refs, "requirement-set")
        if graph_ref is None or rs_ref is None:
            raise _invalid("plan.replan needs the current task-graph and requirement-set artifacts")
        current = await ctx.get_json(graph_ref, TaskGraph)
        rs = await ctx.get_json(rs_ref, RequirementSet)
        previous = None
        prev_ref = await ctx.artifacts.latest(report_id(graph_ref.artifact_id), project_id=ctx.project_id)
        if prev_ref is not None:
            previous = await ctx.get_json(prev_ref, PlanReport)
        inputs = task.inputs or {}
        states = {str(k): str(v) for k, v in (inputs.get("states") or {}).items()}
        failed = [str(x) for x in inputs.get("failed") or []]
        feedback = str(inputs.get("feedback") or "").strip() or None
        await ctx.progress(5, "Replanning" + (f": {feedback[:60]}" if feedback else ""))
        result = await replan(current, rs, states=states, feedback=feedback, failed=failed, llm=ctx.llm,
                              kind=previous.project_kind if previous else "software",
                              cache=_ProjectCache(self.cache, ctx.project_id), previous=previous)
        report = result.report.model_copy(update={
            "requirement_set": {"artifact_id": rs_ref.artifact_id, "version": rs_ref.version}})
        latest = await ctx.artifacts.latest(graph_ref.artifact_id, project_id=ctx.project_id)
        version = (latest.version if latest else graph_ref.version) + 1
        graph = result.graph.model_copy(update={"project_id": ctx.project_id, "version": version})
        new_ref = await ctx.put_json(graph, artifact_type=GRAPH_TYPE, artifact_id=graph_ref.artifact_id)
        report_ref = await ctx.put_json(report.model_copy(update={"graph_version": new_ref.version}),
                                        artifact_type=REPORT_TYPE, artifact_id=report_id(graph_ref.artifact_id))
        await ctx.progress(100, f"Plan version {new_ref.version} ready")
        return ctx.result([new_ref, report_ref], summary=_summary(graph, report), evidence=_evidence(report))


def _summary(graph: TaskGraph, report: PlanReport) -> str:
    s = report.schedule
    flagged = f"; {len(report.flagged)} requirement(s) need a person" if report.flagged else ""
    return (f"Plan v{graph.version}: {len(graph.tasks)} steps in {len(s.layers)} stages, about {s.total_effort:g} h "
            f"({report.method}){flagged}")


def _evidence(report: PlanReport) -> list[str]:
    return [f"method={report.method}", f"llm_calls={report.llm_calls}", f"repairs={len(report.repairs)}",
            f"flagged={len(report.flagged)}", f"critical_path={'>'.join(report.schedule.critical_path)}"]
