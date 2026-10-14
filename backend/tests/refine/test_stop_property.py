"""Property tests (item 4.6): whatever the policy and the scores, a loop terminates within the hard cap and returns
the best attempt (regression guard), never simply the last one."""

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hmap.agents.refine import RefineContext, Refiner
from hmap.agents.refine.core import Critique
from hmap.agents.refine.stop import (
    HARD_MAX_ITERS,
    Budget,
    LoopState,
    MaxIters,
    NoCritical,
    Plateau,
    Threshold,
    all_of,
    any_of,
    best_index,
)
from tests.refine.conftest import CountingReviser, issue

scores = st.lists(st.floats(min_value=0.0, max_value=1.0, allow_nan=False), min_size=1, max_size=30)
leaf = st.one_of(
    st.builds(MaxIters, st.integers(min_value=0, max_value=15)),
    st.builds(Threshold, st.floats(min_value=0.0, max_value=1.5, allow_nan=False)),
    st.builds(NoCritical, st.sampled_from(["minor", "major", "critical"])),
    st.builds(Plateau, st.floats(min_value=0.0, max_value=0.5, allow_nan=False), st.integers(min_value=1, max_value=4)),
    st.builds(Budget, st.one_of(st.none(), st.integers(min_value=0, max_value=5000)), st.none()),
)
policies = st.recursive(leaf, lambda inner: st.one_of(
    st.lists(inner, min_size=1, max_size=3).map(lambda ps: any_of(*ps)),
    st.lists(inner, min_size=1, max_size=3).map(lambda ps: all_of(*ps))), max_leaves=6)


class SequenceCritic:
    """Scores taken from a list (last one repeats); a major issue while the score is below 1."""

    kind = "programmatic"
    covers = frozenset()

    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.name = "seq"

    async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique:
        v = self.values[min(output, len(self.values) - 1)]
        return Critique(score=v, issues=[] if v >= 1.0 else [issue()], critic=self.name)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(values=scores, policy=policies)
async def test_every_loop_terminates_and_keeps_the_best(values: list[float], policy: Any) -> None:
    refiner = Refiner(critics=[SequenceCritic(values)], reviser=CountingReviser(), stop=policy)
    result = await refiner.run(None, RefineContext(), output=0)
    assert len(result.attempts) <= HARD_MAX_ITERS + 1
    seen = [a.score for a in result.attempts]
    assert result.best_index == best_index(seen)
    assert result.best_score == max(seen)
    assert result.final_output == result.attempts[result.best_index].output
    assert result.stop_reason in {"max_iters", "threshold", "no_critical_issues", "plateau", "budget"}
    # the trace says the same
    assert result.trace.best_iteration == result.best_index
    assert len(result.trace.iterations) == len(result.attempts)


@settings(max_examples=200, deadline=None)
@given(values=scores, policy=policies)
def test_policies_alone_never_crash_and_a_cap_always_ends_the_loop(values: list[float], policy: Any) -> None:
    capped = any_of(policy, MaxIters(HARD_MAX_ITERS))
    state = LoopState()
    for n, v in enumerate(values * 2):
        state = state.record(v, [issue()] if v < 1.0 else [])
        if capped.check(state) is not None:
            break
        assert n < HARD_MAX_ITERS
