"""``ReviewAgent`` (Sprint 10 item 10.8, plan D8): the real ``review.final`` (the stub stands down, priority 100).

assemble the evidence -> deterministic checks -> LLM judge for what they leave UNDECIDED -> aggregate (objective
first) -> rubric marks -> failure analysis (category + responsible task) -> the round's recovery plan + stop rules
-> ``ReviewReport``.

Inputs (all optional): ``project_tasks`` (the task table, from the recovery slot), ``review_round`` and
``previous_review`` (set by recovery for round N+1), ``change_requests`` (extra human requests to check).
Outputs: ``review-report`` ``rr-<task>`` (first), ``review-evidence`` ``rev-<task>``, ``review-trace``
``rtr-<task>``. Outcome ``success`` whatever the verdict (the report carries it; the recovery slot acts on it);
``partial`` without a requirement set; idempotent per execution.
"""

import time
from typing import Any, ClassVar

from hmap.agents.coding.agent import failure_injection
from hmap.agents.review import checks
from hmap.agents.review.aggregate import blocking, combine, completeness, score_criterion
from hmap.agents.review.evidence import assemble
from hmap.agents.review.failure import analyse
from hmap.agents.review.judge import Judge
from hmap.agents.review.model import (
    EVIDENCE_TYPE,
    REPORT_TYPE,
    TRACE_TYPE,
    Check,
    Decided,
    JudgeVote,
    ReviewTrace,
    Verdict,
    evidence_id,
    report_id,
    trace_id,
)
from hmap.agents.review.recovery import plan_round
from hmap.agents.review.stop import signature
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, ReviewReport, TaskAssign, TaskResult
from hmap.core.contracts.capabilities import REVIEW_FINAL
from hmap.core.contracts.domain import RequirementResult, ReviewFailure, RubricScore
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.tracing import get_logger

log = get_logger("hmap.review.agent")


async def review(task: TaskAssign, ctx: AgentContext, settings: Settings) -> tuple[ReviewReport, list[Decided],
                                                                                   ReviewTrace, Any]:
    """The whole review of one task, without writing anything (the eval and the demo call it too)."""
    started = time.monotonic()
    trace = ReviewTrace(task_id=task.task_id, project_id=ctx.project_id, execution_id=task.execution_id,
                        round=int(task.inputs.get("review_round") or 0))
    b = await assemble(task, ctx)
    trace.mode = b.mode  # type: ignore[assignment]
    trace.notes += b.notes
    trace.flagged_text = b.flagged
    prev = task.inputs.get("previous_review")
    if isinstance(prev, str) and prev:
        old = await ctx.artifacts.latest(trace_id(prev), project_id=ctx.project_id)
        if old is not None:
            try:
                o = ReviewTrace.model_validate_json(await ctx.artifacts.get(old, project_id=ctx.project_id))
                # a re-check (the work changed while the last review read it) is the same round: that review was
                # never acted on, so its failures are not "the last round" for the plateau rule
                stale = task.inputs.get("stale_of") == prev
                trace.history = list(o.history) if stale or not o.signature else [*o.history, o.signature]
            except Exception:
                trace.notes.append("previous review trace unreadable")
    judge = Judge(ctx.llm, samples=settings.review_judge_samples, budget=settings.review_budget_calls)
    decided: list[Decided] = []
    for item in [i for i in b.items if i.kind != "criterion"]:
        c = checks.run(item)
        jv: Verdict | None = None
        votes: list[JudgeVote] = []
        sensitive = False
        if c.verdict == "UNDECIDED" and judge.available:
            jv, votes, sensitive = await judge.verdict(item)
        verdict, source = combine(c.verdict, jv)
        rationale = votes[0].rationale if votes else "; ".join(c.reasons)
        if source == "none":
            rationale = "not judged (no model answered): " + "; ".join(c.reasons)
        decided.append(Decided(item=item, check=c, verdict=verdict, source=source,
                               rationale=rationale[:500], votes=votes, order_sensitive=sensitive))
        if sensitive:
            trace.order_sensitive.append(item.id)
    comp = completeness(decided)
    scores: list[RubricScore] = []
    for item in [i for i in b.items if i.kind == "criterion"]:
        level, why, _ = await judge.rubric_level(item)
        d = Decided(item=item, check=Check(verdict="UNDECIDED"), verdict="PARTIAL",
                    source="judge" if level else "none", level=level,
                    rationale=why or "estimated from the share of requirements met (no judge)")
        d.score = score_criterion(d, comp)
        decided.append(d)
        scores.append(RubricScore(criterion_id=item.id, score=d.score, max_marks=item.max_marks or 0.0))
    blocked = blocking(decided)
    failures = analyse(blocked, b)
    rp = plan_round(failures, decided, b, review_task_id=task.task_id, round_=trace.round, history=trace.history,
                    max_rounds=settings.review_max_rounds, min_confidence=settings.review_min_confidence,
                    calls=judge.calls, budget_calls=0)
    if b.requirements is None:     # nothing to judge (a goal-only or stub project): say so, do not hold it
        rp.recommendation = "PASS"
        trace.notes.append("no requirement set: nothing to review against (outcome partial)")
    trace.items = len(decided)
    for d in decided:
        trace.decided_by[d.source] = trace.decided_by.get(d.source, 0) + 1
    trace.judge_calls = judge.calls
    trace.judge_model_note = "role judge" + (f"; {judge.failed} call(s) failed or missed" if judge.failed else "")
    trace.failures = failures
    trace.signature = signature([(f.item_id, f.category) for f in failures if not f.no_action
                                 and f.item_id not in rp.waiting])
    trace.plan = {"actions": [p.model_dump() for p in rp.plans], "rerun": rp.rerun, "waiting": rp.waiting,
                  "stop_reason": rp.stop_reason}
    trace.completeness = comp
    trace.recommendation = rp.recommendation
    trace.stop_reason = rp.stop_reason
    report = ReviewReport(
        project_id=ctx.project_id,
        requirement_results=[RequirementResult(req_id=d.item.id, verdict=d.verdict, rationale=d.rationale,
                                               evidence=(d.check.reasons + d.item.evidence.facts)[:8])
                             for d in decided if d.item.kind != "criterion"],
        rubric_scores=scores,
        failures=[ReviewFailure(category=f.category, requirement_id=f.item_id, responsible_task_id=f.task_id,
                                description=f.why or f.category) for f in failures],
        revision_requests=rp.plans, overall=comp, recommendation=rp.recommendation)
    trace.seconds = round(time.monotonic() - started, 3)
    return report, decided, trace, b


