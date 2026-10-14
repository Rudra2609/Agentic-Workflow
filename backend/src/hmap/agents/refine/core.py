"""Core abstractions of the refinement library (Sprint 4 item 4.1).

    produce -> critique (critics) -> classify issues (taxonomy) -> stop? -> revise (reviser) -> critique -> ...

- :class:`Critic` reviews an output and returns a :class:`Critique` ``{score 0..1, issues}``.
- :class:`Reviser` turns an output plus its critique into a new output (``revise``); it is told which *strategy* the
  loop wants (``targeted`` first; Reflexion switches to ``full`` / ``widen`` after repeated failures).
- :class:`~hmap.agents.refine.stop.StopPolicy` decides when to stop (``stop.py``).
- :class:`RefineContext` is what critics and revisers may use: the model client (with token / time accounting), the
  cancellation check, a cache, the reflection memory and a progress callback.
- :class:`RefinementResult` is what ``Refiner.run`` returns: the **best** output (not the last), every attempt, and the
  ``RefinementTrace`` contract.

``Issue``, ``Critique``, ``RefinementSpec`` and ``RefinementTrace`` are the shared contracts from
``hmap.core.contracts.domain`` (fixed in Sprint 1), re-exported here.
"""

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from hmap.core.contracts.domain import (
    Critique,
    Issue,
    IssueCategory,
    RefinementIteration,
    RefinementSpec,
    RefinementTrace,
    Severity,
)
from hmap.core.llm.base import ClassifyAnswer, ClassifyQuestion, LLMClient, LLMResponse, Message, Role

__all__ = [
    "CATEGORIES",
    "SEVERITIES",
    "SEVERITY_RANK",
    "Attempt",
    "CountingLLM",
    "Critic",
    "Critique",
    "Issue",
    "IssueCategory",
    "RefineContext",
    "RefinementIteration",
    "RefinementResult",
    "RefinementSpec",
    "RefinementTrace",
    "Reviser",
    "Revision",
    "Severity",
    "StopReason",
    "Strategy",
    "Usage",
    "canonical",
    "digest",
    "max_severity",
    "to_jsonable",
]

T = TypeVar("T", bound=BaseModel)

CATEGORIES: tuple[str, ...] = ("FORMAT", "SCHEMA", "OMISSION", "HALLUCINATION", "FACTUAL", "LOGIC",
                               "REQUIREMENT_VIOLATION", "CONSISTENCY", "STYLE", "SAFETY")
SEVERITIES: tuple[str, ...] = ("info", "minor", "major", "critical")
SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(SEVERITIES)}
StopReason = Literal["max_iters", "threshold", "no_critical_issues", "plateau", "budget", "tests_pass", "cancelled",
                     "error"]
Strategy = Literal["targeted", "full", "widen"]


def max_severity(issues: Sequence[Issue]) -> str | None:
    return max((i.severity for i in issues), key=SEVERITY_RANK.__getitem__, default=None)


def to_jsonable(output: Any) -> Any:
    """Outputs are pydantic models, dicts, lists or strings; the trace stores their JSON form."""
    if isinstance(output, BaseModel):
        return output.model_dump(mode="json")
    if isinstance(output, Mapping | list | tuple | str | int | float | bool) or output is None:
        return json.loads(json.dumps(output, default=str))
    return str(output)


def canonical(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(*parts: Any) -> str:
    """Short stable hash of outputs / rubrics / prompt versions (caching, plan D10)."""
    h = hashlib.sha256()
    for part in parts:
        h.update(canonical(part).encode())
        h.update(b"\x00")
    return h.hexdigest()[:24]


# ---------------------------------------------------------------------------------------------- accounting


@dataclass
class Usage:
    """Tokens and wall-clock time spent by one refinement loop (budget stop policy, trace)."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    cached_calls: int = 0
    started: float = field(default_factory=time.perf_counter)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def seconds(self) -> float:
        return time.perf_counter() - self.started

    def add(self, resp: LLMResponse) -> None:
        self.calls += 1
        self.cached_calls += int(resp.usage.cached)
        self.input_tokens += resp.usage.input_tokens
        self.output_tokens += resp.usage.output_tokens


ProgressFn = Callable[[int, str], Awaitable[None]]


class CountingLLM:
    """An ``LLMClient`` that adds every call's tokens to a :class:`Usage` — so calls made inside other members'
    functions (Member 3's ``replan``, Member 2's extraction) count against the loop's budget too."""

    def __init__(self, inner: LLMClient, usage: Usage) -> None:
        self.inner, self.usage = inner, usage

    async def generate(self, role: Role, messages: list[Message] | list[dict[str, str]], *,
                       schema: type[T] | None = None, max_tokens: int = 1024, temperature: float = 0.2,
                       think: bool = False, seed: int | None = None) -> LLMResponse:
        resp = await self.inner.generate(role, messages, schema=schema, max_tokens=max_tokens,
                                         temperature=temperature, think=think, seed=seed)
        self.usage.add(resp)
        return resp

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.inner.embed(texts)

    async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]:
        self.usage.calls += 1
        return await self.inner.classify(state, questions)

    async def read_images(self, prompt: str, images: list[bytes], *, max_tokens: int = 4096) -> LLMResponse:
        resp = await self.inner.read_images(prompt, images, max_tokens=max_tokens)
        self.usage.add(resp)
        return resp


