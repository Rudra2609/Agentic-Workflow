"""Items 10.5 / 10.6 / 10.11: the 12 seeded failures of the golden scenario through the real modules — category and
responsible task, the minimal recovery plan, and the stop rules (plateau, oscillation, budget) — plus the checks
that the rules matter (the naive "first covering task" attribution gets scenarios wrong)."""

import pytest

from hmap.agents.review.stop import check, signature
from tests.review.helpers import run_scenario, scenarios

BASE, SCENARIOS = scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_seeded_scenario(scenario: dict) -> None:
    got = run_scenario(scenario, BASE)
    want = scenario["expect"]
    for key, value in want.items():
        assert got.get(key) == value, (key, got)


def test_naive_attribution_is_worse() -> None:
    wrong = [s["id"] for s in SCENARIOS
             if run_scenario(s, BASE, naive=True)["failures"] != s["expect"]["failures"]]
    assert {"client_side_bug", "untested_requirement"} <= set(wrong)


def test_stop_rules() -> None:
    a, b = signature([("R1", "INCORRECT")]), signature([("R2", "INCORRECT")])
    assert check(a, [a], round_=1, max_rounds=3).reason.startswith("plateau")  # type: ignore[union-attr]
    assert check(a, [a, b], round_=2, max_rounds=3).reason.startswith("oscillation")  # type: ignore[union-attr]
    assert check(a, [b], round_=2, max_rounds=2).reason.startswith("round budget")  # type: ignore[union-attr]
    assert check(a, [b], round_=1, max_rounds=3, calls=40, budget_calls=40).reason.startswith("cost")  # type: ignore[union-attr]
    assert not check(a, [b], round_=1, max_rounds=3).stop
    assert not check([], [a], round_=5, max_rounds=1).stop


def test_a_doc_mismatch_not_covered_by_a_docs_step_goes_to_the_docs_step() -> None:
    from hmap.agents.review.evidence import Bundle
    from hmap.agents.review.failure import attribute
    from hmap.agents.review.model import Check, Decided, Item, TaskInfo

    tasks = {"code": TaskInfo(task_id="code", plan_task_id="S", capability="code.implement"),
             "docs": TaskInfo(task_id="docs", plan_task_id="D", capability="docs.generate")}
    b = Bundle(items=[], tasks=tasks, graph=None, requirements=None, mode="software")
    d = Decided(item=Item(id="R9", text="Explain the design", covering=["code"]),
                check=Check(verdict="PARTIAL", category="DOC_MISMATCH"), verdict="PARTIAL")
    assert attribute(d, "DOC_MISMATCH", b)[:2] == ("docs", "docs.generate")
