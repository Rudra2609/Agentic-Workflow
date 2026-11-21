"""Static analysis (item 8.3): ruff with an explicit rule list (E4, E7, E9, F: syntax, undefined / unused names,
statement problems; defaults change between ruff versions) and mypy when the workspace configures it (Docker only:
mypy can load plug-ins named in that config). Findings are LINT (SYNTAX for E9); they never stop later stages."""

from hmap.agents.testing import analyze
from hmap.agents.testing.model import FailureRecord, StageRecord
from hmap.agents.testing.sandbox import RunResult, Step
from hmap.agents.testing.stages import View


def steps(view: View) -> list[Step]:
    if not view.py_files:
        return []
    out = [Step(stage="static", name="ruff", kind="ruff", timeout=min(30.0, view.stage_timeout))]
    if view.has_mypy_config:
        out.append(Step(stage="static", name="mypy", kind="mypy", timeout=min(90.0, view.stage_timeout * 1.5)))
    return out


def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]:
    ruff, mypy = run.get("ruff"), run.get("mypy")
    if ruff is None:
        return StageRecord(name="static", status="skipped", detail="no Python files"), []
    failures: list[FailureRecord] = []
    details = []
    seconds = ruff.seconds + (mypy.seconds if mypy else 0)
    for res, parse in ((ruff, analyze.parse_ruff), (mypy, analyze.parse_mypy)):
        if res is None:
            continue
        if res.unavailable:
            details.append(f"{res.name}: {res.unavailable}")
            continue
        if res.timed_out:
            failures.append(FailureRecord(stage="static", category="ENV", message=f"{res.name} timed out",
                                          hint="the static check did not finish; this is not a fault in the code"))
            continue
        found = parse(res.output)
        if res.exit_code not in (0, None) and not found and res.name == "ruff":
            details.append(f"ruff exit {res.exit_code}: {res.output.strip()[-200:]}")
        failures.extend(found)
    if view.backend == "local":
        details.append("local runner: ruff errors only (E9, F), no mypy")
    status = "failed" if failures else "passed"
    return StageRecord(name="static", status=status, duration_s=round(seconds, 3),
                       detail="; ".join(details)[:500]), failures
