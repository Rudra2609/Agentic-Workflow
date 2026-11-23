"""Loop guard for the review -> revise loop (Sprint 10 item 10.6, plan D10).

Member 4's ``MaxIters`` / ``Plateau`` / ``Budget`` work on scores; the review's rounds are compared by their
**failure signature** (sorted ``item:category``), so the rules here are on signatures, with Member 4's names:
round budget, plateau (the same failures as last round), oscillation (a failure set seen in an earlier round, not
the last), cost budget (judge + revision model calls).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: str | None = None


def signature(failures: list[tuple[str, str]]) -> list[str]:
    return sorted({f"{item}:{cat}" for item, cat in failures})


def check(sig: list[str], history: list[list[str]], *, round_: int, max_rounds: int, calls: int = 0,
          budget_calls: int = 0) -> StopDecision:
    if not sig:
        return StopDecision(False)
    if history and sig == history[-1]:
        return StopDecision(True, "plateau: the same failures as the last round (the fix did not help)")
    if sig in history[:-1]:
        return StopDecision(True, "oscillation: this set of failures came back from an earlier round")
    if round_ >= max_rounds:
        return StopDecision(True, f"round budget: {max_rounds} revision round(s) used")
    if budget_calls and calls >= budget_calls:
        return StopDecision(True, f"cost budget: {calls} model calls")
    return StopDecision(False)
