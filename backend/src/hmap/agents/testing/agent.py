"""``TestingAgent`` (Sprint 8 item 8.10): the real ``test.run``.

Input (``TaskAssign``): ``objective`` + ``acceptance_criteria``; the coding step's artifacts in ``artifact_refs``
(newest ``workspace`` = the tree to test, ``code-change-set`` = what changed); or ``inputs.workspace_ref``; else the
project head (plan D8). Optional ``inputs``: ``entrypoint`` / ``sample_input`` / ``long_running`` (execution stage),
``generate_tests`` (write tests even when some exist), ``tests`` (acceptance test files supplied with the step,
``{"tests/acceptance/test_x.py": "..."}``), ``loop`` (the test -> revise round, set by the hook).

Output: ``test-report`` ``tr-<task_id>`` (first), ``test-log`` ``tl-<task_id>``, ``testing-trace`` ``tt-<task_id>``,
``generated-tests`` ``gt-<task_id>`` when any survived the gate. Outcome ``success`` when the pipeline ran (the
report's ``passed`` carries the verdict), ``partial`` when there was nothing to test or the sandbox itself failed,
``failure`` only when artifacts cannot be read or stored (plan D13).

Idempotent: a redelivered execution whose trace is ``done`` returns the stored artifacts. Cancel kills the
running container / process (the sandbox backends watch ``ctx.cancelled``).
"""

import json
import re
import time
from typing import Any, ClassVar

from hmap.agents.coding.agent import failure_injection
from hmap.agents.coding.workspace import files_from_tar
from hmap.agents.testing import analyze, deps, fuzz, mutation, quarantine, testgen
from hmap.agents.testing.governor import startup_cleanup
from hmap.agents.testing.model import (
    GENERATED_TYPE,
    LOG_TYPE,
    REPORT_TYPE,
    STAGES,
    TRACE_TYPE,
    LoopState,
    StageRecord,
    TestingTrace,
    generated_id,
    log_id,
    report_id,
    trace_id,
)
from hmap.agents.testing.pipeline import PipelineResult, run_pipeline
from hmap.agents.testing.sandbox import Backend, Step, choose
from hmap.agents.testing.stages import View, node
from hmap.agents.testing.stages.execution import parse_entrypoint
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, TaskAssign, TaskResult, TestReport
from hmap.core.contracts.capabilities import TEST_RUN
from hmap.core.contracts.domain import StageResult, TestFailure
from hmap.core.runtime.base import AgentContext, BaseAgent
from hmap.core.tracing import get_logger

log = get_logger("hmap.testing.agent")
ACCEPTANCE_PATH = re.compile(r"tests/acceptance/[A-Za-z0-9_./-]+\.py")


def _newest(refs: list[ArtifactRef], artifact_type: str) -> ArtifactRef | None:
    found = [r for r in refs if r.artifact_type == artifact_type]
    return max(found, key=lambda r: (r.created_at, r.version)) if found else None


async def find_workspace(task: TaskAssign, ctx: AgentContext) -> tuple[ArtifactRef | None, str]:
    """Plan D8: the coding step's workspace, then ``inputs.workspace_ref``, then the project head."""
    ref = _newest(task.artifact_refs, "workspace")
    if ref is not None:
        return ref, "the coding step's workspace"
    raw = task.inputs.get("workspace_ref")
    if isinstance(raw, dict):
        try:
            return ArtifactRef.model_validate(raw), "inputs.workspace_ref"
        except ValueError:
            pass
    head = await ctx.artifacts.latest(f"wsh-{ctx.project_id}", project_id=ctx.project_id)
    if head is not None:
        return head, "the project's workspace head"
    return None, "nothing to test"


