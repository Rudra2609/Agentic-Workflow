"""The refinement loop (Sprint 4 item 4.2): Self-Refine, optionally with Reflexion.

    output = producer(input)                                  # or a given output (refine an existing result)
    loop:   critique = critics(output)                        # programmatic first, then the LLM rubric
            issues   = taxonomy(critique.issues)              # 10 categories x 4 severities
            stop?    = policy(scores, issues, tokens, time)   # threshold, no major issue, plateau, budget, max
            note     = reflexion(history) -> strategy         # optional: what failed, targeted -> full -> widen
            output   = reviser(output, critique, history, strategy)
    return the BEST attempt (regression guard), every attempt, the RefinementTrace contract

Deterministic with ``FakeLLM`` (no randomness of its own). Cancellation-aware: ``ctx.check_cancelled`` is called
between steps; a cancelled loop stops with ``stop_reason="cancelled"`` and still returns the best attempt so far.
A failing reviser or LLM critic ends the loop with ``stop_reason="error"`` (best attempt kept); only a failure before
the first critique propagates. ``HARD_MAX_ITERS`` caps every loop, whatever the policy.

    refiner = Refiner(producer=..., critics=[ProgrammaticCritic(check), LLMRubricCritic(RUBRIC)],
                      reviser=TargetedReviser(), stop=default_policy())
    result = await refiner.run(task_input, RefineContext(llm=ctx.llm))
"""

import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from hmap.agents.refine.core import (
    Attempt,
    Critic,
    Critique,
    RefineContext,
    RefinementResult,
    RefinementSpec,
    Reviser,
    StopReason,
    Strategy,
)
from hmap.agents.refine.critics.composite import CompositeCritic
from hmap.agents.refine.reflexion import ReflectionMemory
from hmap.agents.refine.stop import HARD_MAX_ITERS, LoopState, StopPolicy, best_index, default_policy
from hmap.agents.refine.taxonomy import IssueClassifier
from hmap.agents.refine.trace import build_trace
from hmap.core.errors import Cancelled
from hmap.core.tracing import get_logger
from hmap.obs import telemetry

log = get_logger("hmap.refine")

Producer = Callable[[Any, RefineContext], Awaitable[Any]]
OnAttempt = Callable[[list[Attempt], StopReason | None], Awaitable[None]]


