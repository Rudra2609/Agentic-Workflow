"""Stop policies and combinators (item 4.6)."""

from hmap.agents.refine.stop import (
    Budget,
    LoopState,
    MaxIters,
    NoCritical,
    Plateau,
    TestsPass,
    Threshold,
    all_of,
    any_of,
    best_index,
    default_policy,
    policy_from_dict,
)
from tests.refine.conftest import issue


def state(*scores: float, issues=None, tokens: int = 0, seconds: float = 0.0, output=None) -> LoopState:
    s = LoopState()
    for i, sc in enumerate(scores):
        s = s.record(sc, (issues or {}).get(i, ()), tokens=tokens, seconds=seconds, output=output)
    return s


def test_max_iters_counts_revisions() -> None:
    assert MaxIters(2).check(state(0.1)) is None
    assert MaxIters(2).check(state(0.1, 0.2)) is None
    assert MaxIters(2).check(state(0.1, 0.2, 0.3)) == "max_iters"
    assert MaxIters(0).check(state(0.1)) == "max_iters"


def test_threshold() -> None:
    assert Threshold(0.9).check(LoopState()) is None
    assert Threshold(0.9).check(state(0.89)) is None
    assert Threshold(0.9).check(state(0.5, 0.9)) == "threshold"


def test_no_critical_looks_at_the_latest_attempt_only() -> None:
    major = {0: (issue(severity="major"),), 1: (issue(severity="minor"),)}
    assert NoCritical("major").check(state(0.5, issues={0: major[0]})) is None
    assert NoCritical("major").check(state(0.5, 0.6, issues=major)) == "no_critical_issues"
    assert NoCritical("critical").check(state(0.5, issues={0: major[0]})) == "no_critical_issues"
    assert NoCritical().check(LoopState()) is None


def test_plateau_needs_k_small_gains_and_counts_drops() -> None:
    p = Plateau(eps=0.02, k=2)
    assert p.check(state(0.5, 0.51)) is None                      # one gain only
    assert p.check(state(0.5, 0.51, 0.515)) == "plateau"           # two gains < eps
    assert p.check(state(0.5, 0.6, 0.605)) is None                 # one big gain among the last two
    assert p.check(state(0.8, 0.7, 0.6)) == "plateau"              # regressions are "no gain"


def test_budget_tokens_and_seconds() -> None:
    assert Budget(1000, None).check(state(0.1, tokens=999)) is None
    assert Budget(1000, None).check(state(0.1, tokens=1000)) == "budget"
    assert Budget(None, 5).check(state(0.1, seconds=5.0)) == "budget"
    assert Budget(None, None).check(state(0.1, tokens=10**9, seconds=10**9)) is None


def test_tests_pass_uses_the_latest_output_and_survives_errors() -> None:
    assert TestsPass(lambda out: out == "green").check(state(0.2, output="green")) == "tests_pass"
    assert TestsPass(lambda out: out == "green").check(state(0.2, output="red")) is None
    assert TestsPass(lambda out: 1 / 0).check(state(0.2, output="x")) is None
    assert TestsPass(lambda out: True).check(LoopState()) is None


def test_any_of_reports_the_first_reason_and_all_of_needs_every_policy() -> None:
    s = state(0.95, 0.96, 0.961)
    assert any_of(Threshold(0.9), Plateau()).check(s) == "threshold"
    assert any_of(Plateau(), Threshold(0.9)).check(s) == "plateau"
    assert all_of(Threshold(0.9), MaxIters(5)).check(s) is None
    assert all_of(Threshold(0.9), MaxIters(2)).check(s) == "max_iters"


def test_default_policy_and_from_dict() -> None:
    d = default_policy().describe()
    assert d["max_iters"] == 3 and d["threshold"] == 0.9 and d["budget_tokens"] == 20000
    assert policy_from_dict({"max_iters": 1, "threshold": 0.5}).describe()["max_iters"] == 1
    assert policy_from_dict(None).describe() == d
    major = {i: (issue(severity="major"),) for i in range(4)}
    assert default_policy().check(state(0.1, 0.2, 0.3, 0.4, issues=major)) == "max_iters"
    assert default_policy().check(state(0.1)) == "no_critical_issues"      # nothing major left: stop at once


def test_best_index_keeps_the_best_and_the_earliest_on_ties() -> None:
    assert best_index([]) is None
    assert best_index([0.5, 0.9, 0.7]) == 1
    assert best_index([0.9, 0.9, 0.8]) == 0
    assert best_index([0.4, 0.3, 0.4]) == 0
