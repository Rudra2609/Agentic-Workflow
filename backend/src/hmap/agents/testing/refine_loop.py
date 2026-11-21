"""The code -> test -> revise loop with Member 7 (Sprint 8 item 8.9, plan D10).

After a ``test.run`` the hook asks :func:`decide`: revise or stop. Stop rules = Member 4's policies over the loop's
pass ratios (one score per round): ``TestsPass`` (the report passed), ``MaxIters(HMAP_TESTING_MAX_ROUNDS)``, and
no progress: the last revision neither raised the pass ratio nor changed which tests fail (a plain ``Plateau`` on
the ratio alone stops too early: a fix that turns "cannot connect" into "wrong reply" is progress at the same
ratio). Only actionable failures start a revision: not LINT (style), not ENV (the sandbox), not flaky, not only from
generated tests (they may be wrong themselves, research §2).

A revision is two tasks: ``code.revise`` (Member 7's agent; ``revision_inputs`` + the report in ``artifact_refs``,
parent = the coding task) and a new ``test.run`` that depends on it, carrying ``inputs.loop`` (round + history).
"""

from dataclasses import dataclass

from hmap.agents.refine.stop import LoopState as StopState
from hmap.agents.refine.stop import MaxIters, TestsPass, any_of
from hmap.agents.testing.model import FailureRecord, TestingTrace

ACTIONABLE = ("SYNTAX", "IMPORT", "ASSERTION", "TIMEOUT", "CRASH", "SECURITY")
MAX_CHANGES = 8


@dataclass
class Decision:
    revise: bool
    reason: str
    required_changes: list[str]


def actionable(failures: list[FailureRecord]) -> list[FailureRecord]:
    return [f for f in failures if f.category in ACTIONABLE and not f.flaky and not f.generated and not f.fuzz]


def signature(failures: list[FailureRecord]) -> list[str]:
    return sorted(f"{f.category}|{f.test or f.file}|{f.message[:120]}" for f in actionable(failures))


def required_changes(failures: list[FailureRecord]) -> list[str]:
    out = []
    for f in actionable(failures)[:MAX_CHANGES]:
        detail = f.message.split(": ", 1)[1] if f.test and f.message.startswith(f"{f.test}: ") else f.message
        where = f"{f.file}:{f.line}" if f.file and f.line else (f.file or f.stage)
        test = f" in test {f.test}" if f.test else ""
        hint = f" Hint: {f.hint}" if f.hint else ""
        out.append(f"fix the {f.category} failure{test} at {where}: {detail[:300]}.{hint}"[:500])
    return out


def decide(trace: TestingTrace, *, enabled: bool, max_rounds: int) -> Decision:
    if not enabled:
        return Decision(False, "automatic revision is off (HMAP_TESTING_AUTO_REVISE=false)", [])
    if trace.passed:
        return Decision(False, "tests pass", [])
    if not trace.coding_task_id or trace.changeset_ref is None:
        return Decision(False, "no coding step to revise (the tested code has no change set)", [])
    todo = actionable(trace.failures)
    if not todo:
        return Decision(False, "no actionable failure (only lint, flaky, generated-test or sandbox problems)", [])
    state = StopState()
    for score in [*trace.loop.history, trace.pass_ratio]:
        state = state.record(score)
    policy = any_of(TestsPass(lambda _out: trace.passed), MaxIters(max_rounds))
    reason: str | None = policy.check(state)
    if reason is None and trace.loop.history and trace.pass_ratio <= trace.loop.history[-1] + 0.01 \
            and signature(trace.failures) == sorted(trace.loop.last_failures):
        reason = "no_progress"
    if reason is not None:
        return Decision(False, f"loop stopped: {reason} (round {trace.loop.round}, pass ratios "
                               f"{[round(s, 2) for s in state.scores]})", [])
    return Decision(True, f"{len(todo)} actionable failures", required_changes(trace.failures))
