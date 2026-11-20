"""The coding loop (Sprint 7 items 7.6 / 7.7, plan D7, D11, D17, D18): understand → locate → plan → edit → check →
debug, as a plain async state machine (no LangGraph).

1. **understand**: an empty workspace gets a template (D8); the repo map is built; files that talk to an AI are
   flagged (D22); the workspace's own checks run once so a bug-fix or revision starts from the real failure;
2. **locate** the files to change (BM25 + embeddings + rerank);
3. **plan** (``coder``, JSON ``CodePlan``): files to modify / create and a few steps;
4. **edit** (``coder``, SEARCH/REPLACE text); a rejected edit goes back with the applicator's message (at most
   ``MAX_REJECTIONS`` in a row);
5. **check** (compile, lint errors, imports, existing tests);
6. **debug** while checks fail: failures parsed by rules → the failing slices + a Reflexion note → one fix → checks
   again, until Member 4's stop policy says stop (tests pass / max rounds / plateau / token budget). A round that
   makes things worse is rolled back at the end (regression guard: the best round is kept).

Budgets: at most ``HMAP_CODING_MAX_STEPS`` model calls; every prompt within ``HMAP_CODING_PROMPT_TOKENS``; wall
clock is only a safety abort in the agent, never a decision here (replay). A missing model answer (fake mode,
replay miss, no route) ends the loop **gracefully** (D18): whatever was done so far is checked and packaged.
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel

from hmap.agents.coding import debug, prompts, templates
from hmap.agents.coding.context_budget import tokens, window
from hmap.agents.coding.edits import EditError, apply_text
from hmap.agents.coding.locate import locate
from hmap.agents.coding.model import CodingTrace, EditRecord, Step, StepKind
from hmap.agents.coding.repomap import RepoMap
from hmap.agents.coding.tools.checks import Checker, CheckRun
from hmap.agents.coding.tools.files import injected_lines, wrap_file
from hmap.agents.coding.tools.runner import Runner
from hmap.agents.coding.workspace import JailError, Workspace, changed_files
from hmap.agents.refine.stop import Budget, LoopState, MaxIters, Plateau, TestsPass, any_of
from hmap.core.config import Settings
from hmap.core.errors import Cancelled, HmapError
from hmap.core.llm.base import ClassifyQuestion, LLMClient, LLMResponse, Message
from hmap.core.tracing import get_logger

log = get_logger("hmap.coding.loop")

SEED = 7
MAX_REJECTIONS = 2
MAX_PLAN_FILES = 6
PLAN_TOKENS = 700
EDIT_TOKENS = 2000
DEBUG_TOKEN_BUDGET = 60_000      # Member 4 Budget policy: tokens spent by the debug rounds
ProgressFn = Callable[[int, str], Awaitable[None]]


class NoModel(Exception):
    """No model answer (fake mode, replay miss, no route): the loop stops and packages what it has."""


class StepBudget(Exception):
    """``HMAP_CODING_MAX_STEPS`` model calls used."""


@dataclass
class Options:
    """Switches for the eval's ablations (7.13)."""

    use_embeddings: bool = True
    use_rerank: bool = True
    use_locator: bool = True
    use_debug: bool = True
    role: str = "coder"
    seed: int = SEED                 # pass@k samples use other seeds at a higher temperature
    temperature: float = 0.0


@dataclass
class Job:
    ws: Workspace
    settings: Settings
    trace: CodingTrace
    task: prompts.TaskView
    llm: LLMClient | None = None
    known_failures: list[debug.Failure] = field(default_factory=list)
    progress: ProgressFn | None = None
    cancelled: asyncio.Event | None = None
    options: Options = field(default_factory=Options)
    review: bool = True              # 7.11 self-review (Member 4's Refiner) before returning
    use_judge: bool = False          # + LLM judge and one review fix round (task.refine)