class TestingAgent(BaseAgent):
    __test__ = False  # not a pytest test class
    name = "testing"
    capabilities: ClassVar[tuple[str, ...]] = (TEST_RUN,)
    max_slots: ClassVar[int] = 1
    version: ClassVar[str] = "1.0"

    def __init__(self, settings: Settings | None = None, **deps: Any) -> None:
        self.settings = settings
        self.deps = deps                     # tests: backend=<Backend>

    async def on_start(self) -> None:
        await startup_cleanup(self.settings or Settings.from_env())

    async def _existing(self, task: TaskAssign, ctx: AgentContext) -> list[ArtifactRef]:
        pid = ctx.project_id
        tr = await ctx.artifacts.latest(trace_id(task.task_id), project_id=pid)
        if tr is None:
            return []
        try:
            trace = TestingTrace.model_validate_json(await ctx.artifacts.get(tr, project_id=pid))
        except Exception:
            return []
        if trace.status != "done" or trace.execution_id != task.execution_id:
            return []
        rep = await ctx.artifacts.latest(report_id(task.task_id), project_id=pid)
        lg = await ctx.artifacts.latest(log_id(task.task_id), project_id=pid)
        return [rep, *([lg] if lg else []), tr] if rep else []

    async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult:
        await failure_injection(task, ctx)
        settings = self.settings or Settings.from_env()
        if existing := await self._existing(task, ctx):
            return ctx.result(existing, summary="tests already run for this execution (redelivered)")
        started = time.monotonic()
        trace = TestingTrace(task_id=task.task_id, project_id=ctx.project_id, execution_id=task.execution_id,
                             objective=task.objective[:2000], acceptance_criteria=list(task.acceptance_criteria)[:20],
                             loop=LoopState.model_validate(task.inputs.get("loop") or {}))
        ccs = _newest(task.artifact_refs, "code-change-set")
        trace.changeset_ref = ccs
        if ccs is not None and ccs.artifact_id.startswith("ccs-"):
            trace.coding_task_id = ccs.artifact_id[4:]
        ws_ref, how = await find_workspace(task, ctx)
        trace.workspace_ref, trace.workspace_from = ws_ref, how
        files: dict[str, str] = {}
        if ws_ref is not None:
            files = files_from_tar(await ctx.artifacts.get(ws_ref, project_id=ctx.project_id))
        trace.files = len(files)
        await self._progress(ctx, trace, 5, f"testing {len(files)} files ({how})")
        if not files:
            trace.notes.append("no workspace to test: the step has no code yet")
            return await self._finish(task, ctx, trace, None, None, started, outcome="partial")
        backend: Backend = self.deps.get("backend") or await choose(settings)
        trace.backend, trace.isolation = backend.name, backend.isolation   # type: ignore[assignment]
        supplied = acceptance_tests(task.inputs.get("tests"))
        if supplied:
            trace.notes.append(f"{len(supplied)} acceptance test file(s) supplied with the step: "
                               f"{', '.join(sorted(supplied))}")
        view = View(files={**files, **supplied}, backend=backend.name, stage_timeout=settings.testing_stage_timeout_s,
                    entrypoint=parse_entrypoint(task.inputs.get("entrypoint")),
                    sample_input=str(task.inputs["sample_input"])[:20_000] if task.inputs.get("sample_input") else None,
                    long_running=bool(task.inputs.get("long_running")))
        if node.is_js_project(view.files):
            view.language, view.image = "js", settings.testing_image_node
        trace.language = view.language
        gen = testgen.Generated()
        if view.language == "python" and testgen.wanted(view, list(task.acceptance_criteria),
                                                        asked=bool(task.inputs.get("generate_tests")),
                          enabled=settings.testing_generate):
            await self._progress(ctx, trace, 15, "writing tests from the acceptance criteria")
            gen = await testgen.generate(ctx.llm, view, list(task.acceptance_criteria), task.objective)
            ctx.check_cancelled()
            await testgen.gate(gen, view, backend, ctx.cancelled)
            if gen.text:
                view.files[testgen.GENERATED_FILE] = gen.text
                view.deselect = gen.deselect
            trace.model_calls += gen.model_calls
            trace.tokens += gen.tokens
            trace.generated = gen.summary()
            if gen.note:
                trace.notes.append(gen.note)
        ctx.check_cancelled()
        await self._progress(ctx, trace, 30, f"running the stages in the {backend.name} sandbox")
        result = await run_pipeline(view, backend, cancelled=ctx.cancelled)
        ctx.check_cancelled()
        await self._quarantine(task, ctx, trace, result)
        await self._dependencies(view, settings, trace, result)
        python = view.language == "python"
        if python and (task.inputs.get("mutation") or settings.testing_mutation) \
                and result.stages["unit"].status == "passed":
            await self._progress(ctx, trace, 70, "mutation testing: do the tests notice planted faults?")
            trace.mutation = (await run_mutation(view, backend, settings, ctx.cancelled)).as_dict()
        if python and (task.inputs.get("fuzz") or settings.testing_fuzz) and result.stages["build"].status == "passed":
            await self._progress(ctx, trace, 75, "fuzzing the parsing functions with generated inputs")
            trace.fuzz, found = await run_fuzz(view, backend, ctx.cancelled)
            result.failures.extend(found)
        calls = await analyze.model_categories(ctx.llm, result.failures)
        calls_h, tokens = await analyze.model_hints(ctx.llm, result.failures, view.files)
        trace.model_calls += calls + calls_h
        trace.tokens += tokens
        outcome = "partial" if result.error else "success"
        if result.error:
            trace.notes.append(f"the sandbox failed: {result.error}")
        return await self._finish(task, ctx, trace, result, gen, started, outcome=outcome)

    async def _finish(self, task: TaskAssign, ctx: AgentContext, trace: TestingTrace, result: PipelineResult | None,
                      gen: testgen.Generated | None, started: float, *, outcome: str) -> TaskResult:
        pid = ctx.project_id
        refs: list[ArtifactRef] = []
        log_ref = None
        if result is not None:
            trace.stages = [result.stages.get(n) or StageRecord(name=n, status="skipped") for n in STAGES]
            trace.steps, trace.failures, trace.flaky = result.steps, result.failures, result.flaky
            trace.coverage, trace.passed, trace.pass_ratio = result.coverage, result.passed, result.pass_ratio
            log_ref = await ctx.artifacts.put(result.log_text().encode(), project_id=pid, artifact_type=LOG_TYPE,
                                              media_type="text/plain", created_by=ctx.agent_id,
                                              artifact_id=log_id(task.task_id))
        else:
            trace.stages = [StageRecord(name=n, status="skipped", detail="nothing to test") for n in STAGES]
        report = TestReport(
            task_id=task.task_id, changeset_ref=trace.changeset_ref,
            stages={n: StageResult(status=s.status, output_ref=log_ref, duration_s=s.duration_s)
                    for n, s in zip(STAGES, trace.stages, strict=True)},
            failures=[contract_failure(f) for f in trace.failures][:100] or (
                [TestFailure(category="ENV", message="nothing to test: no workspace for this step",
                             hint="run the coding step first")] if result is None else []),
            passed=trace.passed, coverage=trace.coverage, exec_log_ref=log_ref)
        rep_ref = await ctx.put_json(report, artifact_type=REPORT_TYPE, artifact_id=report_id(task.task_id))
        refs.append(rep_ref)
        if log_ref is not None:
            refs.append(log_ref)
        if gen is not None and gen.text:
            refs.append(await ctx.artifacts.put(gen.text.encode(), project_id=pid, artifact_type=GENERATED_TYPE,
                                                media_type="text/x-python", created_by=ctx.agent_id,
                                                artifact_id=generated_id(task.task_id)))
        trace.status = "done"
        trace.seconds = round(time.monotonic() - started, 3)
        refs.append(await ctx.put_json(trace, artifact_type=TRACE_TYPE, artifact_id=trace_id(task.task_id)))
        counted = [f for f in trace.failures if f.category != "LINT" and not f.flaky]
        summary = (f"{'passed' if trace.passed else 'failed'}: {len(counted)} failures, "
                   f"{sum(s.tests for s in trace.stages)} tests ({trace.backend})")
        log.info("testing done", task_id=task.task_id, passed=trace.passed, failures=len(counted),
                 backend=trace.backend, seconds=trace.seconds)
        return ctx.result(refs, summary=summary, outcome=outcome,
                          evidence=[json.dumps({"passed": trace.passed, "stages": {s.name: s.status
                                                                                  for s in trace.stages},
                                                "failures": len(counted), "backend": trace.backend})])

    @staticmethod
    async def _dependencies(view: View, settings: Settings, trace: TestingTrace, result: PipelineResult) -> None:
        """Known-vulnerable pinned dependencies (OSV). Only live mode may use the network: fake / replay runs (tests,
        CI, demos) read the cache, so they stay offline and repeatable."""
        mode = settings.testing_dep_audit
        if mode == "auto" and settings.llm_mode != "live":
            mode = "offline"
        audit, found = await deps.audit(view.files, mode)
        trace.dependencies = audit.as_dict()
        if found:
            result.failures.extend(found)
            sec = result.stages["security"]
            sec.status = "failed"
            sec.detail = (sec.detail + f"; {len(found)} vulnerable dependency pin(s)")[:500]
        elif audit.audited:
            sec = result.stages["security"]
            sec.detail = (sec.detail + f"; {len(audit.audited)} pinned dependencies audited ({audit.source})")[:500]

    @staticmethod
    async def _quarantine(task: TaskAssign, ctx: AgentContext, trace: TestingTrace, result: PipelineResult) -> None:
        """Flaky tests seen before do not count (stretch: quarantine); new flaky ones go in, clean passes count."""
        q = await quarantine.load(ctx.artifacts, ctx.project_id)
        hit = quarantine.apply(q, result.failures)
        if hit:
            trace.notes.append(f"{len(hit)} quarantined (flaky) test(s) did not count: {', '.join(sorted(hit))[:300]}")
        failed = {f.test for f in result.failures if f.test and not f.flaky}
        if quarantine.update(q, flaky=result.flaky, failed=failed, passed=result.passed_tests, task_id=task.task_id):
            await quarantine.save(ctx.artifacts, q, ctx.agent_id)
        trace.quarantined = sorted(q.active())

    @staticmethod
    async def _progress(ctx: AgentContext, trace: TestingTrace, percent: int, summary: str) -> None:
        ref = await ctx.put_json(trace, artifact_type=TRACE_TYPE, artifact_id=trace_id(trace.task_id))
        await ctx.progress(percent, summary, artifact_refs=[ref])


