"""Unit tests (item 8.4): pytest over the workspace's tests (integration tests excluded), per-test results from
JUnit XML, coverage % of the code under test (Docker image only: ``coverage`` is not in the local coding venv).
Shared with :mod:`.integration`, which runs the same way with its own files and time limit."""

import json
import re

from hmap.agents.testing import analyze
from hmap.agents.testing.model import FailureRecord, StageRecord
from hmap.agents.testing.sandbox import RunResult, Step, StepResult
from hmap.agents.testing.stages import View


def pytest_step(view: View, stage: str, files: list[str], timeout: float, *, coverage: bool = False) -> Step:
    args = [*files, "-p", "no:randomly"]
    for node in view.deselect:
        args += ["--deselect", node]
    needs = ["compile", "imports"] if view.modules else ["compile"]
    return Step(stage=stage, name=stage, kind="pytest", args=args, timeout=timeout, needs=needs, coverage=coverage)


def steps(view: View) -> list[Step]:
    if not view.unit_tests:
        return []
    return [pytest_step(view, "unit", view.unit_tests, view.stage_timeout,
                        coverage=view.coverage and view.backend == "docker")]


def coverage_of(res: StepResult) -> float | None:
    raw = res.files.get(".cov.json")
    if not raw:
        return None
    try:
        return round(float(json.loads(raw)["totals"]["percent_covered"]), 1)
    except (ValueError, KeyError, TypeError):
        return None


def evaluate_tests(view: View, run: RunResult, stage: str) -> tuple[StageRecord, list[FailureRecord]]:
    res = run.get(stage)
    if res is None:
        return StageRecord(name=stage, status="skipped", detail="no tests"), []
    if res.skipped:
        return StageRecord(name=stage, status="skipped", detail="the code does not compile or import"), []
    if res.unavailable:
        f = FailureRecord(stage=stage, category="ENV", message=res.unavailable[:300])
        f.hint = analyze.rule_hint(f)
        return StageRecord(name=stage, status="error", detail=res.unavailable[:300]), [f]
    total, failed, failures, _ = analyze.parse_junit(res.files.get(".xml", ""), stage, view.names)
    if res.timed_out:
        f = FailureRecord(stage=stage, category="TIMEOUT", test=last_test(res.output),
                          message=f"the {stage} tests were killed after {res.seconds:.0f} s"[:300])
        f.hint = analyze.rule_hint(f, timeout_s=res.seconds)
        failures.append(f)
    elif res.exit_code not in (0, 5) and not failures:
        # pytest itself failed (usage error, internal error, collection crash without a report)
        failures.append(analyze.parse_traceback_output(res.output, stage, view.names))
    status = "failed" if failures else "passed"
    if res.exit_code == 5 and not failures:
        status, total = "skipped", 0
    rec = StageRecord(name=stage, status=status, duration_s=res.seconds, tests=total, tests_failed=failed,
                      detail=f"{total} tests, {failed} failed" if total else "no tests collected")
    return rec, failures


def last_test(output: str) -> str | None:
    """The test that was running when the stage was killed (pytest -q prints nothing per test; take the last
    node id it mentioned)."""
    found = re.findall(r"([\w./-]+\.py::[\w\[\]:.-]+)", output)
    return found[-1] if found else None


def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]:
    return evaluate_tests(view, run, "unit")