class CodingLoop:
    def __init__(self, job: Job) -> None:
        self.job = job
        self.ws = job.ws
        self.t = job.trace
        self.settings = job.settings
        self.runner = Runner(job.ws, job.settings)
        self.checker = Checker(self.runner, cancelled=job.cancelled)
        self.budget = job.settings.coding_prompt_tokens
        self.before: dict[str, str] = {}
        self.rmap: RepoMap | None = None
        self.last_run: CheckRun | None = None
        self.stale = True                    # files changed since the last check run
        self._recorded = 0
        self.best: tuple[float, dict[str, str], CheckRun | None] | None = None
        self.no_change_needed = False        # the model judged the code already does what the task asks

    # ------------------------------------------------------------------------------------------------ helpers
    def check_cancelled(self) -> None:
        if self.job.cancelled is not None and self.job.cancelled.is_set():
            raise Cancelled("execution cancelled")

    async def progress(self, percent: int, summary: str) -> None:
        if self.job.progress is not None:
            await self.job.progress(percent, summary)

    async def call(self, kind: StepKind, msgs: list[Message], *, schema: type[BaseModel] | None = None,
                   max_tokens: int = EDIT_TOKENS, summary: str = "") -> LLMResponse:
        self.check_cancelled()
        if self.job.llm is None:
            raise NoModel("no model configured")
        if len(self.t.steps) >= self.settings.coding_max_steps:
            raise StepBudget()
        est = sum(tokens(m.content) for m in msgs)
        if est > self.budget + 16:       # fit() guarantees this; a violation is a bug, never sent
            raise AssertionError(f"prompt of {est} tokens exceeds the budget of {self.budget}")
        try:
            resp = await self.job.llm.generate(self.job.options.role, msgs, schema=schema,  # type: ignore[arg-type]
                                               max_tokens=max_tokens, temperature=self.job.options.temperature,
                                               seed=self.job.options.seed)
        except Cancelled:
            raise
        except HmapError as exc:
            self.t.steps.append(Step(n=len(self.t.steps) + 1, kind=kind, ok=False, prompt_tokens=est,
                                     summary=f"no answer: {type(exc).__name__}"))
            raise NoModel(f"{type(exc).__name__}: {str(exc)[:160]}") from None
        self.t.steps.append(Step(n=len(self.t.steps) + 1, kind=kind, summary=summary[:200],
                                 prompt_tokens=resp.usage.input_tokens or est,
                                 completion_tokens=resp.usage.output_tokens or tokens(resp.text)))
        return resp

    def _sync_commands(self) -> None:
        new = self.checker.records[self._recorded:]
        self._recorded = len(self.checker.records)
        self.t.commands.extend(new)
        for r in new:
            if r.denied:
                self.t.denials.append(f"{r.cmd}: {r.denied}")

    async def run_checks(self, changed: list[str] | None = None) -> CheckRun:
        reused = self.checker.reused
        run = await self.checker.run(len(self.t.steps), changed)
        if self.checker.reused > reused and not any("reused" in n for n in self.t.notes):
            self.t.notes.append("check results reused from an identical workspace (same files, same checks)")
        self._sync_commands()
        self.t.checks = run.checks
        self.last_run, self.stale = run, False
        score = debug.score(run.checks)
        if self.best is None or score > self.best[0]:
            self.best = (score, self.ws.snapshot(), run)
        return run

    def file_view(self, rel: str, lines: list[int] | None = None) -> tuple[str, str] | None:
        try:
            text = self.ws.read(rel)
        except (JailError, FileNotFoundError, ValueError, OSError):
            return None
        spans: list[tuple[int, int]] = [(n, n) for n in (lines or [])]
        part, a, b = window(text, spans, pad=25)
        return rel, wrap_file(part, path=rel, lines=None if (a, b) == (1, len(text.split("\n"))) else (a, b))

    def flag_injection(self) -> None:
        for rel, text in sorted(self.ws.snapshot().items()):
            for line in injected_lines(text)[:3]:
                flag = f"{rel}:{line}"
                if flag not in self.t.flags:
                    self.t.flags.append(flag)
        if self.t.flags:
            log.warning("coding: repository text that talks to an AI (treated as data)", flags=self.t.flags[:5])

    # --------------------------------------------------------------------------------------------------- stages
    async def scaffold(self) -> None:
        task = self.job.task
        text = " ".join([task.objective, *task.criteria, *task.requirements])
        name, _ = templates.choose(text)
        how = "keywords"
        if name is None and self.job.llm is not None:
            names = sorted(templates.all_templates())
            try:
                q = ClassifyQuestion(name="template", kind="choice", options=names,
                                     criteria={n: t.description for n, t in templates.all_templates().items()})
                ans = await self.job.llm.classify(text[:1500], [q])
                name = ans[0].answer if ans and ans[0].answer in names else None
                how = "classify"
            except Cancelled:
                raise
            except HmapError as exc:
                log.info("template classify failed; default template", error=type(exc).__name__)
        if name is None:
            name, how = templates.DEFAULT_TEMPLATE, "default"
        installed = templates.all_templates()[name].install(self.ws)
        self.t.template = name
        self.t.notes.append(f"empty workspace: started from the {name} template ({how}; {len(installed)} files)")
        self.stale = True

    async def plan(self, focus: list[str], baseline: str) -> prompts.CodePlan:
        files = [v for p in focus if (v := self.file_view(p, self._failure_lines(p))) is not None]
        notes = [f"files that look relevant: {', '.join(focus)}"] if focus else []
        if self.t.template:
            notes.append(f"the workspace was just created from the {self.t.template} template; adapt it to the task")
        msgs, cut = prompts.plan_messages(self.job.task, self._map(focus), files, baseline, notes, self.budget)
        resp = await self.call("plan", msgs, schema=prompts.CodePlan, max_tokens=PLAN_TOKENS,
                               summary="plan" + (f" (cut: {', '.join(cut)})" if cut else ""))
        plan = resp.parsed if isinstance(resp.parsed, prompts.CodePlan) else prompts.CodePlan()
        modify: list[str] = []
        create: list[str] = []
        for raw in [*plan.files_to_modify, *plan.files_to_create]:
            try:
                rel = self.ws.rel(raw.strip().strip("`"))
            except JailError:
                self.t.notes.append(f"plan named a path outside the workspace: {raw[:80]}")
                continue
            target = modify if self.ws.is_file(rel) else create
            if rel not in modify and rel not in create and rel != ".":
                target.append(rel)
        plan = plan.model_copy(update={"files_to_modify": modify[:MAX_PLAN_FILES],
                                       "files_to_create": create[:max(0, MAX_PLAN_FILES - len(modify))]})
        self.t.plan = plan.model_dump()
        self.t.steps[-1].summary = plan.summary[:200] or self.t.steps[-1].summary
        return plan

    async def edit(self, plan: prompts.CodePlan | None, focus: list[str], *, kind: StepKind = "edit",
                   failures: str = "", output: str = "", notes: list[str] | None = None,
                   lines: dict[str, list[int]] | None = None) -> list[str]:
        """One edit step (with up to ``MAX_REJECTIONS`` retries after a rejected edit); returns changed files."""
        feedback = ""
        for attempt in range(MAX_REJECTIONS + 1):
            files = [v for p in focus if (v := self.file_view(p, (lines or {}).get(p))) is not None]
            if kind in ("debug", "review"):
                msgs, cut = prompts.debug_messages(self.job.task, failures, output, notes or [], files, feedback,
                                                   self._map(focus), self.budget)
            else:
                msgs, cut = prompts.edit_messages(self.job.task, plan, files, feedback, self._map(focus),
                                                  self.budget)
            resp = await self.call(kind, msgs, max_tokens=EDIT_TOKENS,
                                   summary=f"{kind} attempt {attempt + 1}" + (f" (cut: {', '.join(cut)})" if cut
                                                                              else ""))
            text = resp.text.strip()
            hypothesis = next((ln[11:].strip() for ln in text.splitlines() if ln.upper().startswith("HYPOTHESIS:")),
                              "")
            if hypothesis:
                self.t.steps[-1].summary = f"hypothesis: {hypothesis}"[:200]
            if "<<<<<<< SEARCH" not in text and re.search(r"\bNO CHANGES\b", text, re.I):
                self.t.edits.append(EditRecord(step=len(self.t.steps), ok=True, notes=["model: no changes needed"]))
                self.no_change_needed = kind == "edit"
                return []
            try:
                applied = apply_text(self.ws, text)
            except EditError as exc:
                self.t.edits.append(EditRecord(step=len(self.t.steps), ok=False, error=str(exc)[:500]))
                self.t.steps[-1].ok = False
                feedback = str(exc)
                continue
            self.t.edits.append(EditRecord(step=len(self.t.steps), ok=True, files=applied.files, notes=applied.notes))
            self.stale = True
            return applied.files
        self.t.notes.append(f"{kind}: {MAX_REJECTIONS + 1} edits in a row were rejected; last error: {feedback[:200]}")
        return []

    async def debug_loop(self, run: CheckRun, changed: set[str]) -> None:
        rounds = self.settings.coding_max_debug_rounds if self.job.options.use_debug else 0
        policy = any_of(TestsPass(lambda r: bool(r is not None and r.passed)), MaxIters(rounds),
                        Plateau(eps=0.01, k=2), Budget(tokens=DEBUG_TOKEN_BUDGET, seconds=None))
        start_tokens = self.t.tokens
        state = LoopState().record(debug.score(run.checks), output=run)
        notes: list[str] = []
        n = 0
        while True:
            reason = policy.check(state)
            if reason:
                self.t.stop_reason = "checks_pass" if reason == "tests_pass" else reason
                return
            n += 1
            failures = self._failures(run)
            lines: dict[str, list[int]] = {}
            for f in failures:
                if f.file and f.line and self._exists(f.file):
                    lines.setdefault(self.ws.rel(f.file), []).append(f.line)
            focus = list(dict.fromkeys([*lines, *sorted(changed)]))[:3]
            await self.progress(min(95, 60 + 8 * n), f"debug round {n}: {failures[0].short() if failures else ''}")
            fixed = await self.edit(None, focus, kind="debug", failures="\n".join(f.short() for f in failures),
                                    output=run.failures_for_model(3000), notes=notes, lines=lines)
            changed.update(fixed)
            if fixed:
                run = await self.run_checks(sorted(changed))
            if not run.passed:
                note = debug.reflection(n, self._failures(run), fixed, failures)
                notes.append(note)
                self.t.reflections.append(note)
            state = state.record(debug.score(run.checks), tokens=self.t.tokens - start_tokens, output=run)

    # ----------------------------------------------------------------------------------------------- the loop
    async def run(self) -> CodingTrace:
        self.before = self.ws.snapshot()
        try:
            await self._run()
        except NoModel as exc:
            self.t.notes.append(f"no model answer: {exc}")
            self.t.stop_reason = "no_model"
        except StepBudget:
            self.t.stop_reason = "step_budget"
            self.t.notes.append(f"stopped after {self.settings.coding_max_steps} model calls")
        if self.stale or self.last_run is None:
            await self.run_checks(changed_files(self.before, self.ws.snapshot()) or None)
        await self._keep_best()
        if self.job.review and self.t.stop_reason != "no_model":
            from hmap.agents.coding.review_hook import review

            await review(self, use_judge=self.job.use_judge)
        after = self.ws.snapshot()
        self.t.files_changed = changed_files(self.before, after)
        passed = self.last_run is not None and self.last_run.passed
        finished = self.t.stop_reason not in ("no_model", "step_budget")
        did_something = bool(self.t.files_changed) or self.no_change_needed
        if passed and finished and not did_something:
            self.t.notes.append("no change was made (edits were refused or rolled back)")
        elif self.no_change_needed and not self.t.files_changed:
            self.t.notes.append("the model judged that the code already does what the task asks")
        self.t.outcome = "success" if passed and finished and did_something else "partial"
        if not self.t.stop_reason:
            self.t.stop_reason = "checks_pass" if passed else "checks_fail"
        return self.t

    async def _run(self) -> None:
        await self.progress(5, "reading the workspace")
        if not self.ws.files():
            await self.scaffold()
        self.rmap = RepoMap.build(self.ws)
        self.flag_injection()
        baseline = ""
        if self.ws.files(".py"):
            run = await self.run_checks()
            baseline = "all checks pass" if run.passed else run.failures_for_model(2500)
        known = "\n".join(f.short() for f in self.job.known_failures)
        if known:
            baseline = f"Reported failures:\n{known}\n\n{baseline}".strip()
        await self.progress(15, "locating the files to change")
        focus = await self._locate(baseline)
        await self.progress(30, "planning the change")
        plan = await self.plan(focus, baseline)
        targets = [*plan.files_to_modify, *plan.files_to_create] or focus
        changed: set[str] = set()
        if plan.files_to_modify or plan.files_to_create or not (self.last_run and self.last_run.passed):
            await self.progress(45, f"editing {', '.join(targets[:3])}")
            changed.update(await self.edit(plan, targets[:4]))
        else:
            self.no_change_needed = True
            self.t.notes.append("the plan changes no file and the checks already pass")
        self.rmap = RepoMap.build(self.ws, previous=self.rmap)
        await self.progress(60, "running the checks")
        run = await self.run_checks(sorted(changed) or None) if (self.stale or self.last_run is None) else \
            self.last_run
        assert run is not None
        if run.passed:
            self.t.stop_reason = "checks_pass"
            return
        await self.debug_loop(run, changed)

    # ------------------------------------------------------------------------------------------------ internals
    async def _locate(self, baseline: str) -> list[str]:
        assert self.rmap is not None
        failure_files = [f.file for f in [*self.job.known_failures, *self._failures(self.last_run)]
                         if f.file and self._exists(f.file)]
        focus: list[str] = []
        if self.job.options.use_locator:
            query = " ".join([self.job.task.query(), baseline[:600]])
            located = await locate(self.rmap, self.ws.snapshot(), query, self.job.llm,
                                   use_embeddings=self.job.options.use_embeddings,
                                   use_rerank=self.job.options.use_rerank)
            self.t.located = [{"path": p, "score": s} for p, s in located.ranked[:8]]
            focus = located.top(3)
        focus = list(dict.fromkeys([*(self.ws.rel(f) for f in failure_files), *focus]))[:4]
        return focus

    def _map(self, focus: list[str]) -> str:
        if self.rmap is None:
            return ""
        return self.rmap.render(min(1500, self.budget // 4), focus=focus)

    def _exists(self, rel: str) -> bool:
        try:
            return self.ws.is_file(rel)
        except JailError:
            return False

    def _failures(self, run: CheckRun | None) -> list[debug.Failure]:
        if run is None:
            return []
        out: list[debug.Failure] = []
        for r in run.failed_results():
            out.extend(debug.parse_output(r.cmd, r.output, r.timed_out))
        return out[:8]

    def _failure_lines(self, rel: str) -> list[int]:
        return [f.line for f in [*self.job.known_failures, *self._failures(self.last_run)]
                if f.file and f.line and self._exists(f.file) and self.ws.rel(f.file) == rel]

    async def _keep_best(self) -> None:
        """Regression guard: if a later round made the checks worse, go back to the best state."""
        if self.best is None or self.last_run is None:
            return
        score, files, run = self.best
        if debug.score(self.last_run.checks) + 1e-9 < score and run is not None:
            self.ws.restore(files)
            self.t.notes.append(f"the last round made the checks worse; kept the best round (score {score:.2f})")
            await self.run_checks()