async def run_mutation(view: View, backend: Backend, settings: Settings,
                       cancelled: Any = None) -> mutation.MutationResult:
    mutants = mutation.make_mutants(view.files, view.code_files, settings.testing_mutants)
    if not mutants or not view.unit_tests:
        return mutation.MutationResult(error="nothing to mutate" if not mutants else "no unit tests")
    per = min(mutation.PER_MUTANT_S, view.stage_timeout)
    step = Step(stage="unit", name="mutation", kind="script",
                args=[mutation.RUNNER_PATH, mutation.MUTANTS_PATH, str(per), *view.unit_tests],
                timeout=per * len(mutants) + 30)
    run = await backend.run({**view.files, **mutation.plan_files(mutants)}, [step], cancelled=cancelled)
    res = run.get("mutation")
    if res is None or res.unavailable:
        return mutation.MutationResult(error=(res.unavailable if res else run.error) or "the sandbox did not run it")
    out = mutation.parse(res.output, mutants)
    out.seconds = res.seconds
    return out


async def run_fuzz(view: View, backend: Backend, cancelled: Any = None) -> tuple[dict[str, Any], list[Any]]:
    tgts = fuzz.targets(view.files, view.code_files)
    if not tgts:
        return {"targets": 0, "note": "no function with simple typed parameters to fuzz"}, []
    if backend.name != "docker":
        return {"targets": len(tgts), "note": "fuzzing needs the Docker sandbox (Hypothesis is in its image)"}, []
    step = Step(stage="unit", name="fuzz", kind="script",
                args=[fuzz.RUNNER_PATH, fuzz.TARGETS_PATH, str(fuzz.EXAMPLES)],
                timeout=min(300.0, 30.0 * len(tgts) + 30))
    run = await backend.run({**view.files, **fuzz.plan_files(tgts)}, [step], cancelled=cancelled)
    res = run.get("fuzz")
    if res is None or res.unavailable or res.timed_out:
        return {"targets": len(tgts), "error": (res.unavailable if res else run.error) or "timed out"}, []
    return fuzz.parse(res.output, tgts)


def acceptance_tests(raw: Any) -> dict[str, str]:
    """``inputs.tests``: test files supplied with the step (the assignment's own tests, a teacher's checks). Trusted
    like the workspace's tests (their failures can start a revision); only ``tests/acceptance/*.py``, at most 10
    files of 100 KB."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for rel, text in list(raw.items())[:10]:
        if isinstance(rel, str) and isinstance(text, str) and ACCEPTANCE_PATH.fullmatch(rel) and ".." not in rel \
                and len(text) <= 100_000:
            out[rel] = text
    return out


def contract_failure(f: Any) -> TestFailure:
    tags = "".join(t for t, on in (("[generated] ", f.generated), ("[flaky] ", f.flaky), ("[fuzz] ", f.fuzz)) if on)
    return TestFailure(category=f.category, file=f.file, line=f.line if f.line and f.line >= 1 else None,
                       message=(tags + (f.message or f.category))[:1000], hint=f.hint)
