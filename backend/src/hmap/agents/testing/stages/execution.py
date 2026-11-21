"""Execution (item 8.2, plan D5): run the program's entry point with a sample input, only when the task names one
(``inputs.entrypoint`` = ``"main.py --flag"``, ``inputs.sample_input`` = stdin text). Exit code 0 passes; for a
server (``inputs.long_running``) still running at the time limit also passes (it started and did not crash)."""

import shlex

from hmap.agents.testing import analyze
from hmap.agents.testing.model import FailureRecord, StageRecord
from hmap.agents.testing.sandbox import RunResult, Step
from hmap.agents.testing.stages import View

TIMEOUT_S = 10.0


def parse_entrypoint(raw: object) -> list[str]:
    if not raw:
        return []
    try:
        argv = [str(a) for a in raw] if isinstance(raw, list | tuple) else shlex.split(str(raw))
    except ValueError:
        return []
    if argv and argv[0] in ("python", "python3"):
        argv = argv[1:]
    return argv if argv and argv[0].endswith(".py") and not argv[0].startswith(("/", "..")) else []


def steps(view: View) -> list[Step]:
    if not view.entrypoint or view.entrypoint[0] not in view.files:
        return []
    return [Step(stage="execution", name="execution", kind="script", args=view.entrypoint, timeout=TIMEOUT_S,
                 needs=["compile"], stdin=view.sample_input)]


def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]:
    res = run.get("execution")
    if res is None:
        detail = "no entry point given" if not view.entrypoint else f"{view.entrypoint[0]} is not in the workspace"
        return StageRecord(name="execution", status="skipped", detail=detail), []
    if res.skipped:
        return StageRecord(name="execution", status="skipped", detail="the code does not compile"), []
    if res.ok or (res.timed_out and view.long_running):
        return StageRecord(name="execution", status="passed", duration_s=res.seconds,
                           detail="started and kept running" if res.timed_out else "exit code 0"), []
    if res.unavailable:
        f = FailureRecord(stage="execution", category="ENV", message=res.unavailable[:300])
        f.hint = analyze.rule_hint(f)
        return StageRecord(name="execution", status="error", detail=res.unavailable[:300]), [f]
    f = analyze.parse_traceback_output(res.output, "execution", view.names, timed_out=res.timed_out,
                                       timeout_s=TIMEOUT_S)
    return StageRecord(name="execution", status="failed", duration_s=res.seconds,
                       detail=f"exit code {res.exit_code}" if not res.timed_out else "timed out"), [f]