class ReviewAgent(BaseAgent):
    name = "review"
    capabilities: ClassVar[tuple[str, ...]] = (REVIEW_FINAL,)
    max_slots: ClassVar[int] = 1
    version: ClassVar[str] = "1.0"

    def __init__(self, settings: Settings | None = None, **deps: Any) -> None:
        self.settings = settings
        self.deps = deps

    async def _existing(self, task: TaskAssign, ctx: AgentContext) -> list[ArtifactRef]:
        tr = await ctx.artifacts.latest(trace_id(task.task_id), project_id=ctx.project_id)
        if tr is None:
            return []
        try:
            trace = ReviewTrace.model_validate_json(await ctx.artifacts.get(tr, project_id=ctx.project_id))
        except Exception:
            return []
        if trace.status != "done" or trace.execution_id != task.execution_id:
            return []
        out = [await ctx.artifacts.latest(report_id(task.task_id), project_id=ctx.project_id),
               await ctx.artifacts.latest(evidence_id(task.task_id), project_id=ctx.project_id), tr]
        return [r for r in out if r is not None]

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        await failure_injection(task, ctx)
        settings = self.settings or Settings.from_env()
        if existing := await self._existing(task, ctx):
            return ctx.result(existing, summary="review already written for this execution (redelivered)")
        report, decided, trace, b = await review(task, ctx, settings)
        trace.status = "done"
        rep = await ctx.put_json(report, artifact_type=REPORT_TYPE, artifact_id=report_id(task.task_id))
        ev = await ctx.put_json({"items": [d.model_dump(mode="json") for d in decided], "mode": b.mode,
                                 "notes": b.notes, "artifacts_read": b.used,
                                 "tasks": [t.model_dump() for t in b.tasks.values()]},
                                artifact_type=EVIDENCE_TYPE, artifact_id=evidence_id(task.task_id))
        tr = await ctx.put_json(trace, artifact_type=TRACE_TYPE, artifact_id=trace_id(task.task_id))
        n_pass = sum(1 for d in decided if d.verdict == "PASS" and d.item.kind != "criterion")
        n = sum(1 for d in decided if d.item.kind != "criterion")
        summary = (f"review round {trace.round}: {report.recommendation} — {n_pass}/{n} PASS, "
                   f"{len(report.failures)} failure(s)" + (f"; stop: {trace.stop_reason}" if trace.stop_reason else ""))
        log.info("review done", task_id=task.task_id, recommendation=report.recommendation, passed=n_pass, items=n)
        outcome = "success" if b.requirements is not None else "partial"
        return ctx.result([rep, ev, tr], summary=summary, outcome=outcome)
