"""Build / import (item 8.2): every Python file compiles, then every module of the code under test imports. A
failure here (SYNTAX, IMPORT, a crash at import time) skips the test stages: they would only repeat it."""

from hmap.agents.testing import analyze
from hmap.agents.testing.model import FailureRecord, StageRecord
from hmap.agents.testing.sandbox import RunResult, Step
from hmap.agents.testing.stages import View


def steps(view: View) -> list[Step]:
    if not view.py_files:
        return []
    out = [Step(stage="build", name="compile", kind="compile", args=view.py_files[:400],
                timeout=min(30.0, view.stage_timeout))]
    if view.modules:
        out.append(Step(stage="build", name="imports", kind="imports", args=view.modules[:60], needs=["compile"],
                        timeout=min(30.0, view.stage_timeout)))
    return out


def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]:
    comp, imp = run.get("compile"), run.get("imports")
    if comp is None:
        return StageRecord(name="build", status="skipped", detail="no Python files"), []
    failures = []
    for res in (comp, imp):
        if res is None or res.skipped or res.ok:
            continue
        if res.unavailable:
            failures.append(FailureRecord(stage="build", category="ENV", message=res.unavailable[:300],
                                          hint=analyze.rule_hint(FailureRecord(stage="build", category="ENV",
                                                                               message="x"))))
            continue
        failures.append(analyze.parse_traceback_output(res.output, "build", view.names, timed_out=res.timed_out,
                                                       timeout_s=30.0))
    seconds = comp.seconds + (imp.seconds if imp else 0)
    return StageRecord(name="build", status="failed" if failures else "passed", duration_s=round(seconds, 3),
                       detail=f"{len(view.py_files)} files, {len(view.modules)} modules"), failures