@dataclass
class RefineContext:
    """What critics and revisers may use. Build one per loop (``RefineContext(llm=ctx.llm)``); everything is
    optional so the library also runs without a model (programmatic critics + rule revisers)."""

    llm: LLMClient | None = None
    check_cancelled: Callable[[], None] | None = None
    progress: ProgressFn | None = None
    memory: Any = None                       # hmap.agents.refine.reflexion.ReflectionMemory
    cache: dict[str, Any] = field(default_factory=dict)   # critic / reviser answers by content hash (D10)
    usage: Usage = field(default_factory=Usage)
    extras: dict[str, Any] = field(default_factory=dict)  # adapter-specific data (document model, requirements...)
    judge_role: Role = "judge"
    reviser_role: Role = "reasoner"

    def __post_init__(self) -> None:
        if self.llm is not None and not isinstance(self.llm, CountingLLM):
            self.llm = CountingLLM(self.llm, self.usage)

    def cancelled(self) -> None:
        """Raise :class:`~hmap.core.errors.Cancelled` if the surrounding task was cancelled."""
        if self.check_cancelled is not None:
            self.check_cancelled()

    @property
    def has_llm(self) -> bool:
        return self.llm is not None

    async def generate(self, role: Role, messages: list[Message], *, schema: type[T], max_tokens: int = 2048,
                       temperature: float = 0.0, seed: int | None = 7) -> T:
        """A schema-constrained model call, with its tokens counted against the loop's budget."""
        if self.llm is None:
            raise RuntimeError("this refinement step needs a model, but none is configured")
        self.cancelled()
        resp = await self.llm.generate(role, messages, schema=schema, max_tokens=max_tokens, temperature=temperature,
                                       seed=seed)
        parsed: T = resp.parsed
        return parsed

    async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]:
        if self.llm is None:
            raise RuntimeError("classification needs a model")
        self.cancelled()
        return await self.llm.classify(state, questions)


# ---------------------------------------------------------------------------------------------- protocols


@runtime_checkable
class Critic(Protocol):
    """Reviews one output. ``kind`` tells the composite whether its issues are verified facts (``programmatic``)
    or an opinion (``llm``)."""

    name: str
    kind: Literal["programmatic", "llm"]

    async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique: ...


@dataclass
class Revision:
    """A reviser's answer: the new output and what it changed (shown in the UI next to the diff)."""

    output: Any
    notes: list[str] = field(default_factory=list)
    applied: int = 0               # changes applied
    rejected: list[str] = field(default_factory=list)   # proposed changes refused by a guard, with the reason


@runtime_checkable
class Reviser(Protocol):
    """Turns ``output`` + its critique into a new output. ``history`` holds every earlier attempt (Reflexion notes
    included); ``strategy`` is ``targeted`` (only flagged parts), ``full`` (rewrite) or ``widen`` (look wider)."""

    name: str

    async def revise(self, output: Any, critique: Critique, history: Sequence["Attempt"], ctx: RefineContext, *,
                     task_input: Any = None, strategy: Strategy = "targeted") -> Revision: ...


# ---------------------------------------------------------------------------------------------- results


@dataclass
class Attempt:
    """One critiqued output (index 0 = the producer's output)."""

    index: int
    output: Any
    critique: Critique
    parts: list[Critique] = field(default_factory=list)         # one per critic
    tokens: int = 0
    seconds: float = 0.0
    strategy: str | None = None          # how this output was made from the previous one (None for index 0)
    reflection: str | None = None        # the Reflexion note written after this attempt failed
    revision_notes: list[str] = field(default_factory=list)
    rejected_changes: list[str] = field(default_factory=list)
    classifications: list[dict[str, Any]] = field(default_factory=list)   # taxonomy decisions (Sprint 11 data)
    critic_errors: list[str] = field(default_factory=list)  # LLM critics skipped this round ("judge: ReplayMissError")

    @property
    def score(self) -> float:
        return self.critique.score

    def issues_by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.critique.issues:
            out[i.category] = out.get(i.category, 0) + 1
        return out


@dataclass
class RefinementResult:
    final_output: Any
    best_index: int
    stop_reason: StopReason
    attempts: list[Attempt]
    trace: RefinementTrace
    usage: Usage
    error: str | None = None

    @property
    def base_score(self) -> float | None:
        return self.attempts[0].score if self.attempts else None

    @property
    def best_score(self) -> float | None:
        return self.attempts[self.best_index].score if self.attempts else None

    @property
    def improved(self) -> bool:
        return bool(self.attempts) and self.best_index > 0 and \
            self.attempts[self.best_index].score > self.attempts[0].score

    @property
    def iterations(self) -> int:
        """Revisions made (attempts after the first)."""
        return max(0, len(self.attempts) - 1)
