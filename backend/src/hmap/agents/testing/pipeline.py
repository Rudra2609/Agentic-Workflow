"""The stage pipeline (Sprint 8 item 8.2, plan D5, D7).

One sandbox run executes every stage's steps in order (static → build → unit → integration → security →
execution); a step that ``needs`` a failed step is skipped (no tests after a file that does not compile). Each stage
then turns its step results into a status and failures. Failed tests are re-run once in a fresh run: a test that
passes the second time is FLAKY (kept in the report, never sent to Member 7).
"""

import asyncio
import re
import time
from dataclasses import dataclass, field

from hmap.agents.testing import analyze
from hmap.agents.testing.model import STAGES, FailureRecord, StageRecord, StepRecord
from hmap.agents.testing.sandbox import Backend, RunResult, Step
from hmap.agents.testing.stages import View, build, execution, integration, node, security, static, unit
from hmap.agents.testing.stages.unit import pytest_step

MODULES = {"static": static, "build": build, "unit": unit, "integration": integration, "security": security,
           "execution": execution}
_NORMALISE = [
    (re.compile(r"/work/"), ""),
    (re.compile(r"<ws>/"), ""),
    (re.compile(r"(?<=\S) in \d+(?:\.\d+)?s( \([\d:]+\))?(?=\s|$)"), ""),
    (re.compile(r"(Ran \d+ tests?) in [\d.]+s"), r"\1"),
    (re.compile(r"0x[0-9a-fA-F]{6,}"), "0x?"),
    (re.compile(r"\btmp[a-z0-9_]{8}\b"), "tmpXXXXXXXX"),
    (re.compile(r"\bport \d{4,5}\b"), "port N"),
    (re.compile(r"\('127\.0\.0\.1', \d+\)"), "('127.0.0.1', N)"),
]


def normalise(text: str) -> str:
    """Replay-stable, path-free command output (what prompts and logs may contain)."""
    for pattern, repl in _NORMALISE:
        text = pattern.sub(repl, text)
    return text


@dataclass
class PipelineResult:
    backend: str
    stages: dict[str, StageRecord] = field(default_factory=dict)
    failures: list[FailureRecord] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)
    flaky: list[str] = field(default_factory=list)
    passed_tests: set[str] = field(default_factory=set)
    coverage: float | None = None
    tests: int = 0
    tests_failed: int = 0
    seconds: float = 0.0
    error: str | None = None

    @property
    def passed(self) -> bool:
        """No failure that counts: LINT findings, flaky tests and fuzz findings are reported but do not fail the run."""
        return self.error is None and not any(f.category != "LINT" and not f.flaky and not f.fuzz
                                              for f in self.failures)

    @property
    def pass_ratio(self) -> float:
        if self.tests:
            return round((self.tests - self.tests_failed) / self.tests, 4)
        return 1.0 if self.passed else 0.0

    def log_text(self) -> str:
        parts = [f"backend: {self.backend}"]
        for s in self.steps:
            status = "TIMED OUT" if s.timed_out else f"exit {s.exit_code}"
            parts.append(f"=== [{s.stage}] {s.name}: {s.cmd}\n[{status}, {s.duration_s:.1f} s]\n{s.output.rstrip()}")
        return "\n\n".join(parts) + "\n"


def dedupe(failures: list[FailureRecord]) -> list[FailureRecord]:
    """One failure per (category, file, line): ruff and py_compile both report the same syntax error."""
    seen: set[tuple[str, str | None, int | None]] = set()
    out = []
    for f in failures:
        key = (f.category, f.file, f.line)
        if f.file and f.line and key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def all_steps(view: View) -> list[Step]:
    if view.language == "js":
        return node.steps(view)
    return [step for name in STAGES for step in MODULES[name].steps(view)]


def record_steps(run: RunResult) -> list[StepRecord]:
    return [StepRecord(stage=s.stage, name=s.name, cmd=normalise(s.cmd)[:300], exit_code=s.exit_code,
                       timed_out=s.timed_out, duration_s=s.seconds,
                       output=normalise(s.output if not s.unavailable else f"not run: {s.unavailable}")[-16_000:])
            for s in run.steps if not s.skipped]


async def run_pipeline(view: View, backend: Backend, *, cancelled: asyncio.Event | None = None,
                       flaky_check: bool = True) -> PipelineResult:
    started = time.monotonic()
    run = await backend.run(view.files, all_steps(view), cancelled=cancelled, image=view.image)
    out = PipelineResult(backend=backend.name, steps=record_steps(run))
    if run.error:
        out.error = run.error
        f = FailureRecord(stage="build", category="ENV", message=run.error[:300])
        f.hint = analyze.rule_hint(f)
        out.failures.append(f)
        for name in STAGES:
            out.stages[name] = StageRecord(name=name, status="error", detail=run.error[:200])
        out.seconds = round(time.monotonic() - started, 3)
        return out
    js = node.evaluate(view, run) if view.language == "js" else {}
    for name in STAGES:
        rec, failures = js[name] if js else MODULES[name].evaluate(view, run)
        out.stages[name] = rec
        out.failures.extend(failures)
        if name in ("unit", "integration"):
            out.tests += rec.tests
            out.tests_failed += rec.tests_failed
    for name in ("unit", "integration"):
        res = run.get(name)
        if res is not None and res.files.get(".xml"):
            out.passed_tests |= analyze.passed_nodes(res.files[".xml"])
    unit_res = run.get("unit")
    if unit_res is not None:
        out.coverage = unit.coverage_of(unit_res)
    out.failures = dedupe(out.failures)
    for f in out.failures:
        f.message = normalise(f.message)
    if flaky_check:
        await recheck_flaky(view, backend, out, cancelled)
    out.seconds = round(time.monotonic() - started, 3)
    return out


async def recheck_flaky(view: View, backend: Backend, out: PipelineResult,
                        cancelled: asyncio.Event | None = None) -> None:
    """Re-run each failed test once; pass-then-fail is FLAKY (research §5)."""
    nodes = sorted({f.test for f in out.failures
                    if f.test and f.stage in ("unit", "integration") and f.category in ("ASSERTION", "CRASH")
                    and "::" in f.test})
    if not nodes or len(nodes) > 10:
        return
    if view.language == "js":
        step = Step(stage="unit", name="recheck", kind="node_test", args=sorted({n.split("::")[0] for n in nodes}),
                    timeout=view.stage_timeout)
    else:
        step = pytest_step(view, "recheck", nodes, view.stage_timeout)
    step.needs = []
    run = await backend.run(view.files, [step], cancelled=cancelled, image=view.image)
    res = run.get("recheck")
    if res is None or res.skipped or res.unavailable or res.timed_out:
        return
    _, _, still, _ = analyze.parse_junit(res.files.get(".xml", ""), "recheck", view.names)
    still_failing = {f.test for f in still}
    if not res.files.get(".xml"):
        return
    for f in out.failures:
        if f.test in nodes and f.test not in still_failing:
            f.flaky = True
            f.hint = "flaky: failed once and passed when run again (timing, order or a shared resource)"
            out.flaky.append(f.test)
    out.steps.extend(record_steps(run))
