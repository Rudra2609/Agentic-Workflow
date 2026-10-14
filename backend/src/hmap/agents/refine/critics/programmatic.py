"""``ProgrammaticCritic``: wraps a check written in code — a schema validator, Member 3's DAG validator, a quote
matcher, a test runner. Its issues are facts, not opinions, so the composite lets them override an LLM critic
(plan D8, spec §3 "prefer external verifiers first").

    def no_empty_sections(report, task_input) -> list[Issue]: ...
    critic = ProgrammaticCritic(no_empty_sections, covers={"OMISSION"})

The check may be sync or async, take ``(output, task_input)`` or ``(output, task_input, ctx)``, and return a list
of issues (the score is then derived from their severities), a ``Critique``, or ``(score, issues)``.
"""

import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any, Literal

from hmap.agents.refine.core import Critique, Issue, RefineContext

# score lost per issue of each severity (1.0 = perfect); a critical issue alone halves the score
PENALTY: dict[str, float] = {"critical": 0.5, "major": 0.2, "minor": 0.05, "info": 0.0}

CheckResult = Sequence[Issue] | Critique | tuple[float, Sequence[Issue]]
CheckFn = Callable[..., CheckResult | Awaitable[CheckResult]]


def score_from_issues(issues: Iterable[Issue], penalty: Mapping[str, float] = PENALTY) -> float:
    return round(max(0.0, 1.0 - sum(penalty.get(i.severity, 0.0) for i in issues)), 4)


class ProgrammaticCritic:
    kind: Literal["programmatic", "llm"] = "programmatic"

    def __init__(self, fn: CheckFn, *, name: str | None = None, covers: Iterable[str] = (),
                 penalty: Mapping[str, float] = PENALTY, weight: float = 1.0) -> None:
        """``covers``: issue categories this check verifies completely. When it reports nothing in one of them,
        an LLM critic's issues in that category are dropped as contradicted (plan D8)."""
        self.fn = fn
        self.name: str = name or str(getattr(fn, "__name__", "check"))
        self.covers = frozenset(covers)
        self.penalty = dict(penalty)
        self.weight = weight
        self._wants_ctx = len(inspect.signature(fn).parameters) >= 3

    async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique:
        raw = self.fn(output, task_input, ctx) if self._wants_ctx else self.fn(output, task_input)
        if inspect.isawaitable(raw):
            raw = await raw
        if isinstance(raw, Critique):
            return raw.model_copy(update={"critic": raw.critic or self.name})
        if isinstance(raw, tuple):
            score, issues = raw
            return Critique(score=max(0.0, min(1.0, float(score))), issues=list(issues), critic=self.name)
        issues = list(raw)
        return Critique(score=score_from_issues(issues, self.penalty), issues=issues, critic=self.name)
