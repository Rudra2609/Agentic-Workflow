"""Coverage tracking and stopping (Sprint 5 item 5.8, plan D10), built on Member 4's stop policies.

Coverage of a sub-question needs two independent sites: one site alone tops out at 75 % however many quotes it
gives (see :func:`coverage`). The round's score is the mean coverage.

    policy = research_policy(budget)      # any_of(AllCovered, LowNovelty, Budget(tokens, seconds), MaxIters(rounds))

Member 4's ``LoopState`` records one "attempt" per round, so ``MaxIters(max_rounds - 1)`` allows ``max_rounds``
rounds. The policies return Member 4's reason names; :func:`research_reason` maps them to the research ones
(``threshold`` -> ``all_covered``, ``plateau`` -> ``low_novelty``, ``max_iters`` -> ``max_rounds``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from hmap.agents.refine.core import StopReason
from hmap.agents.refine.stop import AnyOf, Budget, LoopState, MaxIters, any_of
from hmap.agents.research.model import EvidenceDraft
from hmap.core.contracts.domain import ResearchBudget, SubQuestion

COVERED = 0.99
NOVELTY_EPS = 0.1
HARD_MAX_ROUNDS = 6
REASONS = {"threshold": "all_covered", "plateau": "low_novelty", "max_iters": "max_rounds", "budget": "budget",
           "cancelled": "cancelled"}


def coverage(sub: SubQuestion, evidence: Sequence[EvidenceDraft]) -> float:
    """(sites + min(0.5, 0.25 x further quotes)) / 2, at most 1: an answer needs two independent sites - one site
    alone tops out at 75 % however many quotes it gives (one quote 50 %, two 62.5 %, three or more 75 %)."""
    mine = [e for e in evidence if e.sub_question == sub.id]
    if not mine:
        return 0.0
    hosts = len({e.host or e.url for e in mine})
    return round(min(1.0, (hosts + min(0.5, 0.25 * (len(mine) - hosts))) / 2), 3)


def update(subs: Sequence[SubQuestion], evidence: Sequence[EvidenceDraft], round_index: int,
           exhausted: set[str]) -> list[SubQuestion]:
    out: list[SubQuestion] = []
    for s in subs:
        c = coverage(s, evidence)
        status = "covered" if c >= COVERED else ("exhausted" if s.id in exhausted else
                                                ("partial" if c > 0 else "open"))
        out.append(s.model_copy(update={"coverage": c, "status": status}))
    return out


@dataclass(frozen=True)
class AllCovered:
    """Every sub-question is covered (the round's mean coverage reached ``COVERED``)."""

    theta: float = COVERED

    def check(self, state: LoopState) -> StopReason | None:
        return "threshold" if state.latest_score is not None and state.latest_score >= self.theta else None

    def describe(self) -> dict[str, Any]:
        return {"all_covered": self.theta}


@dataclass(frozen=True)
class LowNovelty:
    """The last round added less than ``eps`` of the evidence (after the first round), or nothing is left to
    search (every open sub-question has used all its queries)."""

    eps: float = NOVELTY_EPS

    def check(self, state: LoopState) -> StopReason | None:
        if state.extra.get("nothing_left"):
            return "plateau"
        novelty = state.extra.get("novelty")
        if state.attempts >= 2 and novelty is not None and novelty < self.eps:
            return "plateau"
        return None

    def describe(self) -> dict[str, Any]:
        return {"novelty_below": self.eps}


DEFAULT_MAX_TOKENS = 60_000


def research_policy(budget: ResearchBudget) -> AnyOf:
    """The default budget is in tokens (identical when a recorded run is replayed); a time limit applies only when
    the brief sets ``max_seconds`` — wall-clock time differs between recording and replay, so a default time cut
    would make replays take another path."""
    rounds = max(1, min(budget.max_rounds, HARD_MAX_ROUNDS))
    seconds = float(budget.max_seconds) if budget.max_seconds else None
    return any_of(AllCovered(), LowNovelty(), Budget(tokens=budget.max_tokens or DEFAULT_MAX_TOKENS, seconds=seconds),
                  MaxIters(rounds - 1))


def research_reason(reason: str | None) -> str:
    return REASONS.get(reason or "", reason or "max_rounds")
