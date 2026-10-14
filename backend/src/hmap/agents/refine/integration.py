"""How agents opt in to refinement (Sprint 4 item 4.8, plan D1/D2).

Existing agents (Members 2 and 3) are refined **without touching their code**: the refine plug-in registers a
:class:`CapabilityAdapter` per capability in ``Plugin.refiners``; the agent runtime calls it with the agent's result
when the task has ``refine=true`` (the project setting, copied in by the Manager).

New agents (Members 5, 7, 9, ...) opt in from their own code — five lines (dry run: ``docs/members/4/integration.md``):

    class ResearchAgent(RefinementMixin, BaseAgent):
        def refine_setup(self, task, ctx):
            return RefineSetup(artifact_type="research-report", load=ResearchReport.model_validate_json,
                               critics=[ProgrammaticCritic(check_citations), LLMRubricCritic(RESEARCH_RUBRIC)],
                               reviser=TargetedReviser(load=ResearchReport.model_validate))
        # at the end of handle():  return await self.refine(task, ctx.result([ref]), ctx)

or decorate ``handle`` with ``@refinable(lambda agent, task, ctx: RefineSetup(...))``. Either way the result's
artifact of ``artifact_type`` is critiqued and revised; the best version is stored as the next version of the same
artifact (only if it scored higher), a ``refinement-trace`` artifact is added to the result, and nothing happens when
``task.refine`` is false. Use one mechanism per capability (an adapter in ``Plugin.refiners`` *or* the mixin).
"""

import functools
import inspect
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from hmap.agents.refine.core import Critic, RefineContext, RefinementResult, Reviser, to_jsonable
from hmap.agents.refine.refiner import Refiner
from hmap.agents.refine.reflexion import ArtifactMemoryStore, ReflectionMemory
from hmap.agents.refine.stop import StopPolicy
from hmap.agents.refine.trace import TraceRecorder, run_id_for
from hmap.core.contracts import ArtifactRef, TaskAssign, TaskResult
from hmap.core.errors import Cancelled
from hmap.core.runtime.base import AgentContext
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine.integration")

WriteFn = Callable[[Any, ArtifactRef, AgentContext], Awaitable[list[ArtifactRef]]]


@dataclass
class RefineSetup:
    """What to refine in a result and how."""

    artifact_type: str                                   # which artifact of the result to refine
    load: Callable[[bytes], Any]                         # artifact bytes -> the output object
    critics: Sequence[Critic]
    reviser: Reviser | None
    stop: StopPolicy | None = None                       # default: stop.default_policy()
    dump: Callable[[Any], Any] = to_jsonable             # output -> JSON (stored artifacts, diffs)
    task_input: Any = None                               # what critics / revisers check the output against
    reflexion: bool = True
    memory_key: str | None = None                        # default: "<capability>"
    subject: str = "result"                              # "requirements", "plan" (UI / progress wording)
    extras: dict[str, Any] = field(default_factory=dict)
    write: WriteFn | None = None                         # store the improved output; default: next version
    min_gain: float = 0.0                                # apply only if best - base > min_gain


async def write_next_version(output: Any, ref: ArtifactRef, ctx: AgentContext, dump: Callable[[Any], Any]) -> \
        list[ArtifactRef]:
    import json

    body = json.dumps(dump(output), indent=2, ensure_ascii=False).encode()
    new = await ctx.artifacts.put(body, project_id=ctx.project_id, artifact_type=ref.artifact_type,
                                  media_type=ref.media_type, created_by=ctx.agent_id, artifact_id=ref.artifact_id)
    return [new]


def _summary(result: TaskResult, res: RefinementResult, applied: bool) -> str:
    base, best = res.base_score or 0.0, res.best_score or 0.0
    how = (f"checked and improved: score {base:.2f} -> {best:.2f} in {res.iterations} round(s)" if applied
           else f"checked: score {base:.2f}, kept as is ({res.stop_reason.replace('_', ' ')})")
    return f"{result.summary}; {how}" if result.summary else how


