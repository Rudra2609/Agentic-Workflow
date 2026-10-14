"""Refinement traces (Sprint 4 item 4.9, plan D4/D5).

- :func:`build_trace` -> the shared ``RefinementTrace`` contract (spec, iterations with scores / tokens / time,
  best iteration, stop reason).
- :class:`RefineRun` is the richer record the UI reads: everything in the trace (it validates as a
  ``RefinementTrace`` once stopped — consumers ignore the extra fields) plus each iteration's strategy, Reflexion note,
  per-critic scores, issues by category, the changes a guard refused and the taxonomy decisions.
- :class:`TraceRecorder` stores a run while it happens, as project artifacts (deleted with the project):
  ``refine-output`` (version *n* = the output of iteration *n-1*, so the UI can diff any two),
  ``refinement-progress`` (one version per iteration, status ``running``) and finally ``refinement-trace``
  (status ``stopped``). Each store is announced with ``ctx.progress(..., artifact_refs=[ref])``; the refine plug-in's
  ``task.progress`` hook turns that into ``refine.iteration`` / ``refine.stopped`` events (D5). The artifacts may quote
  the project's own document (an issue's evidence), like the requirement set itself; telemetry never does (D17).
"""

import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from hmap.agents.refine.core import (
    Attempt,
    Critique,
    RefinementIteration,
    RefinementSpec,
    RefinementTrace,
    StopReason,
    canonical,
)
from hmap.core.contracts import ArtifactRef
from hmap.obs import metrics as obs_metrics

OUTPUT_TYPE = "refine-output"
PROGRESS_TYPE = "refinement-progress"
TRACE_TYPE = "refinement-trace"


def build_trace(spec: RefinementSpec, attempts: Sequence[Attempt], best: int | None, reason: StopReason,
                output_refs: Sequence[ArtifactRef | None] | None = None) -> RefinementTrace:
    iterations = [RefinementIteration(index=a.index, critique=a.critique, score=a.score, tokens=a.tokens,
                                      duration_s=a.seconds,
                                      output_ref=output_refs[i] if output_refs and i < len(output_refs) else None)
                  for i, a in enumerate(attempts)]
    return RefinementTrace(spec=spec, iterations=iterations, best_iteration=best if attempts else None,
                           stop_reason=reason)


class CriticScore(BaseModel):
    critic: str
    score: float
    issues: int


class IterationRecord(BaseModel):
    """A ``RefinementIteration`` plus what the UI shows on an iteration card."""

    index: int
    output_ref: ArtifactRef | None = None
    critique: Critique
    score: float
    tokens: int = 0
    duration_s: float = 0.0
    strategy: str | None = None
    reflection: str | None = None
    revision_notes: list[str] = Field(default_factory=list)
    rejected_changes: list[str] = Field(default_factory=list)
    critics: list[CriticScore] = Field(default_factory=list)
    issues_by_category: dict[str, int] = Field(default_factory=dict)
    classifications: list[dict[str, Any]] = Field(default_factory=list)
    critic_errors: list[str] = Field(default_factory=list)      # LLM critics skipped this round (code checks only)


class RefineRun(BaseModel):
    """Artifact body of ``refinement-progress`` / ``refinement-trace``."""

    run_id: str
    project_id: str
    task_id: str | None = None
    capability: str | None = None
    subject: str = "result"
    status: Literal["running", "stopped"] = "running"
    spec: RefinementSpec
    iterations: list[IterationRecord] = Field(default_factory=list)
    best_iteration: int | None = None
    stop_reason: StopReason | None = None
    base_score: float | None = None
    best_score: float | None = None
    tokens: int = 0
    model_calls: int = 0
    seconds: float = 0.0
    started_at: datetime
    updated_at: datetime
    error: str | None = None
    applied: bool = False                       # the improved output replaced the original result
    output_artifact: dict[str, Any] | None = None   # {artifact_id, artifact_type, version} written for the task

    def to_trace(self) -> RefinementTrace:
        return RefinementTrace.model_validate(self.model_dump(mode="json"))


def iteration_record(a: Attempt, output_ref: ArtifactRef | None) -> IterationRecord:
    return IterationRecord(index=a.index, output_ref=output_ref, critique=a.critique, score=a.score, tokens=a.tokens,
                           duration_s=a.seconds, strategy=a.strategy, reflection=a.reflection,
                           revision_notes=a.revision_notes, rejected_changes=a.rejected_changes,
                           critics=[CriticScore(critic=p.critic or "?", score=p.score, issues=len(p.issues))
                                    for p in a.parts],
                           issues_by_category=a.issues_by_category(), classifications=a.classifications,
                           critic_errors=a.critic_errors)


