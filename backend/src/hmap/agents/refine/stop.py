"""Stop policies (Sprint 4 item 4.6, plan D9): when does a refinement loop end?

A policy looks at the loop so far (:class:`LoopState`: the score and issues of every attempt, tokens and seconds
spent) and returns a stop reason or ``None`` (continue). Policies combine with :func:`any_of` / :func:`all_of`.
They are usable without a ``Refiner`` too (Members 7 and 8 drive their own code <-> test loops with them):

    policy = default_policy()                       # max 3 revisions, score >= 0.9, no major issue left,
    while True:                                     # plateau (gain < 0.02 twice), 20k tokens / 180 s
        state = state.record(score, issues)
        if (reason := policy.check(state)):
            break

Termination does not depend on the policy: ``Refiner`` also enforces a hard cap (``HARD_MAX_ITERS``), and
:func:`best_index` (the regression guard) always returns the best attempt, never simply the last one. Both are
checked by property tests (``tests/refine/test_stop_property.py``).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

from hmap.agents.refine.core import SEVERITY_RANK, Issue, StopReason

HARD_MAX_ITERS = 10   # revisions; no policy can make a loop run longer


@dataclass(frozen=True)
class LoopState:
    """Scores (0..1) and issues of every critiqued attempt so far (index 0 = the producer's output)."""

    scores: tuple[float, ...] = ()
    issues: tuple[tuple[Issue, ...], ...] = ()
    tokens: int = 0
    seconds: float = 0.0
    latest_output: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def attempts(self) -> int:
        return len(self.scores)

    @property
    def revisions(self) -> int:
        return max(0, len(self.scores) - 1)

    @property
    def latest_score(self) -> float | None:
        return self.scores[-1] if self.scores else None

    @property
    def latest_issues(self) -> tuple[Issue, ...]:
        return self.issues[-1] if self.issues else ()

    def record(self, score: float, issues: Sequence[Issue] = (), *, tokens: int | None = None,
               seconds: float | None = None, output: Any = None) -> "LoopState":
        return replace(self, scores=(*self.scores, float(score)), issues=(*self.issues, tuple(issues)),
                       tokens=self.tokens if tokens is None else tokens,
                       seconds=self.seconds if seconds is None else seconds, latest_output=output)


@runtime_checkable
class StopPolicy(Protocol):
    def check(self, state: LoopState) -> StopReason | None: ...

    def describe(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MaxIters:
    """Stop after ``n`` revisions (each revision costs about two model calls: critique + revise)."""

    n: int = 3

    def check(self, state: LoopState) -> StopReason | None:
        return "max_iters" if state.revisions >= self.n else None

    def describe(self) -> dict[str, Any]:
        return {"max_iters": self.n}


@dataclass(frozen=True)
class Threshold:
    """Stop when the latest score is at least ``theta``."""

    theta: float = 0.9

    def check(self, state: LoopState) -> StopReason | None:
        return "threshold" if state.latest_score is not None and state.latest_score >= self.theta else None

    def describe(self) -> dict[str, Any]:
        return {"threshold": self.theta}


@dataclass(frozen=True)
class NoCritical:
    """Stop when no issue of severity ``at_least`` or worse is left (default: nothing major or critical)."""

    at_least: str = "major"

    def check(self, state: LoopState) -> StopReason | None:
        if not state.scores:
            return None
        rank = SEVERITY_RANK[self.at_least]
        return None if any(SEVERITY_RANK[i.severity] >= rank for i in state.latest_issues) else "no_critical_issues"

    def describe(self) -> dict[str, Any]:
        return {"no_issues_at_least": self.at_least}


@dataclass(frozen=True)
class Plateau:
    """Stop when each of the last ``k`` revisions gained less than ``eps`` (a drop counts as no gain)."""

    eps: float = 0.02
    k: int = 2

    def check(self, state: LoopState) -> StopReason | None:
        s = state.scores
        if len(s) < self.k + 1:
            return None
        gains = [s[-j] - s[-j - 1] for j in range(1, self.k + 1)]
        return "plateau" if all(g < self.eps for g in gains) else None

    def describe(self) -> dict[str, Any]:
        return {"plateau_eps": self.eps, "plateau_k": self.k}


@dataclass(frozen=True)
class Budget:
    """Stop when the loop has used ``tokens`` model tokens or ``seconds`` of wall-clock time."""

    tokens: int | None = 20_000
    seconds: float | None = 180.0

    def check(self, state: LoopState) -> StopReason | None:
        if self.tokens is not None and state.tokens >= self.tokens:
            return "budget"
        if self.seconds is not None and state.seconds >= self.seconds:
            return "budget"
        return None

    def describe(self) -> dict[str, Any]:
        return {"budget_tokens": self.tokens, "budget_seconds": self.seconds}


@dataclass(frozen=True)
class TestsPass:
    """Stop when ``passes(latest_output)`` is true (Member 8's code <-> test loop: the tests are green)."""

    passes: Callable[[Any], bool]

    __test__ = False   # not a pytest class

    def check(self, state: LoopState) -> StopReason | None:
        if not state.scores:
            return None
        try:
            return "tests_pass" if self.passes(state.latest_output) else None
        except Exception:
            return None

    def describe(self) -> dict[str, Any]:
        return {"tests_pass": getattr(self.passes, "__name__", "fn")}


@dataclass(frozen=True)
class AnyOf:
    policies: tuple[StopPolicy, ...]

    def check(self, state: LoopState) -> StopReason | None:
        for p in self.policies:
            if (reason := p.check(state)) is not None:
                return reason
        return None

    def describe(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in self.policies:
            out.update(p.describe())
        return out


@dataclass(frozen=True)
class AllOf:
    """Stop only when every policy wants to stop; the reason is the last policy's."""

    policies: tuple[StopPolicy, ...]

    def check(self, state: LoopState) -> StopReason | None:
        reasons = [p.check(state) for p in self.policies]
        return reasons[-1] if reasons and all(r is not None for r in reasons) else None

    def describe(self) -> dict[str, Any]:
        return {"all_of": [p.describe() for p in self.policies]}


def any_of(*policies: StopPolicy) -> AnyOf:
    return AnyOf(tuple(policies))


def all_of(*policies: StopPolicy) -> AllOf:
    return AllOf(tuple(policies))


def default_policy(*, max_iters: int = 3, threshold: float = 0.9, at_least: str = "major", plateau_eps: float = 0.02,
                   plateau_k: int = 2, tokens: int | None = 20_000, seconds: float | None = 180.0) -> AnyOf:
    """Plan D9. Order matters only for the reported reason: a loop that reaches the threshold on its last allowed
    revision reports ``threshold``."""
    return any_of(Threshold(threshold), NoCritical(at_least), Plateau(plateau_eps, plateau_k),
                  Budget(tokens, seconds), MaxIters(max_iters))


def policy_from_dict(d: dict[str, Any] | None) -> AnyOf:
    """``RefinementSpec.stop_policy`` (``{"max_iters": 3, "threshold": 0.9, ...}``) -> a policy; missing keys take
    the defaults. Unknown keys are ignored."""
    d = d or {}
    return default_policy(max_iters=int(d.get("max_iters", 3)), threshold=float(d.get("threshold", 0.9)),
                          at_least=str(d.get("no_issues_at_least", "major")),
                          plateau_eps=float(d.get("plateau_eps", 0.02)), plateau_k=int(d.get("plateau_k", 2)),
                          tokens=d.get("budget_tokens", 20_000), seconds=d.get("budget_seconds", 180.0))


def best_index(scores: Sequence[float]) -> int | None:
    """Regression guard: the attempt to keep is the highest score; on a tie the EARLIER one (a revision must
    strictly improve to replace what we have)."""
    if not scores:
        return None
    best = 0
    for i, s in enumerate(scores):
        if s > scores[best]:
            best = i
    return best