class Refiner:
    def __init__(self, producer: Producer | None = None, critics: Sequence[Critic] | CompositeCritic = (),
                 reviser: Reviser | None = None, stop: StopPolicy | None = None,
                 memory: ReflectionMemory | None = None, *, classifier: IssueClassifier | None = None,
                 name: str = "refine", producer_name: str | None = None, on_attempt: OnAttempt | None = None,
                 hard_max_iters: int = HARD_MAX_ITERS) -> None:
        self.producer = producer
        self.critic = critics if isinstance(critics, CompositeCritic) else CompositeCritic(list(critics))
        self.reviser = reviser
        self.stop = stop or default_policy()
        self.memory = memory
        self.classifier = classifier or IssueClassifier()
        self.name = name
        self.producer_name = producer_name or getattr(producer, "__name__", None) or "given output"
        self.on_attempt = on_attempt
        self.hard_max_iters = max(0, min(hard_max_iters, HARD_MAX_ITERS))

    @property
    def spec(self) -> RefinementSpec:
        return RefinementSpec(producer=self.producer_name, critics=self.critic.names,
                              reviser=getattr(self.reviser, "name", "none") if self.reviser else "none",
                              stop_policy={**self.stop.describe(), "reflexion": self.memory is not None,
                                           "hard_max_iters": self.hard_max_iters})

    async def _critique(self, output: Any, task_input: Any, ctx: RefineContext,
                        errors: list[str]) -> tuple[Critique, list[Critique], list[dict[str, Any]]]:
        merged, parts = await self.critic.review_all(output, task_input, ctx, errors)
        programmatic = {c.name for c in self.critic.critics if c.kind == "programmatic"}
        issues = []
        decisions: list[dict[str, Any]] = []
        new_parts = []
        for part in parts:
            classified, made = await self.classifier.classify(part.issues, ctx, programmatic=part.critic in
                                                              programmatic)
            issues += classified
            decisions += [d.as_dict() for d in made]
            new_parts.append(part.model_copy(update={"issues": classified}))
        return merged.model_copy(update={"issues": issues}), new_parts, decisions

    async def _notify(self, attempts: list[Attempt], reason: StopReason | None) -> None:
        if self.on_attempt is None:
            return
        try:
            await self.on_attempt(attempts, reason)
        except Cancelled:
            raise
        except Exception as exc:  # a progress sink must never break the loop
            log.warning("refine progress callback failed", error=type(exc).__name__)

    async def run(self, task_input: Any, ctx: RefineContext | None = None, *, output: Any = None) -> RefinementResult:
        ctx = ctx or RefineContext()
        if self.memory is not None:
            ctx.memory = self.memory
            if not self.memory.loaded:
                await self.memory.load()
        usage = ctx.usage
        attempts: list[Attempt] = []
        state = LoopState()
        reason: StopReason | None = None
        error: str | None = None
        with telemetry.span(f"refine.loop {self.name}", attrs={"hmap.refine.critics": len(self.critic.critics),
                                                               "hmap.refine.reflexion": self.memory is not None}) as sp:
            if output is None:
                if self.producer is None:
                    raise ValueError("Refiner.run needs an output or a producer")
                output = await self.producer(task_input, ctx)
            strategy: Strategy | None = None
            notes: list[str] = []
            rejected: list[str] = []
            mark_tokens, mark_time = usage.tokens, time.perf_counter()
            try:
                for index in range(self.hard_max_iters + 1):
                    ctx.cancelled()
                    skipped: list[str] = []
                    critique, parts, decisions = await self._critique(output, task_input, ctx, skipped)
                    attempt = Attempt(index=index, output=output, critique=critique, parts=parts,
                                      tokens=usage.tokens - mark_tokens,
                                      seconds=round(time.perf_counter() - mark_time, 4), strategy=strategy,
                                      revision_notes=notes, rejected_changes=rejected, classifications=decisions,
                                      critic_errors=skipped)
                    attempts.append(attempt)
                    state = state.record(critique.score, critique.issues, tokens=usage.tokens, seconds=usage.seconds,
                                         output=output)
                    reason = self.stop.check(state)
                    if reason is None and (index >= self.hard_max_iters or self.reviser is None):
                        reason = "max_iters"
                    if reason is not None:
                        break
                    strategy = self.memory.choose_strategy(attempts) if self.memory is not None else "targeted"
                    if self.memory is not None:
                        attempt.reflection = await self.memory.reflect(attempts, ctx, strategy)
                    await self._notify(attempts, None)
                    ctx.cancelled()
                    mark_tokens, mark_time = usage.tokens, time.perf_counter()
                    assert self.reviser is not None
                    revision = await self.reviser.revise(output, critique, attempts, ctx, task_input=task_input,
                                                         strategy=strategy)
                    output, notes, rejected = revision.output, list(revision.notes), list(revision.rejected)
            except Cancelled:
                reason = "cancelled"
            except Exception as exc:
                if not attempts:
                    raise
                reason, error = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
                log.warning("refinement step failed; keeping the best attempt so far", error=type(exc).__name__)
            assert reason is not None
            best = best_index([a.score for a in attempts]) or 0
            if self.memory is not None:
                await self.memory.finish(attempts, best)
            trace = build_trace(self.spec, attempts, best, reason)
            result = RefinementResult(final_output=attempts[best].output, best_index=best, stop_reason=reason,
                                      attempts=attempts, trace=trace, usage=usage, error=error)
            sp.update({"hmap.refine.attempts": len(attempts), "hmap.refine.best": best, "hmap.refine.stop": reason,
                       "hmap.refine.base_score": result.base_score, "hmap.refine.best_score": result.best_score,
                       "hmap.refine.tokens": usage.tokens})
            await self._notify(attempts, reason)
        return result