async def refine_result(task: TaskAssign, result: TaskResult, ctx: AgentContext, setup: RefineSetup) -> TaskResult:
    """Critique and revise ``result``'s ``setup.artifact_type`` artifact; returns the result to report."""
    ref = next((r for r in result.artifact_refs if r.artifact_type == setup.artifact_type), None)
    if ref is None:
        log.info("nothing to refine: no artifact of the expected type", artifact_type=setup.artifact_type)
        return result
    output = setup.load(await ctx.artifacts.get(ref, project_id=ctx.project_id))
    rctx = RefineContext(llm=ctx.llm, check_cancelled=ctx.check_cancelled, extras=dict(setup.extras))
    memory = None
    if setup.reflexion:
        memory = ReflectionMemory(setup.memory_key or task.capability,
                                  ArtifactMemoryStore(ctx.artifacts, ctx.project_id, created_by=ctx.agent_id))
    refiner = Refiner(critics=setup.critics, reviser=setup.reviser, stop=setup.stop, memory=memory,
                      producer_name=f"{task.capability} agent", name=task.capability)
    recorder = TraceRecorder(ctx.artifacts, ctx.project_id, run_id=run_id_for(task.task_id, ref.artifact_id),
                             spec=refiner.spec, task_id=task.task_id, capability=task.capability,
                             subject=setup.subject, created_by=ctx.agent_id, progress=ctx.progress,
                             usage=rctx.usage, dump=setup.dump)
    refiner.on_attempt = recorder.on_attempt
    res = await refiner.run(setup.task_input, rctx, output=output)
    if ctx.cancelled.is_set():
        raise Cancelled("execution cancelled during refinement")
    gain = (res.best_score or 0.0) - (res.base_score or 0.0)
    applied = res.improved and gain > setup.min_gain
    new_refs = [ref]
    if applied:
        new_refs = await (setup.write(res.final_output, ref, ctx) if setup.write is not None
                          else write_next_version(res.final_output, ref, ctx, setup.dump))
    trace_ref = await recorder.finish(res.stop_reason, best=res.best_index, applied=applied,
                                      output_artifact=new_refs[0] if applied else None, error=res.error)
    refs: list[ArtifactRef] = []
    for r in result.artifact_refs:
        if r.artifact_id == ref.artifact_id and r.version == ref.version:
            refs += new_refs
        elif applied and any(r.artifact_id == n.artifact_id for n in new_refs):
            continue                                  # an older version of something the writer replaced
        else:
            refs.append(r)
    refs.append(trace_ref)
    evidence = [*result.evidence, f"refine_base_score={res.base_score}", f"refine_best_score={res.best_score}",
                f"refine_iterations={res.iterations}", f"refine_stop={res.stop_reason}", f"refine_applied={applied}"]
    return result.model_copy(update={"artifact_refs": refs, "summary": _summary(result, res, applied),
                                     "evidence": evidence})


SetupBuilder = Callable[[TaskAssign, TaskResult, AgentContext], Awaitable[RefineSetup | None]]


class CapabilityAdapter:
    """A ``RefineAdapter`` for ``Plugin.refiners`` (plan D1): builds the setup from the task and the agent's result
    (``None`` = nothing to refine) and runs :func:`refine_result`."""

    def __init__(self, build: SetupBuilder, *, name: str = "adapter") -> None:
        self.build = build
        self.name = name

    async def __call__(self, task: TaskAssign, result: TaskResult, ctx: AgentContext) -> TaskResult:
        setup = await self.build(task, result, ctx)
        if setup is None:
            return result
        return await refine_result(task, result, ctx, setup)


AgentSetup = Callable[[Any, TaskAssign, AgentContext], RefineSetup | Awaitable[RefineSetup | None] | None]


async def _resolve(setup: RefineSetup | Awaitable[RefineSetup | None] | None) -> RefineSetup | None:
    if inspect.isawaitable(setup):
        return await setup
    return setup


def refinable(make_setup: AgentSetup) -> Callable[[Callable[..., Awaitable[TaskResult]]],
                                                  Callable[..., Awaitable[TaskResult]]]:
    """Decorate ``BaseAgent.handle``: with ``task.refine`` the successful result is refined before it is returned."""

    def wrap(handle: Callable[..., Awaitable[TaskResult]]) -> Callable[..., Awaitable[TaskResult]]:
        @functools.wraps(handle)
        async def wrapper(agent: Any, task: TaskAssign, ctx: AgentContext) -> TaskResult:
            result = await handle(agent, task, ctx)
            if not task.refine or result.outcome != "success":
                return result
            setup = await _resolve(make_setup(agent, task, ctx))
            return result if setup is None else await refine_result(task, result, ctx, setup)

        return wrapper

    return wrap


class RefinementMixin:
    """Mix into a ``BaseAgent``; override :meth:`refine_setup`; end ``handle`` with
    ``return await self.refine(task, result, ctx)``."""

    def refine_setup(self, task: TaskAssign,
                     ctx: AgentContext) -> RefineSetup | Awaitable[RefineSetup | None] | None:
        return None

    async def refine(self, task: TaskAssign, result: TaskResult, ctx: AgentContext) -> TaskResult:
        if not task.refine or result.outcome != "success":
            return result
        setup = await _resolve(self.refine_setup(task, ctx))
        return result if setup is None else await refine_result(task, result, ctx, setup)
