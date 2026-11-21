"""Integration tests (item 8.5): tests in an ``integration`` folder / file name or marked
``pytest.mark.integration`` (e.g. a TCP server and N clients). They run in the same sandbox as everything else:
in Docker the run has its own network namespace with only loopback, so every run has private ports and nothing
can reach outside; on the local runner the macOS sandbox allows localhost only. Twice the unit time limit."""

from hmap.agents.testing.model import FailureRecord, StageRecord
from hmap.agents.testing.sandbox import RunResult, Step
from hmap.agents.testing.stages import View
from hmap.agents.testing.stages.unit import evaluate_tests, pytest_step


def steps(view: View) -> list[Step]:
    if not view.integration_tests:
        return []
    return [pytest_step(view, "integration", view.integration_tests, view.stage_timeout * 2)]


def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]:
    return evaluate_tests(view, run, "integration")