def run_id_for(task_id: str | None, fallback: str) -> str:
    raw = f"rf-{task_id}" if task_id else f"rf-{fallback}"
    return re.sub(r"[^A-Za-z0-9_-]", "-", raw)[:120]


ProgressFn = Callable[..., Awaitable[None]]


class TraceRecorder:
    """``Refiner(on_attempt=recorder.on_attempt)``: stores outputs, progress and the final trace as they happen."""

    def __init__(self, artifacts: Any, project_id: str, *, run_id: str, spec: RefinementSpec,
                 task_id: str | None = None, capability: str | None = None, subject: str = "result",
                 created_by: str = "refine", progress: ProgressFn | None = None, usage: Any = None,
                 dump: Callable[[Any], Any] | None = None) -> None:
        self.artifacts, self.project_id = artifacts, project_id
        self.created_by, self.progress, self.usage = created_by, progress, usage
        self.dump = dump or (lambda o: o)
        now = datetime.now(UTC)
        self.run = RefineRun(run_id=run_id, project_id=project_id, task_id=task_id, capability=capability,
                             subject=subject, spec=spec, started_at=now, updated_at=now)
        self.output_refs: list[ArtifactRef] = []
        self.final_ref: ArtifactRef | None = None
        self.progress_ref: ArtifactRef | None = None

    async def _put(self, body: bytes, artifact_type: str, artifact_id: str) -> ArtifactRef:
        ref: ArtifactRef = await self.artifacts.put(body, project_id=self.project_id, artifact_type=artifact_type,
                                                    media_type="application/json", created_by=self.created_by,
                                                    artifact_id=artifact_id)
        return ref

    async def on_attempt(self, attempts: list[Attempt], reason: StopReason | None) -> None:
        for a in attempts[len(self.output_refs):]:
            self.output_refs.append(await self._put(canonical(self.dump(a.output)).encode(), OUTPUT_TYPE,
                                                    f"{self.run.run_id}-out"))
        run = self.run
        run.iterations = [iteration_record(a, self.output_refs[i]) for i, a in enumerate(attempts)]
        scores = [a.score for a in attempts]
        run.base_score = scores[0] if scores else None
        run.best_iteration = max(range(len(scores)), key=lambda i: (scores[i], -i)) if scores else None
        run.best_score = scores[run.best_iteration] if run.best_iteration is not None else None
        run.updated_at = datetime.now(UTC)
        if self.usage is not None:
            run.tokens, run.model_calls = self.usage.tokens, self.usage.calls
            run.seconds = round(self.usage.seconds, 3)
        if reason is None:
            self.progress_ref = await self._put(run.model_dump_json(indent=1).encode(), PROGRESS_TYPE,
                                                f"{run.run_id}-progress")
            await self._announce(min(99, 90 + len(attempts)), f"Checking the {run.subject}: iteration "
                                 f"{len(attempts) - 1}, score {scores[-1]:.2f}", self.progress_ref)

    async def finish(self, reason: StopReason, *, best: int, applied: bool,
                     output_artifact: ArtifactRef | None = None, error: str | None = None) -> ArtifactRef:
        run = self.run
        run.status, run.stop_reason, run.best_iteration = "stopped", reason, best if run.iterations else None
        run.applied, run.error = applied, error
        if output_artifact is not None:
            run.output_artifact = {"artifact_id": output_artifact.artifact_id,
                                   "artifact_type": output_artifact.artifact_type, "version": output_artifact.version}
        run.updated_at = datetime.now(UTC)
        if self.usage is not None:
            run.tokens, run.model_calls = self.usage.tokens, self.usage.calls
            run.seconds = round(self.usage.seconds, 3)
        run.to_trace()   # the stored record must validate as the shared contract
        self.final_ref = await self._put(run.model_dump_json(indent=1).encode(), TRACE_TYPE, run.run_id)
        cap = run.capability or "library"
        obs_metrics.REFINE_RUNS.labels(cap, reason).inc()
        obs_metrics.REFINE_ITERATIONS.labels(cap).inc(max(0, len(run.iterations) - 1))
        if run.base_score is not None and run.best_score is not None:
            obs_metrics.REFINE_GAIN.labels(cap).observe(run.best_score - run.base_score)
        gain = (f", score {run.base_score:.2f} -> {run.best_score:.2f}" if run.base_score is not None
                and run.best_score is not None else "")
        await self._announce(100, f"Checked the {run.subject}: {reason.replace('_', ' ')}{gain}", self.final_ref)
        return self.final_ref

    async def _announce(self, percent: int, summary: str, ref: ArtifactRef) -> None:
        if self.progress is not None:
            try:
                await self.progress(percent, summary, [ref])
            except TypeError:       # a progress callback without artifact refs (library use)
                await self.progress(percent, summary)
