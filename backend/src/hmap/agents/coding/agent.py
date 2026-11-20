"""``CodingAgent`` (Sprint 7 item 7.9): the real ``code.implement`` and ``code.revise``.

Input (``TaskAssign``): ``objective`` + ``acceptance_criteria``; the project's latest ``requirement-set`` (the
requirements this step covers, ``inputs.requirement_ids``, else the first few) as context; ``inputs.workspace_ref``
(optional start tree); for ``code.revise``: ``inputs.revision_of`` (the ``code-change-set`` being revised),
``inputs.required_changes``, ``inputs.revision_round`` and any ``test-report`` / ``review-report`` in
``artifact_refs`` (see :mod:`.revise`). ``task.refine`` turns on the judge in the self-review.

Output: ``code-change-set`` ``ccs-<task_id>`` (first), ``workspace`` ``ws-<task_id>``, ``code-patch``
``patch-<task_id>``, ``coding-trace`` ``ct-<task_id>``; the project head ``wsh-<project_id>`` moves. Outcome
``success`` when every check passes, ``partial`` when the budget ran out with checks failing or no model answered
(the Manager treats ``partial`` as completed, so the pipeline continues and Member 8 sees what is not done),
``failure`` only when the workspace itself cannot be loaded or stored (the Manager's retry applies).

Idempotent: a redelivered execution whose trace is already ``done`` returns the stored artifacts. Failure-injection
inputs (``stub_fail``, ``stub_delay_s``) are honoured like the stub did.
"""

import asyncio
import json
from typing import Any, ClassVar

from hmap.agents.coding import debug, package, revise
from hmap.agents.coding.loop import CodingLoop, Job
from hmap.agents.coding.model import CodingTrace, changeset_id, patch_id, trace_id, workspace_id
from hmap.agents.coding.prompts import TaskView
from hmap.agents.coding.workspace import new_workspace, remove_workspace
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, TaskAssign, TaskResult
from hmap.core.contracts.capabilities import CODE_IMPLEMENT, CODE_REVISE
from hmap.core.errors import Cancelled
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.tracing import get_logger

log = get_logger("hmap.coding.agent")

TIME_LIMIT_S = 900          # safety abort only (decisions use steps and tokens: replay stays deterministic)
MAX_REQUIREMENTS = 8


async def failure_injection(task: TaskAssign, ctx: AgentContext) -> None:
    """The platform's test / demo hooks, only when a task asks for them (as the stub did)."""
    from hmap.agents.stubs.agents import MAX_DELAY_S, maybe_fail

    maybe_fail(task)
    delay = min(max(float(task.inputs.get("stub_delay_s") or 0), 0.0), MAX_DELAY_S)
    loop = asyncio.get_running_loop()
    end = loop.time() + delay
    while (left := end - loop.time()) > 0:
        ctx.check_cancelled()
        await asyncio.sleep(min(0.05, left))


async def requirements_for(task: TaskAssign, ctx: AgentContext) -> list[str]:
    """Texts of the requirements this step covers (+ technology constraints), from the latest requirement set."""
    refs = [r for r in await ctx.artifacts.list(ctx.project_id) if r.artifact_type == "requirement-set"]
    ref = max(refs, key=lambda r: (r.created_at, r.version), default=None)
    if ref is None:
        return []
    try:
        rs = json.loads(await ctx.artifacts.get(ref, project_id=ctx.project_id))
    except Exception:  # context only
        return []
    wanted = {str(x) for x in task.inputs.get("requirement_ids") or []}
    reqs = [r for r in rs.get("requirements", []) if not wanted or str(r.get("id")) in wanted]
    out = [f"{r.get('id', '')} {str(r.get('text', ''))[:200]}".strip() for r in reqs[:MAX_REQUIREMENTS]]
    out += [f"constraint: {str(c.get('text', ''))[:200]}" for c in rs.get("constraints", [])
            if c.get("kind") in ("technology", "format")][:3]
    return out


