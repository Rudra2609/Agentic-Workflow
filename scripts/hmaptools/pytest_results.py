"""Tiny pytest plug-in (no dependencies): writes {nodeid: outcome} to $HMAP_RESULTS_JSON.

Loaded with ``-p hmaptools.pytest_results`` (PYTHONPATH must contain the scripts/ folder). Outcome per test is
"failed" if setup/call/teardown failed ("error" if only setup/teardown failed), "skipped" if skipped, else "passed".
"""

import json
import os
from typing import Any

_results: dict[str, str] = {}
_RANK = {"passed": 0, "skipped": 1, "error": 2, "failed": 3}


def pytest_runtest_logreport(report: Any) -> None:
    if report.passed and report.when != "call":
        outcome = "passed"
    elif report.failed:
        outcome = "failed" if report.when == "call" else "error"
    elif report.skipped:
        outcome = "skipped"
    else:
        outcome = "passed"
    prev = _results.get(report.nodeid)
    if prev is None or _RANK[outcome] > _RANK[prev]:
        _results[report.nodeid] = outcome


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    path = os.environ.get("HMAP_RESULTS_JSON")
    if path:
        with open(path, "w") as f:
            json.dump({"exitstatus": int(exitstatus), "results": _results}, f, indent=1, sort_keys=True)