class CodingAgent(BaseAgent):
    name = "coding"
    capabilities: ClassVar[tuple[str, ...]] = (CODE_IMPLEMENT, CODE_REVISE)
    max_slots: ClassVar[int] = 1
    version: ClassVar[str] = "1.0"

    def __init__(self, settings: Settings | None = None, **deps: Any) -> None:
        self.settings = settings
        self.deps = deps                  # tests: options=Options(...)

    async def _existing(self, task: TaskAssign, ctx: AgentContext) -> list[ArtifactRef]:
        pid = ctx.project_id
        tr = await ctx.artifacts.latest(trace_id(task.task_id), project_id=pid)
        if tr is None:
            return []
        try:
            trace = CodingTrace.model_validate_json(await ctx.artifacts.get(tr, project_id=pid))
        except Exception:
            return []
        if trace.status != "done" or trace.execution_id != task.execution_id:
            return []
        refs = [await ctx.artifacts.latest(i, project_id=pid)
                for i in (changeset_id(task.task_id), workspace_id(task.task_id), patch_id(task.task_id))]
        return [r for r in refs if r is not None] + [tr] if all(refs) else []

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        await failure_injection(task, ctx)
        settings = self.settings or Settings.from_env()
        if existing := await self._existing(task, ctx):
            return ctx.result(existing, summary="code change already made for this execution (redelivered)")
        view = TaskView(objective=task.objective, criteria=list(task.acceptance_criteria),
                        requirements=await requirements_for(task, ctx),
                        required_changes=[str(c) for c in task.inputs.get("required_changes") or []][:20],
                        kind="revise" if task.capability == CODE_REVISE else "implement")
        known: list[debug.Failure] = []
        revision_of = task.inputs.get("revision_of")
        if task.capability == CODE_REVISE:
            ids = {str(task.inputs.get("original_task_id") or ""), task.task_id} - {""}
            changes, known = await revise.evidence_from_refs(task.artifact_refs, ctx, ids)
            view.required_changes = list(dict.fromkeys([*view.required_changes, *changes]))[:20]
        stored: package.Stored | None = None
        trace = self._trace(task, ctx, revision_of)
        for attempt in (1, 2):
            ws = new_workspace(settings, ctx.project_id, task.task_id, f"{task.execution_id}-{attempt}")
            try:
                base = await package.load_base(task, ctx, ws)
                trace.base, trace.base_ref = base.how, base.ref
                over = task.capability == CODE_REVISE and \
                    int(task.inputs.get("revision_round") or 1) > settings.coding_max_revisions
                if over:
                    trace.stop_reason, trace.outcome = "revision_limit", "partial"
                    trace.notes.append(f"revision limit reached ({settings.coding_max_revisions} rounds): no change")
                else:
                    await self._run_loop(task, ctx, settings, Job(
                        ws=ws, settings=settings, trace=trace, task=view, llm=ctx.llm, known_failures=known,
                        progress=self._progress(ctx, trace), cancelled=ctx.cancelled, use_judge=task.refine,
                        **({"options": self.deps["options"]} if "options" in self.deps else {})))
                stored = await package.store(task, ctx, ws, trace, base)
            finally:
                remove_workspace(ws, settings)
            if not stored.conflicts:
                break
            if attempt == 1:
                log.info("project head moved with conflicts; redoing the change on the new head",
                         task_id=task.task_id, files=stored.conflicts)
                trace = self._trace(task, ctx, revision_of)
                trace.notes.append(f"redone on the newer project head (conflicts in {', '.join(stored.conflicts)})")
                continue
            trace.outcome = "partial"
            trace.notes.append(f"conflicts with the project head in {', '.join(stored.conflicts)}: not merged")
        assert stored is not None
        log.info("coding done", task_id=task.task_id, outcome=trace.outcome, stop=trace.stop_reason,
                 steps=trace.model_calls, files=len(trace.files_changed))
        summary = (f"{len(trace.files_changed)} files changed; checks "
                   f"{'pass' if trace.checks_passed() else 'fail'}; stop: {trace.stop_reason}")
        return ctx.result(stored.refs, summary=summary, outcome=trace.outcome or "partial",
                          evidence=[json.dumps({"checks": {c.name: c.status for c in trace.checks},
                                                "model_calls": trace.model_calls, "tokens": trace.tokens})])

    @staticmethod
    def _trace(task: TaskAssign, ctx: AgentContext, revision_of: Any) -> CodingTrace:
        return CodingTrace(task_id=task.task_id, project_id=ctx.project_id, capability=task.capability,
                           execution_id=task.execution_id, objective=task.objective[:2000],
                           acceptance_criteria=list(task.acceptance_criteria)[:20],
                           revision_of=ArtifactRef.model_validate(revision_of) if isinstance(revision_of, dict)
                           else None, required_changes=[str(c) for c in task.inputs.get("required_changes") or []],
                           revision_round=int(task.inputs.get("revision_round") or 0),
                           original_task_id=str(task.inputs.get("original_task_id") or "") or None)

    @staticmethod
    def _progress(ctx: AgentContext, trace: CodingTrace) -> Any:
        async def report(percent: int, summary: str) -> None:
            ref = await ctx.put_json(trace, artifact_type="coding-trace", artifact_id=trace_id(trace.task_id))
            await ctx.progress(percent, summary, artifact_refs=[ref])
        return report

    @staticmethod
    async def _run_loop(task: TaskAssign, ctx: AgentContext, settings: Settings, job: Job) -> None:
        try:
            await asyncio.wait_for(CodingLoop(job).run(), timeout=TIME_LIMIT_S)
        except TimeoutError:
            job.trace.stop_reason, job.trace.outcome = "time_limit", "partial"
            job.trace.notes.append(f"stopped by the {TIME_LIMIT_S} s safety limit")
        except Cancelled:
            raise
