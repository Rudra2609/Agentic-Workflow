# Code summaries: hmap

The hmap repository implements a hierarchical multi‑agent AI execution platform that coordinates agents, tasks, and observability across a single‑process composition root (backend/src/hmap/system.py::system). Core platform services live in hmap.core (e.g., backend/src/hmap/core/config.py::config and backend/src/hmap/core/runtime/base.py::base) and provide settings, error handling, tracing, and the agent plug‑in contract. Agents such as the documentation generator (backend/src/hmap/agents/docgen/model.py::model) and the testing sandbox (backend/src/hmap/agents/testing/sandbox/__init__.py::sandbox) use these contracts, while the manager (hmap.manager) runs the task state machine and graph executor. Persistence is handled by hmap.db (Postgres connection pool and migrations), and observability is provided by hmap.obs (traces and metrics). Supporting tooling in hmaptools (e.g., hmaptools.report::report) enables regression checks, ownership validation, and secret scanning across the 310 modules and 84 HTTP endpoints.

Public functions and classes: 2165; described: 31 % (from docstrings or the model; the rest show their signature).

## `backend/alembic/env.py`

“Alembic environment for hmap.”

- `backend/alembic/env.py::run_migrations_offline`: “``alembic upgrade head --sql``: emit SQL without a database.”
- `backend/alembic/env.py::run_migrations_online`: `def run_migrations_online() -> None`

## `backend/src/hmap/__init__.py`

“hmap — hierarchical multi-agent AI project execution platform.”


## `backend/src/hmap/agents/__init__.py`

“hmap package.”


## `backend/src/hmap/agents/coding/__init__.py`

“Autonomous coding (Member 7, Sprint 7): ``code.implement`` + ``code.revise``.”


## `backend/src/hmap/agents/coding/agent.py`

“``CodingAgent`` (Sprint 7 item 7.9): the real ``code.implement`` and ``code.revise``.”

- `backend/src/hmap/agents/coding/agent.py::failure_injection`: “The platform's test / demo hooks, only when a task asks for them (as the stub did).”
- `backend/src/hmap/agents/coding/agent.py::requirements_for`: “Texts of the requirements this step covers (+ technology constraints), from the latest requirement set.”
- `backend/src/hmap/agents/coding/agent.py::CodingAgent`: `class CodingAgent(BaseAgent)`
- `backend/src/hmap/agents/coding/agent.py::CodingAgent.__init__`: `def __init__(self, settings: Settings | None=None, **deps: Any) -> None`
- `backend/src/hmap/agents/coding/agent.py::CodingAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/agents/coding/context_budget.py`

“Context budgeter (Sprint 7 item 7.8, plan D10): every prompt fits ``HMAP_CODING_PROMPT_TOKENS``.”

- `backend/src/hmap/agents/coding/context_budget.py::tokens`: `def tokens(text: str) -> int`
- `backend/src/hmap/agents/coding/context_budget.py::Part`: `class Part`
- `backend/src/hmap/agents/coding/context_budget.py::cut_middle`: `def cut_middle(text: str, max_tokens: int) -> str`
- `backend/src/hmap/agents/coding/context_budget.py::fit`: “Choose and cut parts so ``tokens(separator.join(texts)) <= budget``.”
- `backend/src/hmap/agents/coding/context_budget.py::window`: “A slice of ``text`` covering ``ranges`` (1-based line spans) plus ``pad`` lines around; the whole file when it is short.”

## `backend/src/hmap/agents/coding/debug.py`

“Debug helpers (Sprint 7 item 7.7, plan D11): turn check output into located failures, score a round, and write the Reflexion note carried into the next round.”

- `backend/src/hmap/agents/coding/debug.py::Failure`: `class Failure`
- `backend/src/hmap/agents/coding/debug.py::Failure.short`: `def short(self) -> str`
- `backend/src/hmap/agents/coding/debug.py::parse_traceback`: “One failure per traceback block (the innermost workspace frame + the exception line).”
- `backend/src/hmap/agents/coding/debug.py::parse_output`: `def parse_output(cmd: str, output: str, timed_out: bool=False) -> list[Failure]`
- `backend/src/hmap/agents/coding/debug.py::from_test_report`: “Member 8's ``TestReport.failures`` (category, file, line, message, hint) as :class:`Failure`.”
- `backend/src/hmap/agents/coding/debug.py::score`: “0..1 progress of one round: compile 0.25, imports 0.15, lint 0.1, tests 0.5 (by passed fraction).”
- `backend/src/hmap/agents/coding/debug.py::passed_fraction`: `def passed_fraction(text: str) -> float`
- `backend/src/hmap/agents/coding/debug.py::reflection`: “Rule-made Reflexion note: what is still failing and what to try differently.”

## `backend/src/hmap/agents/coding/edits.py`

“SEARCH/REPLACE edit applicator (Sprint 7 item 7.5, plan D13; ported from ``samples/coding/edits.py``).”

- `backend/src/hmap/agents/coding/edits.py::EditError`: “An edit that was not applied; the message is written for the model to act on.”
- `backend/src/hmap/agents/coding/edits.py::Edit`: `class Edit`
- `backend/src/hmap/agents/coding/edits.py::Applied`: `class Applied`
- `backend/src/hmap/agents/coding/edits.py::parse`: `def parse(text: str) -> list[Edit]`
- `backend/src/hmap/agents/coding/edits.py::apply`: `def apply(ws: Workspace, edits: list[Edit]) -> Applied`
- `backend/src/hmap/agents/coding/edits.py::apply_text`: `def apply_text(ws: Workspace, model_output: str) -> Applied`

## `backend/src/hmap/agents/coding/hooks.py`

“Manager hooks of the coding agent (Sprint 7, plan D16).”

- `backend/src/hmap/agents/coding/hooks.py::emit_code_completed`: `async def emit_code_completed(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/coding/hooks.py::on_code_implemented`: `async def on_code_implemented(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/coding/hooks.py::on_code_revised`: `async def on_code_revised(event: DomainEvent, manager: ManagerHandle) -> None`

## `backend/src/hmap/agents/coding/locate.py`

“Locator (Sprint 7 item 7.3, plan D9): which files does a task need to change?”

- `backend/src/hmap/agents/coding/locate.py::tokens`: `def tokens(text: str) -> list[str]`
- `backend/src/hmap/agents/coding/locate.py::bm25`: `def bm25(files: dict[str, str], query: str, k1: float=1.2, b: float=0.75) -> list[tuple[str, float]]`
- `backend/src/hmap/agents/coding/locate.py::RerankAnswer`: `class RerankAnswer(BaseModel)`
- `backend/src/hmap/agents/coding/locate.py::Located`: `class Located`
- `backend/src/hmap/agents/coding/locate.py::Located.top`: `def top(self, k: int=3) -> list[str]`
- `backend/src/hmap/agents/coding/locate.py::locate`: `async def locate(rmap: RepoMap, files: dict[str, str], query: str, llm: LLMClient | None=None, *, use_embeddings: bool=True, use_rerank: bool=True) -> Located`

## `backend/src/hmap/agents/coding/loop.py`

“The coding loop (Sprint 7 items 7.6 / 7.7, plan D7, D11, D17, D18): understand → locate → plan → edit → check → debug, as a plain async state machine (no LangGraph).”

- `backend/src/hmap/agents/coding/loop.py::NoModel`: “No model answer (fake mode, replay miss, no route): the loop stops and packages what it has.”
- `backend/src/hmap/agents/coding/loop.py::StepBudget`: “``HMAP_CODING_MAX_STEPS`` model calls used.”
- `backend/src/hmap/agents/coding/loop.py::Options`: “Switches for the eval's ablations (7.13).”
- `backend/src/hmap/agents/coding/loop.py::Job`: `class Job`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop`: `class CodingLoop`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.__init__`: `def __init__(self, job: Job) -> None`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.check_cancelled`: `def check_cancelled(self) -> None`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.progress`: `async def progress(self, percent: int, summary: str) -> None`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.call`: `async def call(self, kind: StepKind, msgs: list[Message], *, schema: type[BaseModel] | None=None, max_tokens: int=EDIT_TOKENS, summary: str='') -> LLMResponse`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.run_checks`: `async def run_checks(self, changed: list[str] | None=None) -> CheckRun`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.file_view`: `def file_view(self, rel: str, lines: list[int] | None=None) -> tuple[str, str] | None`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.flag_injection`: `def flag_injection(self) -> None`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.scaffold`: `async def scaffold(self) -> None`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.plan`: `async def plan(self, focus: list[str], baseline: str) -> prompts.CodePlan`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.edit`: “One edit step (with up to ``MAX_REJECTIONS`` retries after a rejected edit); returns changed files.”
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.debug_loop`: `async def debug_loop(self, run: CheckRun, changed: set[str]) -> None`
- `backend/src/hmap/agents/coding/loop.py::CodingLoop.run`: `async def run(self) -> CodingTrace`

## `backend/src/hmap/agents/coding/model.py`

“Artifact types, ids and the coding trace (Sprint 7, plan D3).”

- `backend/src/hmap/agents/coding/model.py::changeset_id`: `def changeset_id(task_id: str) -> str`
- `backend/src/hmap/agents/coding/model.py::workspace_id`: `def workspace_id(task_id: str) -> str`
- `backend/src/hmap/agents/coding/model.py::patch_id`: `def patch_id(task_id: str) -> str`
- `backend/src/hmap/agents/coding/model.py::trace_id`: `def trace_id(task_id: str) -> str`
- `backend/src/hmap/agents/coding/model.py::head_id`: `def head_id(project_id: str) -> str`
- `backend/src/hmap/agents/coding/model.py::Step`: “One model call.”
- `backend/src/hmap/agents/coding/model.py::EditRecord`: `class EditRecord(BaseModel)`
- `backend/src/hmap/agents/coding/model.py::CommandRecord`: `class CommandRecord(BaseModel)`
- `backend/src/hmap/agents/coding/model.py::Check`: “Result of the agent's own checks (plan D12): compile, lint, tests, import smoke.”
- `backend/src/hmap/agents/coding/model.py::CodingTrace`: `class CodingTrace(BaseModel)`
- `backend/src/hmap/agents/coding/model.py::CodingTrace.model_calls`: `def model_calls(self) -> int`
- `backend/src/hmap/agents/coding/model.py::CodingTrace.tokens`: `def tokens(self) -> int`
- `backend/src/hmap/agents/coding/model.py::CodingTrace.checks_passed`: `def checks_passed(self) -> bool`

## `backend/src/hmap/agents/coding/package.py`

“Where a task's workspace starts (plan D1), and how its result is stored (D2, D3).”

- `backend/src/hmap/agents/coding/package.py::Base`: `class Base`
- `backend/src/hmap/agents/coding/package.py::latest_head`: `async def latest_head(ctx: AgentContext) -> ArtifactRef | None`
- `backend/src/hmap/agents/coding/package.py::load_base`: `async def load_base(task: TaskAssign, ctx: AgentContext, ws: Workspace) -> Base`
- `backend/src/hmap/agents/coding/package.py::Stored`: `class Stored`
- `backend/src/hmap/agents/coding/package.py::summary_notes`: `def summary_notes(trace: CodingTrace) -> str`
- `backend/src/hmap/agents/coding/package.py::store`: “Write the head (rebasing if it moved), the workspace, the patch, the trace and the changeset.”

## `backend/src/hmap/agents/coding/plugin.py`

“Member 7 plug-in: autonomous coding (Sprint 7).”


## `backend/src/hmap/agents/coding/prompts.py`

“Prompts for the coding loop (plan D10, D13, D19, D22).”

- `backend/src/hmap/agents/coding/prompts.py::CodePlan`: `class CodePlan(BaseModel)`
- `backend/src/hmap/agents/coding/prompts.py::TaskView`: `class TaskView`
- `backend/src/hmap/agents/coding/prompts.py::TaskView.text`: `def text(self) -> str`
- `backend/src/hmap/agents/coding/prompts.py::TaskView.query`: `def query(self) -> str`
- `backend/src/hmap/agents/coding/prompts.py::requirements_part`: `def requirements_part(task: TaskView) -> Part | None`
- `backend/src/hmap/agents/coding/prompts.py::plan_messages`: `def plan_messages(task: TaskView, repo_map: str, files: list[tuple[str, str]], baseline: str, notes: list[str], budget: int) -> tuple[list[Message], list[str]]`
- `backend/src/hmap/agents/coding/prompts.py::plan_text`: `def plan_text(plan: CodePlan) -> str`
- `backend/src/hmap/agents/coding/prompts.py::edit_messages`: `def edit_messages(task: TaskView, plan: CodePlan | None, files: list[tuple[str, str]], feedback: str, repo_map: str, budget: int) -> tuple[list[Message], list[str]]`
- `backend/src/hmap/agents/coding/prompts.py::debug_messages`: `def debug_messages(task: TaskView, failures: str, output: str, notes: list[str], files: list[tuple[str, str]], feedback: str, repo_map: str, budget: int) -> tuple[list[Message], list[str]]`

## `backend/src/hmap/agents/coding/repomap.py`

“Repository map (Sprint 7 item 7.2, plan D9): a compact, budgeted outline of the workspace for prompts.”

- `backend/src/hmap/agents/coding/repomap.py::FileEntry`: `class FileEntry`
- `backend/src/hmap/agents/coding/repomap.py::FileEntry.is_python`: `def is_python(self) -> bool`
- `backend/src/hmap/agents/coding/repomap.py::parse_python`: `def parse_python(path: str, text: str) -> FileEntry`
- `backend/src/hmap/agents/coding/repomap.py::symbol_lines`: “``{name: (first line, last line)}`` for top-level functions/classes and ``Class.method`` (1-based).”
- `backend/src/hmap/agents/coding/repomap.py::RepoMap`: `class RepoMap`
- `backend/src/hmap/agents/coding/repomap.py::RepoMap.build`: `def build(cls, ws: Workspace, previous: 'RepoMap | None'=None) -> 'RepoMap'`
- `backend/src/hmap/agents/coding/repomap.py::RepoMap.render`: “The outline within ``budget_tokens``: focus files in full, the rest shortened as needed.”
- `backend/src/hmap/agents/coding/repomap.py::RepoMap.search_text`: “Identifiers + docstring for the locator (file name included).”

## `backend/src/hmap/agents/coding/review_hook.py`

“Self-review before returning (Sprint 7 item 7.11): Member 4's ``Refiner`` around the finished change.”

- `backend/src/hmap/agents/coding/review_hook.py::output_of`: `def output_of(loop: CodingLoop) -> dict[str, Any]`
- `backend/src/hmap/agents/coding/review_hook.py::check_issues`: `def check_issues(output: dict[str, Any], task_input: dict[str, Any]) -> list[Issue]`
- `backend/src/hmap/agents/coding/review_hook.py::render`: `def render(output: dict[str, Any], task_input: dict[str, Any]) -> str`
- `backend/src/hmap/agents/coding/review_hook.py::LoopReviser`: “One more fix round through the coding loop, with the critique as the requested changes.”
- `backend/src/hmap/agents/coding/review_hook.py::LoopReviser.__init__`: `def __init__(self, loop: CodingLoop) -> None`
- `backend/src/hmap/agents/coding/review_hook.py::LoopReviser.revise`: `async def revise(self, output: Any, critique: Critique, history: Sequence[Any], ctx: RefineContext, *, task_input: Any=None, strategy: str='targeted') -> Revision`
- `backend/src/hmap/agents/coding/review_hook.py::review`: “Run the self-review; leaves the workspace at the best attempt and notes the result in the trace.”

## `backend/src/hmap/agents/coding/revise.py`

“``code.revise`` inputs (Sprint 7 item 7.9, plan D14).”

- `backend/src/hmap/agents/coding/revise.py::revision_inputs`: `def revision_inputs(changeset_ref: ArtifactRef | dict[str, Any] | None, *, required_changes: list[str], round_: int=1, original_task_id: str | None=None) -> dict[str, Any]`
- `backend/src/hmap/agents/coding/revise.py::from_test_report`: `def from_test_report(report: TestReport) -> tuple[list[str], list[debug.Failure]]`
- `backend/src/hmap/agents/coding/revise.py::from_review_report`: `def from_review_report(report: ReviewReport, task_ids: set[str]) -> list[str]`
- `backend/src/hmap/agents/coding/revise.py::evidence_from_refs`: “Requested changes + located failures from the test / review reports handed to a revision.”

## `backend/src/hmap/agents/coding/router.py`

“Coding API (Sprint 7 item 7.14), mounted at ``/api/coding``.”

- `backend/src/hmap/agents/coding/router.py::ReviseIn`: `class ReviseIn(BaseModel)`
- `backend/src/hmap/agents/coding/router.py::summary`: `def summary(trace: dict[str, Any]) -> dict[str, Any]`
- `backend/src/hmap/agents/coding/router.py::list_runs`: `async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/coding/router.py::get_run`: `async def get_run(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/coding/router.py::get_diff`: `async def get_diff(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> str`
- `backend/src/hmap/agents/coding/router.py::get_files`: `async def get_files(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep, path: str | None=Query(default=None, max_length=500)) -> dict[str, Any]`
- `backend/src/hmap/agents/coding/router.py::download`: `async def download(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> Response`
- `backend/src/hmap/agents/coding/router.py::get_head`: `async def get_head(project_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/coding/router.py::request_changes`: “A human asks for changes to a coding step's result: a ``code.revise`` task (bounded rounds).”

## `backend/src/hmap/agents/coding/tools/__init__.py`

“The coding agent's tools (Sprint 7 item 7.4): files (read / list / search / write), edits, and checks run through the allow-listed :class:`~hmap.agents.coding.tools.runner.Runner`.”


## `backend/src/hmap/agents/coding/tools/checks.py`

“The agent's own checks (plan D12): compile, lint (errors only), the workspace's existing tests, and an import smoke test of the changed modules.”

- `backend/src/hmap/agents/coding/tools/checks.py::is_test_file`: `def is_test_file(rel: str) -> bool`
- `backend/src/hmap/agents/coding/tools/checks.py::module_name`: `def module_name(rel: str) -> str | None`
- `backend/src/hmap/agents/coding/tools/checks.py::CheckRun`: `class CheckRun`
- `backend/src/hmap/agents/coding/tools/checks.py::CheckRun.passed`: `def passed(self) -> bool`
- `backend/src/hmap/agents/coding/tools/checks.py::CheckRun.failures_for_model`: “Output of the failing commands, newest-first priority, capped (fed to the debugger).”
- `backend/src/hmap/agents/coding/tools/checks.py::CheckRun.failed_results`: `def failed_results(self) -> list[RunResult]`
- `backend/src/hmap/agents/coding/tools/checks.py::Checker`: `class Checker`
- `backend/src/hmap/agents/coding/tools/checks.py::Checker.__init__`: `def __init__(self, runner: Runner, *, cancelled: asyncio.Event | None=None) -> None`
- `backend/src/hmap/agents/coding/tools/checks.py::Checker.has_pytest`: `async def has_pytest(self, step: int) -> bool`
- `backend/src/hmap/agents/coding/tools/checks.py::Checker.run`: `async def run(self, step: int, changed: list[str] | None=None, *, tests: bool=True) -> CheckRun`

## `backend/src/hmap/agents/coding/tools/files.py`

“Read-only file tools for prompts: read (whole file or a line window), list, search (Sprint 7 item 7.4).”

- `backend/src/hmap/agents/coding/tools/files.py::wrap_file`: `def wrap_file(text: str, *, path: str, lines: tuple[int, int] | None=None) -> str`
- `backend/src/hmap/agents/coding/tools/files.py::injected_lines`: `def injected_lines(text: str) -> list[int]`
- `backend/src/hmap/agents/coding/tools/files.py::read_file`: “The file (or lines ``start..end``, 1-based, inclusive) wrapped for a prompt; an error text otherwise.”
- `backend/src/hmap/agents/coding/tools/files.py::list_files`: `def list_files(ws: Workspace, limit: int=200) -> str`
- `backend/src/hmap/agents/coding/tools/files.py::search`: “``path:line: text`` for lines containing ``pattern`` (case-insensitive).”

## `backend/src/hmap/agents/coding/tools/runner.py`

“Allow-listed command runner (Sprint 7 item 7.4, plan D5; ported from ``samples/coding/workspace.py``).”

- `backend/src/hmap/agents/coding/tools/runner.py::RunResult`: `class RunResult`
- `backend/src/hmap/agents/coding/tools/runner.py::RunResult.ok`: `def ok(self) -> bool`
- `backend/src/hmap/agents/coding/tools/runner.py::RunResult.for_model`: `def for_model(self, cap: int=MODEL_OUTPUT_CAP) -> str`
- `backend/src/hmap/agents/coding/tools/runner.py::normalise`: “Make command output replay-stable and free of local paths.”
- `backend/src/hmap/agents/coding/tools/runner.py::Runner`: `class Runner`
- `backend/src/hmap/agents/coding/tools/runner.py::Runner.__init__`: `def __init__(self, ws: Workspace, settings: Settings) -> None`
- `backend/src/hmap/agents/coding/tools/runner.py::Runner.plan`: “(real argv, needs sandbox) for an allowed command; raises :class:`JailError` otherwise.”
- `backend/src/hmap/agents/coding/tools/runner.py::Runner.env`: `def env(self) -> dict[str, str]`
- `backend/src/hmap/agents/coding/tools/runner.py::Runner.run`: `async def run(self, cmd: str | Sequence[str], *, timeout: float | None=None, cancelled: asyncio.Event | None=None) -> RunResult`

## `backend/src/hmap/agents/coding/tools/sandbox.py`

“Which interpreter runs model-written code, and the best-effort macOS sandbox around it (plan D6, Q2/Q3).”

- `backend/src/hmap/agents/coding/tools/sandbox.py::base_python`: `def base_python() -> str`
- `backend/src/hmap/agents/coding/tools/sandbox.py::interpreter`: `def interpreter(settings: Settings) -> str`
- `backend/src/hmap/agents/coding/tools/sandbox.py::ruff_binary`: “The backend's ruff: it reads code and never runs it, so it needs no sandbox.”
- `backend/src/hmap/agents/coding/tools/sandbox.py::sandbox_available`: `def sandbox_available(settings: Settings) -> bool`
- `backend/src/hmap/agents/coding/tools/sandbox.py::profile`: `def profile(workspace: Path) -> str`
- `backend/src/hmap/agents/coding/tools/sandbox.py::wrap`: `def wrap(argv: list[str], workspace: Path, settings: Settings) -> list[str]`

## `backend/src/hmap/agents/coding/workspace.py`

“Per-task workspace with a path jail (Sprint 7 item 7.1, ported from ``samples/coding/workspace.py``).”

- `backend/src/hmap/agents/coding/workspace.py::JailError`: “A path or command the agent may not use.”
- `backend/src/hmap/agents/coding/workspace.py::WorkspaceTooLarge`: “A tree or tarball over the size / file-count caps.”
- `backend/src/hmap/agents/coding/workspace.py::skipped`: `def skipped(rel: str) -> bool`
- `backend/src/hmap/agents/coding/workspace.py::Workspace`: `class Workspace`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.path`: `def path(self, rel: str) -> Path`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.rel`: “The normalised workspace-relative form of ``rel`` (after the jail check).”
- `backend/src/hmap/agents/coding/workspace.py::Workspace.deny`: `def deny(self, kind: str, what: str, reason: str) -> JailError`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.exists`: `def exists(self, rel: str) -> bool`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.is_file`: `def is_file(self, rel: str) -> bool`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.read`: `def read(self, rel: str) -> str`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.write`: `def write(self, rel: str, text: str) -> None`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.write_tool_file`: “A helper script of the agent's own under ``.tmp/`` (never packed, never shown as a change).”
- `backend/src/hmap/agents/coding/workspace.py::Workspace.delete`: `def delete(self, rel: str) -> None`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.files`: `def files(self, suffix: str='') -> list[str]`
- `backend/src/hmap/agents/coding/workspace.py::Workspace.snapshot`: “``{path: text}`` of every text file (binary files are left out of prompts and diffs).”
- `backend/src/hmap/agents/coding/workspace.py::Workspace.restore`: “Make the text files exactly ``files`` (used to roll a failed merge back).”
- `backend/src/hmap/agents/coding/workspace.py::work_root`: “Where per-task workspaces live: never inside the project folder (``.env`` is there).”
- `backend/src/hmap/agents/coding/workspace.py::safe_name`: `def safe_name(text: str) -> str`
- `backend/src/hmap/agents/coding/workspace.py::new_workspace`: `def new_workspace(settings: Settings, project_id: str, task_id: str, execution_id: str) -> Workspace`
- `backend/src/hmap/agents/coding/workspace.py::remove_workspace`: `def remove_workspace(ws: Workspace, settings: Settings) -> None`
- `backend/src/hmap/agents/coding/workspace.py::pack`: “Deterministic ``.tar.gz`` of the workspace (same tree → same bytes).”
- `backend/src/hmap/agents/coding/workspace.py::unpack`: “Extract a workspace tarball into ``ws`` safely; returns the files written.”
- `backend/src/hmap/agents/coding/workspace.py::files_from_tar`: “Text files of a workspace tarball, read in memory (the API's file viewer; no extraction).”
- `backend/src/hmap/agents/coding/workspace.py::unified_diff`: `def unified_diff(before: dict[str, str], after: dict[str, str]) -> str`
- `backend/src/hmap/agents/coding/workspace.py::changed_files`: `def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]`
- `backend/src/hmap/agents/coding/workspace.py::merge3`: “Line-based three-way merge: ``ours`` and ``theirs`` both changed ``base``.”
- `backend/src/hmap/agents/coding/workspace.py::rebase`: “Re-apply the change ``base → ours`` on ``head`` (the project head moved meanwhile).”

## `backend/src/hmap/agents/doc_intel/__init__.py`

“Member 2 - document intelligence: uploaded documents -> a traceable RequirementSet (Sprint 2).”


## `backend/src/hmap/agents/doc_intel/agent.py`

“``DocIntelAgent`` (spec item 2.8): the real ``document.extract`` capability.”

- `backend/src/hmap/agents/doc_intel/agent.py::LruCache`: “Bounded in-process cache (vision OCR per page, LLM extraction per chunk).”
- `backend/src/hmap/agents/doc_intel/agent.py::LruCache.__init__`: `def __init__(self, max_entries: int=512) -> None`
- `backend/src/hmap/agents/doc_intel/agent.py::LruCache.get`: `async def get(self, key: str) -> str | None`
- `backend/src/hmap/agents/doc_intel/agent.py::LruCache.put`: `async def put(self, key: str, value: str) -> None`
- `backend/src/hmap/agents/doc_intel/agent.py::document_name`: `def document_name(ref_id: str, media_type: str, meta: dict[str, Any], *, only_one: bool, index: int) -> str`
- `backend/src/hmap/agents/doc_intel/agent.py::DocIntelAgent`: `class DocIntelAgent(BaseAgent)`
- `backend/src/hmap/agents/doc_intel/agent.py::DocIntelAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/agents/doc_intel/cache.py`

“Small key -> text cache for expensive steps (vision OCR of a page, LLM extraction of a chunk), so a redelivered task or a re-run on the same document does no model work twice.”

- `backend/src/hmap/agents/doc_intel/cache.py::ResultCache`: `class ResultCache(Protocol)`
- `backend/src/hmap/agents/doc_intel/cache.py::ResultCache.get`: `async def get(self, key: str) -> str | None`
- `backend/src/hmap/agents/doc_intel/cache.py::ResultCache.put`: `async def put(self, key: str, value: str) -> None`
- `backend/src/hmap/agents/doc_intel/cache.py::MemoryCache`: `class MemoryCache`
- `backend/src/hmap/agents/doc_intel/cache.py::MemoryCache.__init__`: `def __init__(self) -> None`
- `backend/src/hmap/agents/doc_intel/cache.py::MemoryCache.get`: `async def get(self, key: str) -> str | None`
- `backend/src/hmap/agents/doc_intel/cache.py::MemoryCache.put`: `async def put(self, key: str, value: str) -> None`
- `backend/src/hmap/agents/doc_intel/cache.py::cache_key`: “``<kind>-<sha256 prefix>``: only ``[a-z0-9-]``, safe as an artifact id.”

## `backend/src/hmap/agents/doc_intel/chunking.py`

“Section-aligned chunks within a token budget (spec item 2.4).”

- `backend/src/hmap/agents/doc_intel/chunking.py::estimate_tokens`: “~4 characters per token for English prose (good enough for budgeting; the gateway has no tokenizer).”
- `backend/src/hmap/agents/doc_intel/chunking.py::Chunk`: `class Chunk`
- `backend/src/hmap/agents/doc_intel/chunking.py::Chunk.text`: “What the model sees: a header line, then headings as Markdown and list items as "- " lines.”
- `backend/src/hmap/agents/doc_intel/chunking.py::Chunk.tokens`: `def tokens(self) -> int`
- `backend/src/hmap/agents/doc_intel/chunking.py::make_chunks`: “Whole sections are packed into a chunk while they fit; a new chunk starts at a section boundary; only a single section larger than the budget is split between blocks.”

## `backend/src/hmap/agents/doc_intel/extract/__init__.py`

“Extraction: rule pre-pass, LLM per chunk, quote verification.”


## `backend/src/hmap/agents/doc_intel/extract/llm.py`

“LLM extraction per chunk (spec item 2.5): one schema-constrained ``reasoner`` call, the rule hits as hints, the answer cached by chunk text + prompt version.”

- `backend/src/hmap/agents/doc_intel/extract/llm.py::ExtractedItem`: `class ExtractedItem(BaseModel)`
- `backend/src/hmap/agents/doc_intel/extract/llm.py::ChunkExtraction`: `class ChunkExtraction(BaseModel)`
- `backend/src/hmap/agents/doc_intel/extract/llm.py::build_messages`: `def build_messages(chunk: Chunk, hints: list[RuleHit]) -> list[Message]`
- `backend/src/hmap/agents/doc_intel/extract/llm.py::extract_chunk`: “The extraction and who answered it: ``provider:model`` (``cache:<model>`` when replayed), or ``memory`` when this agent had already extracted the same chunk.”

## `backend/src/hmap/agents/doc_intel/extract/quotes.py`

“Quote verification (spec §9 "quote required"): every extracted item must quote its source; the quote is looked up in the chunk's blocks.”

- `backend/src/hmap/agents/doc_intel/extract/quotes.py::normalize`: `def normalize(text: str) -> str`
- `backend/src/hmap/agents/doc_intel/extract/quotes.py::words`: `def words(text: str) -> list[str]`
- `backend/src/hmap/agents/doc_intel/extract/quotes.py::overlap`: “Share of ``a``'s content words that appear in ``b`` (0..1).”
- `backend/src/hmap/agents/doc_intel/extract/quotes.py::jaccard`: `def jaccard(a: str, b: str) -> float`
- `backend/src/hmap/agents/doc_intel/extract/quotes.py::QuoteMatch`: `class QuoteMatch`
- `backend/src/hmap/agents/doc_intel/extract/quotes.py::locate`: “Find ``quote`` (or, without one, ``fallback_text``) in ``blocks``.”

## `backend/src/hmap/agents/doc_intel/extract/rules.py`

“Rule pre-pass (spec item 2.5): keyword patterns find candidate requirements, constraints and deliverables with exact spans.”

- `backend/src/hmap/agents/doc_intel/extract/rules.py::RuleHit`: `class RuleHit`
- `backend/src/hmap/agents/doc_intel/extract/rules.py::priority_of`: `def priority_of(text: str) -> str`
- `backend/src/hmap/agents/doc_intel/extract/rules.py::constraint_kind`: `def constraint_kind(text: str) -> str`
- `backend/src/hmap/agents/doc_intel/extract/rules.py::sentences`: `def sentences(text: str) -> list[str]`
- `backend/src/hmap/agents/doc_intel/extract/rules.py::classify_sentence`: `def classify_sentence(sentence: str, block: Block) -> str | None`
- `backend/src/hmap/agents/doc_intel/extract/rules.py::is_lead_in`: “"At minimum, your code needs to support:" introduces a list; it is context, not an item.”
- `backend/src/hmap/agents/doc_intel/extract/rules.py::lead_in_kind`: “Items under a lead-in are requirements unless the lead-in (or its section) says deliverables/constraints.”
- `backend/src/hmap/agents/doc_intel/extract/rules.py::rule_pass`: `def rule_pass(docs: list[SourceDocument]) -> list[RuleHit]`

## `backend/src/hmap/agents/doc_intel/loaders/__init__.py`

“Loaders (spec item 2.1): PDF (native or scanned), DOCX, text / Markdown and images, with per-page OCR gating.”

- `backend/src/hmap/agents/doc_intel/loaders/__init__.py::InputDocument`: `class InputDocument`
- `backend/src/hmap/agents/doc_intel/loaders/__init__.py::detect_kind`: `def detect_kind(name: str, media_type: str, data: bytes) -> str`
- `backend/src/hmap/agents/doc_intel/loaders/__init__.py::load_document`: `async def load_document(doc: InputDocument, ocr: 'OcrEngine', on_page: PageProgress | None=None) -> Loaded`

## `backend/src/hmap/agents/doc_intel/loaders/base.py`

“What every loader produces: an ordered list of :class:`RawBlock` per document (before ids and section paths are assigned by ``structure.py``), plus page info and warnings.”

- `backend/src/hmap/agents/doc_intel/loaders/base.py::strip_marker`: “Remove a leading list marker; returns (text, had_marker).”
- `backend/src/hmap/agents/doc_intel/loaders/base.py::clean_spaces`: “Collapse whitespace (incl.”
- `backend/src/hmap/agents/doc_intel/loaders/base.py::drop_cids`: “pdfminer writes glyphs it cannot map as ``(cid:N)``; at the start of a line they are bullets.”
- `backend/src/hmap/agents/doc_intel/loaders/base.py::join_lines`: “Join wrapped lines; undo end-of-line hyphenation ("require-" + "ment" -> "requirement").”
- `backend/src/hmap/agents/doc_intel/loaders/base.py::rows_to_markdown`: `def rows_to_markdown(rows: list[list[str]]) -> str`
- `backend/src/hmap/agents/doc_intel/loaders/base.py::RawBlock`: `class RawBlock`
- `backend/src/hmap/agents/doc_intel/loaders/base.py::Loaded`: `class Loaded`

## `backend/src/hmap/agents/doc_intel/loaders/docx.py`

“DOCX (python-docx): body paragraphs and tables in document order.”

- `backend/src/hmap/agents/doc_intel/loaders/docx.py::load_docx`: `def load_docx(data: bytes) -> Loaded`

## `backend/src/hmap/agents/doc_intel/loaders/pdf.py`

“Native PDF text with positions (pdfplumber) and page rendering for OCR (pypdfium2).”

- `backend/src/hmap/agents/doc_intel/loaders/pdf.py::render_page_png`: `def render_page_png(data: bytes, page_number: int, dpi: int=OCR_DPI) -> bytes`
- `backend/src/hmap/agents/doc_intel/loaders/pdf.py::load_pdf`: “Synchronous (run it in a thread).”

## `backend/src/hmap/agents/doc_intel/loaders/text.py`

“Plain text and Markdown (also used for the vision model's page transcriptions, which are asked for Markdown).”

- `backend/src/hmap/agents/doc_intel/loaders/text.py::parse_markdown`: “Headings (``#``), list items (``-``, ``*``, ``1.``), pipe tables and paragraphs separated by blank lines.”
- `backend/src/hmap/agents/doc_intel/loaders/text.py::load_text`: `def load_text(data: bytes) -> Loaded`

## `backend/src/hmap/agents/doc_intel/merge.py`

“Merge, dedup and ids (spec item 2.6).”

- `backend/src/hmap/agents/doc_intel/merge.py::Candidate`: `class Candidate`
- `backend/src/hmap/agents/doc_intel/merge.py::Candidate.order`: `def order(self) -> tuple[int, int, int]`
- `backend/src/hmap/agents/doc_intel/merge.py::Candidate.source_ref`: `def source_ref(self) -> SourceRef`
- `backend/src/hmap/agents/doc_intel/merge.py::dedup`: “Same item twice (e.g.”
- `backend/src/hmap/agents/doc_intel/merge.py::Assembled`: `class Assembled`
- `backend/src/hmap/agents/doc_intel/merge.py::assemble`: `def assemble(candidates: list[Candidate]) -> Assembled`

## `backend/src/hmap/agents/doc_intel/model.py`

“``DocumentModel``: the normalised view of every uploaded document (spec §4), stored as the ``document-model`` artifact so the UI can show each requirement's source and highlight it.”

- `backend/src/hmap/agents/doc_intel/model.py::Block`: `class Block(BaseModel)`
- `backend/src/hmap/agents/doc_intel/model.py::TableModel`: `class TableModel(BaseModel)`
- `backend/src/hmap/agents/doc_intel/model.py::PageInfo`: `class PageInfo(BaseModel)`
- `backend/src/hmap/agents/doc_intel/model.py::SourceDocument`: `class SourceDocument(BaseModel)`
- `backend/src/hmap/agents/doc_intel/model.py::SourceDocument.block`: `def block(self, block_id: str) -> Block | None`
- `backend/src/hmap/agents/doc_intel/model.py::ExtractionInfo`: “How the set was made (shown in the UI's developer mode and kept for audits).”
- `backend/src/hmap/agents/doc_intel/model.py::DocumentModel`: `class DocumentModel(BaseModel)`

## `backend/src/hmap/agents/doc_intel/ocr.py`

“OCR for scanned pages and photos (spec item 2.1, plan §0).”

- `backend/src/hmap/agents/doc_intel/ocr.py::OcrOutcome`: `class OcrOutcome`
- `backend/src/hmap/agents/doc_intel/ocr.py::tesseract_available`: `def tesseract_available() -> bool`
- `backend/src/hmap/agents/doc_intel/ocr.py::OcrEngine`: `class OcrEngine`
- `backend/src/hmap/agents/doc_intel/ocr.py::OcrEngine.__init__`: `def __init__(self, llm: LLMClient | None, cache: ResultCache | None=None, *, use_tesseract: bool | None=None) -> None`
- `backend/src/hmap/agents/doc_intel/ocr.py::OcrEngine.read`: `async def read(self, png: bytes, page: int | None) -> OcrOutcome`

## `backend/src/hmap/agents/doc_intel/pipeline.py`

“The document-intelligence pipeline (spec §4), independent of the bus so the agent, the tests and the eval harness all run the same code:”

- `backend/src/hmap/agents/doc_intel/pipeline.py::PipelineStats`: `class PipelineStats`
- `backend/src/hmap/agents/doc_intel/pipeline.py::PipelineResult`: `class PipelineResult`
- `backend/src/hmap/agents/doc_intel/pipeline.py::run_pipeline`: `async def run_pipeline(project_id: str, inputs: list[InputDocument], llm: LLMClient | None, *, source_refs: list[ArtifactRef] | None=None, cache: ResultCache | None=None, progress: ProgressFn | None=None, check_cancelled: Callable[[], None] | None=None, use_llm: bool=True, budget: int=DEFAULT_BUDGET_TOKENS) -> PipelineResult`

## `backend/src/hmap/agents/doc_intel/plugin.py`

“Member 2 plug-in: document intelligence (Sprint 2).”

- `backend/src/hmap/agents/doc_intel/plugin.py::announce_requirements`: `async def announce_requirements(event: DomainEvent, manager: ManagerHandle) -> None`

## `backend/src/hmap/agents/doc_intel/router.py`

“API (spec item 2.10), mounted at ``/api/doc_intel``.”

- `backend/src/hmap/agents/doc_intel/router.py::RequirementsEdit`: `class RequirementsEdit(BaseModel)`
- `backend/src/hmap/agents/doc_intel/router.py::get_requirements`: `async def get_requirements(project_id: str, info: CurrentSession, m: ManagerDep, artifact_id: str | None=None, version: Annotated[int | None, Query(ge=1)]=None) -> dict[str, Any]`
- `backend/src/hmap/agents/doc_intel/router.py::edit_requirements`: `async def edit_requirements(project_id: str, body: RequirementsEdit, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/doc_intel/router.py::get_document_model`: `async def get_document_model(project_id: str, info: CurrentSession, m: ManagerDep) -> Response`
- `backend/src/hmap/agents/doc_intel/router.py::page_image`: `async def page_image(project_id: str, artifact_id: str, page: int, info: CurrentSession, m: ManagerDep) -> Response`

## `backend/src/hmap/agents/doc_intel/structure.py`

“Normalisation (spec item 2.2): loader output -> :class:`SourceDocument` with block ids, heading levels, section paths, table models and character offsets into one document text.”

- `backend/src/hmap/agents/doc_intel/structure.py::build_document`: `def build_document(doc: InputDocument, loaded: Loaded, kind: str | None=None) -> SourceDocument`

## `backend/src/hmap/agents/doc_intel/tables.py`

“Tables (spec item 2.3): marks / rubric tables -> evaluation criteria, deliverables tables -> deliverables.”

- `backend/src/hmap/agents/doc_intel/tables.py::CriterionRow`: `class CriterionRow`
- `backend/src/hmap/agents/doc_intel/tables.py::TableReading`: `class TableReading`
- `backend/src/hmap/agents/doc_intel/tables.py::fill_down`: “Merged cells: an empty cell in the first ``columns`` columns takes the value from the row above.”
- `backend/src/hmap/agents/doc_intel/tables.py::read_table`: `def read_table(rows: list[list[str]]) -> TableReading`
- `backend/src/hmap/agents/doc_intel/tables.py::stated_total`: “The total marks a document states in prose ("Total: 100 marks", "worth 50 marks in total").”

## `backend/src/hmap/agents/doc_intel/validate.py`

“Validation (spec item 2.7): the guarantees handed to Member 3 (spec §7).”

- `backend/src/hmap/agents/doc_intel/validate.py::Report`: `class Report`
- `backend/src/hmap/agents/doc_intel/validate.py::check`: `def check(rs: RequirementSet, stated_totals: list[float]) -> Report`

## `backend/src/hmap/agents/docgen/__init__.py`

“Technical documentation agent (Member 9, Sprint 9): ``docs.generate`` / ``docs.update``.”


## `backend/src/hmap/agents/docgen/agent.py`

“``DocAgent`` (Sprint 9 item 9.10): the real ``docs.generate`` and ``docs.update``.”

- `backend/src/hmap/agents/docgen/agent.py::latest_of_type`: `async def latest_of_type(ctx: AgentContext, artifact_type: str) -> ArtifactRef | None`
- `backend/src/hmap/agents/docgen/agent.py::find_workspace`: `async def find_workspace(task: TaskAssign, ctx: AgentContext) -> tuple[ArtifactRef | None, str]`
- `backend/src/hmap/agents/docgen/agent.py::supplied_files`: “``inputs.files``: the code given with the task (``{"server.py": "..."}``), e.g.”
- `backend/src/hmap/agents/docgen/agent.py::sanitize_files`: “Repository files are untrusted (plan D15): AI-directed lines are blanked (line numbers stay) and listed.”
- `backend/src/hmap/agents/docgen/agent.py::fact_hashes`: “Which facts each document depends on (``docs.update`` regenerates a document only when its hash moved).”
- `backend/src/hmap/agents/docgen/agent.py::DocAgent`: `class DocAgent(BaseAgent)`
- `backend/src/hmap/agents/docgen/agent.py::DocAgent.__init__`: `def __init__(self, settings: Settings | None=None, **deps: Any) -> None`
- `backend/src/hmap/agents/docgen/agent.py::DocAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/agents/docgen/api_docs.py`

“API documentation (Sprint 9 item 9.5, plan D6): one section per HTTP endpoint the code defines.”

- `backend/src/hmap/agents/docgen/api_docs.py::app_location`: “(dotted module, variable) of a ``FastAPI()`` app assigned at module level.”
- `backend/src/hmap/agents/docgen/api_docs.py::routes_from_openapi`: “OpenAPI -> routes; file / handler are taken from the AST route with the same handler name when present.”
- `backend/src/hmap/agents/docgen/api_docs.py::openapi_in_sandbox`: “Import the generated app in Member 8's sandbox and read its OpenAPI document.”
- `backend/src/hmap/agents/docgen/api_docs.py::render`: `def render(facts: Facts, routes: list[Route] | None=None, title: str | None=None) -> str`

## `backend/src/hmap/agents/docgen/architecture.py`

“Architecture extractor (Sprint 9 item 9.2, plan D4): import graph -> components -> Mermaid.”

- `backend/src/hmap/agents/docgen/architecture.py::Component`: `class Component`
- `backend/src/hmap/agents/docgen/architecture.py::Architecture`: `class Architecture`
- `backend/src/hmap/agents/docgen/architecture.py::Architecture.graph`: “JSON for the UI (drawn with @xyflow/react).”
- `backend/src/hmap/agents/docgen/architecture.py::code_modules`: “The repository's code modules (no tests, no migrations, no data files that only look like modules: a ``.py`` inside a package tree whose own folder is not a package, e.g.”
- `backend/src/hmap/agents/docgen/architecture.py::module_graph`: `def module_graph(facts: Facts, within: str | None=None) -> nx.DiGraph`
- `backend/src/hmap/agents/docgen/architecture.py::extract`: “Components at the deepest package level with at most ``max_nodes`` nodes; ``within`` = only that package (the detail diagram of one component).”
- `backend/src/hmap/agents/docgen/architecture.py::mermaid`: `def mermaid(arch: Architecture, *, externals: bool=True) -> str`
- `backend/src/hmap/agents/docgen/architecture.py::parse_mermaid`: “A small grammar check for the subset we write: raises ``ValueError`` on any other line.”
- `backend/src/hmap/agents/docgen/architecture.py::check_edges`: “Every solid edge of the diagram must be an import in the code (item 9.2 acceptance).”
- `backend/src/hmap/agents/docgen/architecture.py::render_doc`: “The architecture document: overview diagram, components, one detail diagram per package, libraries.”
- `backend/src/hmap/agents/docgen/architecture.py::details`: “Detail diagrams for the folded components with more than one module (largest first).”

## `backend/src/hmap/agents/docgen/compile_report.py`

“Final-report compiler (Sprint 9 item 9.20): ``make report`` gathers every member's ``docs/members/<n>/{research,design,eval}.md`` into one report skeleton, in member order.”

- `backend/src/hmap/agents/docgen/compile_report.py::member_dirs`: `def member_dirs(docs: Path) -> list[Path]`
- `backend/src/hmap/agents/docgen/compile_report.py::title_of`: “The member's subsystem, from the first heading of their README or plan (else "Member <n>").”
- `backend/src/hmap/agents/docgen/compile_report.py::shift`: `def shift(md: str, levels: int, source: Path, out_dir: Path) -> str`
- `backend/src/hmap/agents/docgen/compile_report.py::compile_report`: `def compile_report(root: Path=REPO_ROOT, out: Path | None=None) -> tuple[Path, list[str]]`
- `backend/src/hmap/agents/docgen/compile_report.py::main`: `def main() -> None`

## `backend/src/hmap/agents/docgen/config_reference.py`

“Configuration reference (Sprint 9 item 9.17, plan P5), generated from the code: every environment variable that ``Settings.from_env`` reads, its type, default and description (the field's ``description``, else the comment in ``.env.example`”

- `backend/src/hmap/agents/docgen/config_reference.py::Var`: `class Var`
- `backend/src/hmap/agents/docgen/config_reference.py::env_vars_in_code`: “Every ``HMAP_*`` / ``OLLAMA_*`` string the settings loader reads, mapped to its field (from the AST of ``from_env``: the mapping dict, the ``(name, field)`` pairs and the ``get("X")`` calls).”
- `backend/src/hmap/agents/docgen/config_reference.py::env_example`: “name -> (value, comment, group heading) as written in ``.env.example`` (commented-out lines too).”
- `backend/src/hmap/agents/docgen/config_reference.py::variables`: `def variables() -> list[Var]`
- `backend/src/hmap/agents/docgen/config_reference.py::env_vars_elsewhere`: “Read outside the settings loader: ``os.environ`` in the backend (the facts extractor) and ``${HMAP_X}`` in the compose files.”
- `backend/src/hmap/agents/docgen/config_reference.py::drift`: `def drift() -> dict[str, list[str]]`
- `backend/src/hmap/agents/docgen/config_reference.py::render`: `def render() -> str`
- `backend/src/hmap/agents/docgen/config_reference.py::main`: `def main() -> None`

## `backend/src/hmap/agents/docgen/examples.py`

“Code-example / command verifier (Sprint 9 item 9.7, plan D8): documented snippets run in Member 8's sandbox.”

- `backend/src/hmap/agents/docgen/examples.py::collect`: `def collect(docs: dict[str, str]) -> list[ExampleResult]`
- `backend/src/hmap/agents/docgen/examples.py::classify`: `def classify(ex: ExampleResult, facts: Facts) -> ExampleResult`
- `backend/src/hmap/agents/docgen/examples.py::verify`: “Classify every snippet and run the runnable ones (one sandbox call).”

## `backend/src/hmap/agents/docgen/export.py`

“Exports (Sprint 9 stretch): the architecture graph as SVG, every document as one static HTML page (docs-as-site, no build tool, no JavaScript), the changelog between two sets of facts, and a docstring patch.”

- `backend/src/hmap/agents/docgen/export.py::layout`: “Columns by import depth (components), libraries and services last; the same layout as the Docs tab.”
- `backend/src/hmap/agents/docgen/export.py::svg`: `def svg(graph: dict[str, Any], title: str='Architecture') -> str`
- `backend/src/hmap/agents/docgen/export.py::markdown_html`: “A small Markdown -> HTML converter for our own documents (headings, lists, tables, code); everything escaped.”
- `backend/src/hmap/agents/docgen/export.py::site`: “Every document on one static page with a navigation bar; the architecture SVG inline (it is our own SVG).”
- `backend/src/hmap/agents/docgen/export.py::changelog`: “What changed in the code between two documentation runs, as plain sentences (for docs.update).”
- `backend/src/hmap/agents/docgen/export.py::docstring_patch`: “A unified diff that adds the model's summaries as docstrings to public functions / classes that have none.”

## `backend/src/hmap/agents/docgen/grounding/__init__.py`

“Grounding checker (Sprint 9 item 9.6, plan D7): every technical claim of the generated documents, checked against the facts of the repository.”

- `backend/src/hmap/agents/docgen/grounding/__init__.py::rule_claims`: `def rule_claims(markdown: str, facts: Facts, doc: str='') -> list[Claim]`
- `backend/src/hmap/agents/docgen/grounding/__init__.py::summarize`: `def summarize(claims: list[Claim], removed: list[Claim] | None=None) -> Accuracy`
- `backend/src/hmap/agents/docgen/grounding/__init__.py::check_documents`: “-> (accuracy, stats ``{model_calls, tokens, behaviour}``).”
- `backend/src/hmap/agents/docgen/grounding/__init__.py::remove_sentences`: “Final gate (plan D9): drop each ungrounded sentence (or table row / command line) from the document.”

## `backend/src/hmap/agents/docgen/grounding/behaviour.py`

“Model layer of the grounding checker (Sprint 9 item 9.6, plan D7): claims about *behaviour* that rules cannot read ("nicknames are case-sensitive", "the server closes idle connections").”

- `backend/src/hmap/agents/docgen/grounding/behaviour.py::candidates`: “Prose sentences that state behaviour and that no rule already checked (headings, tables, lists of commands and sentences with a rule claim are skipped).”
- `backend/src/hmap/agents/docgen/grounding/behaviour.py::evidence`: “The ``limit`` code windows sharing the most words with the sentence (path:line headers).”
- `backend/src/hmap/agents/docgen/grounding/behaviour.py::check`: “-> (claims, model calls, tokens, why skipped).”

## `backend/src/hmap/agents/docgen/grounding/rules.py`

“Rule layer of the grounding checker (Sprint 9 item 9.6, plan D7; ported from ``samples/docgen/grounding.py``).”

- `backend/src/hmap/agents/docgen/grounding/rules.py::Located`: “A sentence and where it sits in the document (1-based line).”
- `backend/src/hmap/agents/docgen/grounding/rules.py::version_ok`: “``Python 3.11`` vs ``>=3.11``; ``FastAPI 0.115`` vs ``==0.115.6``; ``^18.3.1`` (npm) vs ``18.3``.”
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker`: `class Checker`
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.__init__`: `def __init__(self, facts: Facts) -> None`
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.path_exists`: `def path_exists(self, p: str) -> bool`
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.ignored`: “Git-ignored paths (``.env``, ``data/``, ``logs/``) are made at run time: mentioning them is fine.”
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.evidence`: `def evidence(self, ev: str) -> str | None`
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.tech`: `def tech(self, name: str) -> Claim`
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.endpoint`: `def endpoint(self, method: str, path: str) -> Claim`
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.command`: `def command(self, line: str) -> Claim`
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.span`: “One inline code span: a command, endpoint, flag, env var, symbol, citation or path.”
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.citation`: `def citation(self, path: str, name: str) -> Claim`
- `backend/src/hmap/agents/docgen/grounding/rules.py::Checker.check`: `def check(self, markdown: str, doc: str='') -> list[Claim]`
- `backend/src/hmap/agents/docgen/grounding/rules.py::sentences`: “Sentences with their line; a table row, list item or heading is its own sentence.”
- `backend/src/hmap/agents/docgen/grounding/rules.py::joined_lines`: “Command lines of a shell block, with ``\`` continuations joined (line index of the first part).”

## `backend/src/hmap/agents/docgen/hooks.py`

“Manager hooks of the documentation agent (Sprint 9, plan D12).”

- `backend/src/hmap/agents/docgen/hooks.py::on_docs_done`: `async def on_docs_done(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/docgen/hooks.py::on_docs_updated`: `async def on_docs_updated(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/docgen/hooks.py::on_code_completed`: `async def on_code_completed(event: DomainEvent, manager: ManagerHandle) -> None`

## `backend/src/hmap/agents/docgen/inspect/__init__.py`

“Facts extractor (Sprint 9 item 9.1, plan D3): everything a repository really contains, from the files alone.”

- `backend/src/hmap/agents/docgen/inspect/__init__.py::read_tree`: “Text files under ``root`` (repo-relative POSIX paths), skipping caches, virtualenvs and ``.env`` files.”
- `backend/src/hmap/agents/docgen/inspect/__init__.py::inspect_files`: “``listing``: other paths of the repository, names only (they exist; their contents are not facts).”

## `backend/src/hmap/agents/docgen/inspect/javascript.py`

“JavaScript / TypeScript facts (Sprint 9 stretch: multi-language inspector).”

- `backend/src/hmap/agents/docgen/inspect/javascript.py::is_js`: `def is_js(path: str) -> bool`
- `backend/src/hmap/agents/docgen/inspect/javascript.py::is_js_test`: `def is_js_test(path: str) -> bool`
- `backend/src/hmap/agents/docgen/inspect/javascript.py::resolve`: `def resolve(from_path: str, spec: str, files: set[str]) -> str | None`
- `backend/src/hmap/agents/docgen/inspect/javascript.py::module_facts`: `def module_facts(rel: str, text: str, files: set[str]) -> tuple[ModuleFacts, RepoBits]`

## `backend/src/hmap/agents/docgen/inspect/manifests.py`

“Facts from manifests and infrastructure files (Sprint 9 item 9.1): declared dependencies (``requirements*.txt``, ``pyproject.toml`` incl.”

- `backend/src/hmap/agents/docgen/inspect/manifests.py::requirement_name`: `def requirement_name(spec: str) -> tuple[str, str]`
- `backend/src/hmap/agents/docgen/inspect/manifests.py::read_manifest`: `def read_manifest(rel: str, text: str, facts: Facts) -> None`

## `backend/src/hmap/agents/docgen/inspect/python.py`

“Python facts from the AST (Sprint 9 item 9.1, ported from ``samples/docgen/inspect_repo.py``).”

- `backend/src/hmap/agents/docgen/inspect/python.py::RepoBits`: “What a module adds to the repository-wide facts (merged by ``inspect.inspect_files``).”
- `backend/src/hmap/agents/docgen/inspect/python.py::module_facts`: “Facts of one Python file.”
- `backend/src/hmap/agents/docgen/inspect/python.py::module_name`: “Dotted name of a file: the path from the nearest folder that is not a package (has no ``__init__.py``).”

## `backend/src/hmap/agents/docgen/model.py`

“Data of the documentation agent (Sprint 9, plan D3, D11): the facts a repository really contains, the claims a document makes, and the trace of one run.”

- `backend/src/hmap/agents/docgen/model.py::bundle_id`: `def bundle_id(task_id: str) -> str`
- `backend/src/hmap/agents/docgen/model.py::doc_id`: `def doc_id(name: str, task_id: str) -> str`
- `backend/src/hmap/agents/docgen/model.py::facts_id`: `def facts_id(task_id: str) -> str`
- `backend/src/hmap/agents/docgen/model.py::accuracy_id`: `def accuracy_id(task_id: str) -> str`
- `backend/src/hmap/agents/docgen/model.py::trace_id`: `def trace_id(task_id: str) -> str`
- `backend/src/hmap/agents/docgen/model.py::docstrings_id`: `def docstrings_id(task_id: str) -> str`
- `backend/src/hmap/agents/docgen/model.py::head_id`: `def head_id(project_id: str) -> str`
- `backend/src/hmap/agents/docgen/model.py::Symbol`: `class Symbol(BaseModel)`
- `backend/src/hmap/agents/docgen/model.py::ModuleFacts`: `class ModuleFacts(BaseModel)`
- `backend/src/hmap/agents/docgen/model.py::Route`: `class Route(BaseModel)`
- `backend/src/hmap/agents/docgen/model.py::Facts`: “What the repository contains.”
- `backend/src/hmap/agents/docgen/model.py::Facts.symbol_names`: `def symbol_names(self) -> set[str]`
- `backend/src/hmap/agents/docgen/model.py::Facts.public_symbols`: `def public_symbols(self) -> list[tuple[str, Symbol]]`
- `backend/src/hmap/agents/docgen/model.py::Facts.code_modules`: `def code_modules(self) -> list[ModuleFacts]`
- `backend/src/hmap/agents/docgen/model.py::Claim`: `class Claim(BaseModel)`
- `backend/src/hmap/agents/docgen/model.py::Claim.grounded`: `def grounded(self) -> bool`
- `backend/src/hmap/agents/docgen/model.py::ExampleResult`: `class ExampleResult(BaseModel)`
- `backend/src/hmap/agents/docgen/model.py::Accuracy`: “The full claim table (artifact ``doc-accuracy``); the bundle carries its short form (``AccuracyReport``).”
- `backend/src/hmap/agents/docgen/model.py::Accuracy.ungrounded_lines`: `def ungrounded_lines(self) -> list[str]`
- `backend/src/hmap/agents/docgen/model.py::DocgenTrace`: `class DocgenTrace(BaseModel)`

## `backend/src/hmap/agents/docgen/plugin.py`

“Member 9 plug-in: technical documentation (Sprint 9).”


## `backend/src/hmap/agents/docgen/readme.py`

“README generator (Sprint 9 item 9.4, plan D6; from the prototype's ``draft_readme.py``).”

- `backend/src/hmap/agents/docgen/readme.py::install_commands`: `def install_commands(facts: Facts) -> list[str]`
- `backend/src/hmap/agents/docgen/readme.py::run_commands`: “Make targets and console scripts first (how the project is meant to be run), then entry points.”
- `backend/src/hmap/agents/docgen/readme.py::test_commands`: `def test_commands(facts: Facts) -> list[str]`
- `backend/src/hmap/agents/docgen/readme.py::long_running`: `def long_running(facts: Facts, path: str) -> bool`
- `backend/src/hmap/agents/docgen/readme.py::sections`: `def sections(facts: Facts, arch: Architecture, summaries: Summaries | None) -> list[str]`
- `backend/src/hmap/agents/docgen/readme.py::what_paragraph`: `async def what_paragraph(llm: LLMClient | None, facts: Facts, summaries: Summaries | None, arch: Architecture) -> tuple[str, int, int]`
- `backend/src/hmap/agents/docgen/readme.py::render`: `def render(facts: Facts, arch: Architecture, summaries: Summaries | None, what: str) -> str`

## `backend/src/hmap/agents/docgen/refine_hook.py`

“Refine loop for the documents (Sprint 9 item 9.9, plan D9), on Member 4's ``Refiner``.”

- `backend/src/hmap/agents/docgen/refine_hook.py::DocInput`: `class DocInput`
- `backend/src/hmap/agents/docgen/refine_hook.py::current_claims`: `def current_claims(docs: Docs, inp: DocInput) -> list[Claim]`
- `backend/src/hmap/agents/docgen/refine_hook.py::grounding_check`: `def grounding_check(docs: Docs, inp: DocInput) -> list[Issue]`
- `backend/src/hmap/agents/docgen/refine_hook.py::CompletenessCritic`: `class CompletenessCritic`
- `backend/src/hmap/agents/docgen/refine_hook.py::CompletenessCritic.review`: `async def review(self, output: Docs, task_input: DocInput, ctx: RefineContext) -> Critique`
- `backend/src/hmap/agents/docgen/refine_hook.py::SentenceReviser`: `class SentenceReviser`
- `backend/src/hmap/agents/docgen/refine_hook.py::SentenceReviser.revise`: `async def revise(self, output: Docs, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *, task_input: Any=None, strategy: str='targeted') -> Revision`
- `backend/src/hmap/agents/docgen/refine_hook.py::LoopResult`: `class LoopResult`
- `backend/src/hmap/agents/docgen/refine_hook.py::refine`: `async def refine(docs: Docs, inp: DocInput, llm: Any, *, max_rounds: int, check_cancelled: Any=None) -> LoopResult`

## `backend/src/hmap/agents/docgen/report.py`

“Report sections mapped to the required deliverables (Sprint 9 item 9.8, plan D1, D10).”

- `backend/src/hmap/agents/docgen/report.py::ReportOut`: `class ReportOut`
- `backend/src/hmap/agents/docgen/report.py::doc_deliverables`: `def doc_deliverables(rs: RequirementSet | None) -> list[str]`
- `backend/src/hmap/agents/docgen/report.py::requirement_evidence`: “Code that shares words with the requirement: endpoints, modules, functions, tests (best 4).”
- `backend/src/hmap/agents/docgen/report.py::software`: `def software(facts: Facts, arch: Architecture, summaries: Summaries | None, rs: RequirementSet | None, test_report: dict[str, Any] | None, title: str) -> ReportOut`
- `backend/src/hmap/agents/docgen/report.py::allowed_claims`: `def allowed_claims(research: ResearchReport | None, verification: VerificationReport | None) -> _Allowed`
- `backend/src/hmap/agents/docgen/report.py::document`: `async def document(llm: LLMClient | None, rs: RequirementSet | None, research: ResearchReport | None, verification: VerificationReport | None, objective: str, step: str, title: str) -> ReportOut`
- `backend/src/hmap/agents/docgen/report.py::ground_citations`: “Document mode grounding: every sentence of a section paragraph must cite an allowed claim; the others are removed (and reported as ungrounded).”

## `backend/src/hmap/agents/docgen/router.py`

“Documentation API (Sprint 9 item 9.13, plan D18), mounted at ``/api/docgen``.”

- `backend/src/hmap/agents/docgen/router.py::summary`: `def summary(trace: dict[str, Any], acc: dict[str, Any] | None) -> dict[str, Any]`
- `backend/src/hmap/agents/docgen/router.py::list_bundles`: `async def list_bundles(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/docgen/router.py::get_bundle`: `async def get_bundle(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/docgen/router.py::get_file`: `async def get_file(project_id: str, task_id: str, name: str, info: CurrentSession, m: ManagerDep) -> str`
- `backend/src/hmap/agents/docgen/router.py::regenerate`: `async def regenerate(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/docgen/router.py::architecture_svg`: `async def architecture_svg(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> Response`
- `backend/src/hmap/agents/docgen/router.py::site_html`: “Every document on one static page (docs-as-site); served as a download with a strict CSP.”
- `backend/src/hmap/agents/docgen/router.py::docstrings`: “The suggested docstrings as a patch (``git apply``); the agent never applies it.”
- `backend/src/hmap/agents/docgen/router.py::CheckIn`: `class CheckIn(BaseModel)`
- `backend/src/hmap/agents/docgen/router.py::check`: `async def check(project_id: str, body: CheckIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`

## `backend/src/hmap/agents/docgen/summarize.py`

“Hierarchical code summaries with symbol citations (Sprint 9 item 9.3, plan D5).”

- `backend/src/hmap/agents/docgen/summarize.py::SymbolSummary`: `class SymbolSummary(BaseModel)`
- `backend/src/hmap/agents/docgen/summarize.py::Summaries`: `class Summaries(BaseModel)`
- `backend/src/hmap/agents/docgen/summarize.py::Summaries.coverage_pct`: `def coverage_pct(self) -> float`
- `backend/src/hmap/agents/docgen/summarize.py::summarize`: `async def summarize(facts: Facts, files: dict[str, str], llm: LLMClient | None, *, limit: int=60, previous: Summaries | None=None, arch: Architecture | None=None) -> Summaries`
- `backend/src/hmap/agents/docgen/summarize.py::facts_overview`: “A one-paragraph description built only from facts (the fallback, and the model's input).”
- `backend/src/hmap/agents/docgen/summarize.py::quote`: “The code's own docstring, shown as a quotation: it is the author's text, not a claim of the generator (the grounding checker skips quoted text).”
- `backend/src/hmap/agents/docgen/summarize.py::render`: `def render(s: Summaries, facts: Facts) -> str`

## `backend/src/hmap/agents/ops/__init__.py`

“Operations plug-in (Member 4, Sprint 4): explain failures, list dead letters, replay them explicitly.”


## `backend/src/hmap/agents/ops/explain.py`

“"Why did this task fail?" (Sprint 4 item 4.16; Member 1's research §11): one answer built from everything the platform already records, in the order a person would check it:”

- `backend/src/hmap/agents/ops/explain.py::verdict`: `def verdict(task: dict[str, Any], executions: list[dict[str, Any]], deps: list[dict[str, Any]], dependants: list[dict[str, Any]]) -> dict[str, Any]`
- `backend/src/hmap/agents/ops/explain.py::explain`: `async def explain(system: Any, task_id: str, *, jaeger_url: str, tracing: bool, feed: Any=None) -> dict[str, Any]`

## `backend/src/hmap/agents/ops/history.py`

“Where a task's history lives (item 4.16): its domain events and the assignment messages the Manager sent.”

- `backend/src/hmap/agents/ops/history.py::task_events`: `async def task_events(system: Any, task_id: str, feed: Any=None) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/ops/history.py::processed_by`: “Consumers whose inbox recorded ``message_id``: it was processed once there, and any redelivery (a duplicate) was skipped (research §24).”
- `backend/src/hmap/agents/ops/history.py::task_messages`: “The ``task.assign`` commands for this task: one per execution; ``published`` false = still in the outbox (e.g.”

## `backend/src/hmap/agents/ops/plugin.py`

“Member 4 plug-in: operations (Sprint 4 §5b, plan D12).”


## `backend/src/hmap/agents/ops/router.py`

“Operations API (Sprint 4 items 4.16 and 4.18), mounted at ``/api/ops``.”

- `backend/src/hmap/agents/ops/router.py::ReplayIn`: `class ReplayIn(BaseModel)`
- `backend/src/hmap/agents/ops/router.py::overview`: `async def overview(info: CurrentSession, s: SystemDep, request: Request) -> dict[str, Any]`
- `backend/src/hmap/agents/ops/router.py::failures`: `async def failures(info: CurrentSession, s: SystemDep, limit: Annotated[int, Query(ge=1, le=200)]=50) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/ops/router.py::explain_task`: `async def explain_task(task_id: str, info: CurrentSession, s: SystemDep, request: Request) -> dict[str, Any]`
- `backend/src/hmap/agents/ops/router.py::dlq`: `async def dlq(info: CurrentSession, s: SystemDep) -> dict[str, Any]`
- `backend/src/hmap/agents/ops/router.py::replay`: “Replay a dead-lettered task as a NEW execution (never automatic, never blind: research §26).”

## `backend/src/hmap/agents/pipeline/__init__.py`

“Default project pipeline (owner: Member 1).”


## `backend/src/hmap/agents/pipeline/plugin.py`

“Default project pipeline as Manager hooks (owner: Member 1).”

- `backend/src/hmap/agents/pipeline/plugin.py::on_document_uploaded`: `async def on_document_uploaded(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/pipeline/plugin.py::on_requirements_ready`: `async def on_requirements_ready(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/pipeline/plugin.py::on_plan_ready`: `async def on_plan_ready(event: DomainEvent, manager: ManagerHandle) -> None`

## `backend/src/hmap/agents/planning/__init__.py`

“Member 3 (Sprint 3): planning and task decomposition — RequirementSet -> validated TaskGraph, the layer-parallel DAG executor, replanning, and the plan API.”


## `backend/src/hmap/agents/planning/agent.py`

“``PlanningAgent`` (spec item 3.8): the real ``plan.generate`` and ``plan.replan`` capabilities.”

- `backend/src/hmap/agents/planning/agent.py::report_id`: `def report_id(graph_artifact_id: str) -> str`
- `backend/src/hmap/agents/planning/agent.py::LruCache`: `class LruCache`
- `backend/src/hmap/agents/planning/agent.py::LruCache.__init__`: `def __init__(self, max_entries: int=256) -> None`
- `backend/src/hmap/agents/planning/agent.py::LruCache.get`: `async def get(self, key: str) -> str | None`
- `backend/src/hmap/agents/planning/agent.py::LruCache.put`: `async def put(self, key: str, value: str) -> None`
- `backend/src/hmap/agents/planning/agent.py::PlanningAgent`: `class PlanningAgent(BaseAgent)`
- `backend/src/hmap/agents/planning/agent.py::PlanningAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/agents/planning/coverage.py`

“Coverage and traceability (spec item 3.6): requirement -> the build / test / document steps that serve it, and every requirement either covered or flagged with a reason.”

- `backend/src/hmap/agents/planning/coverage.py::CoverageReport`: `class CoverageReport`
- `backend/src/hmap/agents/planning/coverage.py::CoverageReport.ratio`: “Share of requirements that are covered or explicitly flagged (the spec's target: 1.0).”
- `backend/src/hmap/agents/planning/coverage.py::coverage`: `def coverage(tasks: list[PlanTask], rs: RequirementSet, flagged: dict[str, str] | None=None) -> CoverageReport`

## `backend/src/hmap/agents/planning/decompose.py`

“Decomposition (spec item 3.2): each part's requirements -> build and test steps.”

- `backend/src/hmap/agents/planning/decompose.py::ResultCache`: `class ResultCache(Protocol)`
- `backend/src/hmap/agents/planning/decompose.py::ResultCache.get`: `async def get(self, key: str) -> str | None`
- `backend/src/hmap/agents/planning/decompose.py::ResultCache.put`: `async def put(self, key: str, value: str) -> None`
- `backend/src/hmap/agents/planning/decompose.py::DraftStep`: `class DraftStep(BaseModel)`
- `backend/src/hmap/agents/planning/decompose.py::NotPlannable`: `class NotPlannable(BaseModel)`
- `backend/src/hmap/agents/planning/decompose.py::DraftPlan`: `class DraftPlan(BaseModel)`
- `backend/src/hmap/agents/planning/decompose.py::requirement_line`: `def requirement_line(r: Requirement, section: str | None) -> str`
- `backend/src/hmap/agents/planning/decompose.py::build_messages`: `def build_messages(part: Part, batch: list[Requirement], rs: RequirementSet, kind: str) -> list[Message]`
- `backend/src/hmap/agents/planning/decompose.py::decompose_batch`: “The model's draft for one batch and who answered (``provider:model``, or ``memory`` from the cache).”
- `backend/src/hmap/agents/planning/decompose.py::batches`: `def batches(reqs: list[Requirement]) -> list[list[Requirement]]`
- `backend/src/hmap/agents/planning/decompose.py::rule_draft`: “Without a model: requirements grouped by their section (else in runs of ``RULE_GROUP``), one build step per group of functional requirements and one test step per build step; quality requirements go to the tests.”
- `backend/src/hmap/agents/planning/decompose.py::IdAllocator`: `class IdAllocator`
- `backend/src/hmap/agents/planning/decompose.py::IdAllocator.new`: `def new(self, taken: set[str]) -> str`
- `backend/src/hmap/agents/planning/decompose.py::add_part`: “Turn a draft into plan tasks in ``plan`` (ids T1.., groups, model edges).”
- `backend/src/hmap/agents/planning/decompose.py::ensure_part_coverage`: “Every plannable requirement of the part ends up in a build or test step: a missed one joins the build step with the most words in common, or gets its own rule-made step; a part without tests gets one.”
- `backend/src/hmap/agents/planning/decompose.py::add_deliverables`: “A document step per document-like deliverable (README, report, slides); code deliverables are produced by the build steps; anything else is checked in the final review.”

## `backend/src/hmap/agents/planning/dependencies.py`

“Dependency inference (spec item 3.3).”

- `backend/src/hmap/agents/planning/dependencies.py::infer`: `def infer(plan: WorkingPlan, parts: list[Part], part_tasks: dict[str, list[str]]) -> None`

## `backend/src/hmap/agents/planning/executor.py`

“Layer-parallel DAG executor (spec item 3.9), plugged into the Manager's ``executor`` strategy slot.”

- `backend/src/hmap/agents/planning/executor.py::LayerParallelExecutor`: `class LayerParallelExecutor(NaiveTopologicalExecutor)`
- `backend/src/hmap/agents/planning/executor.py::LayerParallelExecutor.__init__`: `def __init__(self, max_parallel: int | None=None) -> None`
- `backend/src/hmap/agents/planning/executor.py::LayerParallelExecutor.max_parallel`: `def max_parallel(self) -> int`
- `backend/src/hmap/agents/planning/executor.py::LayerParallelExecutor.order`: `def order(self, graph: TaskGraph) -> list[str]`
- `backend/src/hmap/agents/planning/executor.py::LayerParallelExecutor.ready`: `def ready(self, tasks: Sequence[TaskRecord]) -> list[str]`

## `backend/src/hmap/agents/planning/model.py`

“Planning data that is not part of the shared ``TaskGraph`` contract: the ``plan-report`` artifact (how the plan was made, what was repaired, what is flagged, the schedule) and the in-progress plan the pipeline stages pass along.”

- `backend/src/hmap/agents/planning/model.py::Issue`: `class Issue(BaseModel)`
- `backend/src/hmap/agents/planning/model.py::Schedule`: `class Schedule(BaseModel)`
- `backend/src/hmap/agents/planning/model.py::PlanReport`: “Artifact ``plan-report`` (one version per ``task-graph`` version).”
- `backend/src/hmap/agents/planning/model.py::WorkingPlan`: “A plan being built: tasks plus where each dependency came from (cycle repair drops model edges first).”
- `backend/src/hmap/agents/planning/model.py::WorkingPlan.task`: `def task(self, task_id: str) -> PlanTask | None`
- `backend/src/hmap/agents/planning/model.py::WorkingPlan.ids`: `def ids(self) -> set[str]`
- `backend/src/hmap/agents/planning/model.py::WorkingPlan.add_edge`: “``after`` depends on ``before``.”
- `backend/src/hmap/agents/planning/model.py::WorkingPlan.remove_edge`: `def remove_edge(self, before: str, after: str) -> None`
- `backend/src/hmap/agents/planning/model.py::WorkingPlan.replace`: `def replace(self, task: PlanTask) -> None`

## `backend/src/hmap/agents/planning/pipeline.py`

“The planning pipeline (spec §4):”

- `backend/src/hmap/agents/planning/pipeline.py::PlanResult`: `class PlanResult`
- `backend/src/hmap/agents/planning/pipeline.py::make_plan`: `async def make_plan(rs: RequirementSet, llm: LLMClient | None, *, document_model: dict[str, Any] | None=None, capabilities: Iterable[str] | None=None, cache: ResultCache | None=None, progress: ProgressFn | None=None, check_cancelled: Callable[[], None] | None=None, use_llm: bool=True, max_tasks: int=MAX_TASKS, version: int=1, requirement_set_ref: dict[str, str | int] | None=None) -> PlanResult`
- `backend/src/hmap/agents/planning/pipeline.py::finalize`: “Validate (+ repair), reduce, schedule, cover and describe ``plan``; build the ``TaskGraph`` (version ``version``) and fill ``report``.”
- `backend/src/hmap/agents/planning/pipeline.py::working_plan_from`: “A stored plan back into a ``WorkingPlan`` (edits and replans): groups from the roadmap, edges as ``human``.”

## `backend/src/hmap/agents/planning/plugin.py`

“Member 3 plug-in: planning and task decomposition (Sprint 3).”

- `backend/src/hmap/agents/planning/plugin.py::apply_replan`: `async def apply_replan(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/planning/plugin.py::announce_plan_approved`: `async def announce_plan_approved(event: DomainEvent, manager: ManagerHandle) -> None`

## `backend/src/hmap/agents/planning/replan.py`

“Replanning and human edits (spec items 3.10, 3.12).”

- `backend/src/hmap/agents/planning/replan.py::TaskChange`: `class TaskChange(BaseModel)`
- `backend/src/hmap/agents/planning/replan.py::ReplanDraft`: `class ReplanDraft(BaseModel)`
- `backend/src/hmap/agents/planning/replan.py::replan`: `async def replan(current: TaskGraph, rs: RequirementSet, *, states: dict[str, str], feedback: str | None=None, failed: Iterable[str]=(), llm: LLMClient | None=None, kind: str='software', cache: ResultCache | None=None, previous: PlanReport | None=None, allowed: Iterable[str]=PLAN_CAPABILITIES) -> PlanResult`
- `backend/src/hmap/agents/planning/replan.py::apply_edit`: “A person's plan -> the next version.”

## `backend/src/hmap/agents/planning/roadmap.py`

“Roadmap (spec item 3.7): the plan's hierarchy (phase -> part -> feature group, ``Phase.parent_id``), milestones, effort and the critical path, as JSON for the UI and Markdown for people.”

- `backend/src/hmap/agents/planning/roadmap.py::limit_width`: “A group with more than ``MAX_CHILDREN`` direct steps is split into sub-groups of at most that many (in execution order), as long as the hierarchy stays ``MAX_DEPTH`` levels deep; deeper groups keep their steps.”
- `backend/src/hmap/agents/planning/roadmap.py::build`: `def build(plan: WorkingPlan, schedule: Schedule, rs: RequirementSet, *, flagged: dict[str, str], questions: list[str]) -> Roadmap`
- `backend/src/hmap/agents/planning/roadmap.py::markdown`: `def markdown(tasks: list[PlanTask], phases: list[Phase], schedule: Schedule, rs: RequirementSet, *, flagged: dict[str, str], questions: list[str]) -> str`

## `backend/src/hmap/agents/planning/router.py`

“Plan API (spec item 3.11), mounted at ``/api/planning``.”

- `backend/src/hmap/agents/planning/router.py::PlanEdit`: `class PlanEdit(BaseModel)`
- `backend/src/hmap/agents/planning/router.py::Decision`: `class Decision(BaseModel)`
- `backend/src/hmap/agents/planning/router.py::ReplanIn`: `class ReplanIn(BaseModel)`
- `backend/src/hmap/agents/planning/router.py::capabilities`: `async def capabilities(info: CurrentSession) -> dict[str, Any]`
- `backend/src/hmap/agents/planning/router.py::get_plan`: `async def get_plan(project_id: str, info: CurrentSession, m: ManagerDep, version: Annotated[int | None, Query(ge=1)]=None) -> dict[str, Any]`
- `backend/src/hmap/agents/planning/router.py::roadmap_markdown`: `async def roadmap_markdown(project_id: str, info: CurrentSession, m: ManagerDep) -> Response`
- `backend/src/hmap/agents/planning/router.py::edit_plan`: `async def edit_plan(project_id: str, body: PlanEdit, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/planning/router.py::decide`: `async def decide(project_id: str, body: Decision, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/planning/router.py::start_replan`: `async def start_replan(project_id: str, body: ReplanIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`

## `backend/src/hmap/agents/planning/schedule.py`

“Scheduling (spec item 3.5): parallel layers, the critical path, slack and priorities.”

- `backend/src/hmap/agents/planning/schedule.py::compute`: `def compute(tasks: list[PlanTask]) -> Schedule`
- `backend/src/hmap/agents/planning/schedule.py::apply_priorities`: “Always derived from the requirements and the schedule (never accumulated over versions).”
- `backend/src/hmap/agents/planning/schedule.py::execution_order`: “Layer by layer; inside a layer the most urgent first, then by id (what the executor creates first).”

## `backend/src/hmap/agents/planning/skeleton.py`

“Plan skeleton (spec item 3.1): the project kind, its parts (one per upload folder), the template spine, and what people must look at before approving (open questions, low-confidence requirements, things only a person can do).”

- `backend/src/hmap/agents/planning/skeleton.py::Part`: “One part of the work: an upload folder ("Part A"), or the whole request when there are no folders.”
- `backend/src/hmap/agents/planning/skeleton.py::Part.label`: `def label(self) -> str`
- `backend/src/hmap/agents/planning/skeleton.py::phase_group_id`: `def phase_group_id(phase: str) -> str`
- `backend/src/hmap/agents/planning/skeleton.py::section_map`: “(doc_id, block_id) -> the innermost section heading, from Member 2's ``document-model`` (read as plain JSON so this plug-in does not depend on Member 2's code).”
- `backend/src/hmap/agents/planning/skeleton.py::build_parts`: `def build_parts(rs: RequirementSet, sections: dict[tuple[str, str], str] | None=None) -> list[Part]`
- `backend/src/hmap/agents/planning/skeleton.py::human_only`: “Requirements no agent can carry out (a demo in person, uploading to the course portal): flagged with a reason instead of being turned into tasks.”
- `backend/src/hmap/agents/planning/skeleton.py::review_questions`: “Questions to show before approval: Member 2's open questions plus every low-confidence requirement.”
- `backend/src/hmap/agents/planning/skeleton.py::rule_research_questions`: “Research seeds without a model: one per technology constraint and one per part (Member 5 refines them).”
- `backend/src/hmap/agents/planning/skeleton.py::build_skeleton`: “The spine (research, verify, design, review) with its groups; parts are added by the decomposer.”

## `backend/src/hmap/agents/planning/templates.py`

“Phase templates (spec item 3.1).”

- `backend/src/hmap/agents/planning/templates.py::SpineStep`: `class SpineStep`
- `backend/src/hmap/agents/planning/templates.py::detect_kind`: “``software`` unless the writing words clearly win (ties go to software: most course work is code).”
- `backend/src/hmap/agents/planning/templates.py::clamp_effort`: `def clamp_effort(hours: float | None, default: float) -> float`

## `backend/src/hmap/agents/planning/validate.py`

“Plan validation and auto-repair (spec item 3.4).”

- `backend/src/hmap/agents/planning/validate.py::graph_of`: `def graph_of(tasks: Iterable[PlanTask]) -> 'nx.DiGraph[str]'`
- `backend/src/hmap/agents/planning/validate.py::coverage_of`: `def coverage_of(tasks: Iterable[PlanTask]) -> set[str]`
- `backend/src/hmap/agents/planning/validate.py::check`: `def check(tasks: list[PlanTask], rs: RequirementSet | None=None, *, flagged: Iterable[str]=(), allowed: Iterable[str]=PLAN_CAPABILITIES, max_tasks: int=MAX_TASKS) -> list[Issue]`
- `backend/src/hmap/agents/planning/validate.py::validate_plan`: “Public critic (Member 4): every problem of a finished ``TaskGraph`` (errors and warnings).”
- `backend/src/hmap/agents/planning/validate.py::errors`: `def errors(issues: Iterable[Issue]) -> list[Issue]`
- `backend/src/hmap/agents/planning/validate.py::repair`: “Fix ``plan`` in place (and return it).”
- `backend/src/hmap/agents/planning/validate.py::reduce`: “Transitive reduction: drop A->C when A->B->C exists, so the drawn plan stays readable.”

## `backend/src/hmap/agents/refine/__init__.py`

“Self-reflection and refinement library (Member 4, Sprint 4).”


## `backend/src/hmap/agents/refine/adapters/__init__.py`

“Refinement adapters for existing capabilities (Sprint 4 item 4.10, plan D1): registered in the refine plug-in's ``Plugin.refiners`` so Member 2's and Member 3's agents are refined behind ``refine=true`` without editing them.”


## `backend/src/hmap/agents/refine/adapters/extraction.py`

“Refinement of Member 2's ``document.extract`` result (Sprint 4 item 4.10).”

- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionInput`: “What the output is checked against: the parsed documents and the rule pass over them.”
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionInput.docs`: `def docs(self) -> list[SourceDocument]`
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionInput.doc`: `def doc(self, doc_id: str | None) -> SourceDocument | None`
- `backend/src/hmap/agents/refine/adapters/extraction.py::build_input`: `def build_input(model: DocumentModel) -> ExtractionInput`
- `backend/src/hmap/agents/refine/adapters/extraction.py::find`: “Best location of ``text`` in the item's own document (or any document).”
- `backend/src/hmap/agents/refine/adapters/extraction.py::verified`: “``locate`` the quote; a list item under a lead-in is quoted as "<lead-in>: <item>." by Member 2's rules, so when the whole is not one sentence of the document, its item part is located instead.”
- `backend/src/hmap/agents/refine/adapters/extraction.py::was_dropped`: `def was_dropped(inp: ExtractionInput, text: str) -> bool`
- `backend/src/hmap/agents/refine/adapters/extraction.py::items`: `def items(rs: RequirementSet) -> list[tuple[str, Item]]`
- `backend/src/hmap/agents/refine/adapters/extraction.py::item_text`: `def item_text(item: Item) -> str`
- `backend/src/hmap/agents/refine/adapters/extraction.py::check_quotes`: `def check_quotes(rs: RequirementSet, inp: ExtractionInput) -> list[Issue]`
- `backend/src/hmap/agents/refine/adapters/extraction.py::check_contract`: `def check_contract(rs: RequirementSet, inp: ExtractionInput) -> list[Issue]`
- `backend/src/hmap/agents/refine/adapters/extraction.py::check_priority`: “A modal verb in the requirement's own quote decides its priority (must / should / could).”
- `backend/src/hmap/agents/refine/adapters/extraction.py::check_coverage`: “Sentences the keyword rules flag that no item covers: a hint (minor), the judge decides.”
- `backend/src/hmap/agents/refine/adapters/extraction.py::windows`: “Documents (or block runs of a long one) packed into windows of at most ``limit`` characters.”
- `backend/src/hmap/agents/refine/adapters/extraction.py::render_window`: `def render_window(rs: RequirementSet, window: list[tuple[SourceDocument, list[Block]]], first: bool) -> str`
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionJudge`: “The LLM rubric over each document window (the gold documents fit one window; long uploads take several).”
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionJudge.__init__`: `def __init__(self, role: str='judge', weight: float=3.0) -> None`
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionJudge.review`: `async def review(self, output: RequirementSet, task_input: ExtractionInput, ctx: RefineContext) -> Critique`
- `backend/src/hmap/agents/refine/adapters/extraction.py::extraction_critics`: `def extraction_critics(inp: ExtractionInput, *, judge: bool=True) -> list[Any]`
- `backend/src/hmap/agents/refine/adapters/extraction.py::Change`: `class Change(BaseModel)`
- `backend/src/hmap/agents/refine/adapters/extraction.py::ChangeAnswer`: `class ChangeAnswer(BaseModel)`
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionReviser`: `class ExtractionReviser`
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionReviser.__init__`: `def __init__(self, role: str | None=None, max_tokens: int=2500) -> None`
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionReviser.deterministic`: “Programmatic issues that carry an exact fix (``set priority=should``) need no model.”
- `backend/src/hmap/agents/refine/adapters/extraction.py::ExtractionReviser.revise`: `async def revise(self, output: RequirementSet, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *, task_input: ExtractionInput | None=None, strategy: Strategy='targeted') -> Revision`
- `backend/src/hmap/agents/refine/adapters/extraction.py::extraction_setup`: `def extraction_setup(inp: ExtractionInput, *, judge: bool=True, stop: StopPolicy | None=None, reflexion: bool=True) -> RefineSetup`
- `backend/src/hmap/agents/refine/adapters/extraction.py::build_setup`: “``Plugin.refiners["document.extract"]``: the document model travels in the agent's own result.”

## `backend/src/hmap/agents/refine/adapters/plan.py`

“Refinement of Member 3's ``plan.generate`` result (Sprint 4 item 4.10).”

- `backend/src/hmap/agents/refine/adapters/plan.py::PlanInput`: `class PlanInput`
- `backend/src/hmap/agents/refine/adapters/plan.py::PlanInput.kind`: `def kind(self) -> str`
- `backend/src/hmap/agents/refine/adapters/plan.py::PlanInput.report_for`: `def report_for(self, graph: TaskGraph) -> PlanReport`
- `backend/src/hmap/agents/refine/adapters/plan.py::check_validity`: `def check_validity(graph: TaskGraph, inp: PlanInput) -> list[Issue]`
- `backend/src/hmap/agents/refine/adapters/plan.py::check_coverage`: `def check_coverage(graph: TaskGraph, inp: PlanInput) -> list[Issue]`
- `backend/src/hmap/agents/refine/adapters/plan.py::check_testability`: `def check_testability(graph: TaskGraph, inp: PlanInput) -> list[Issue]`
- `backend/src/hmap/agents/refine/adapters/plan.py::render_plan`: `def render_plan(graph: TaskGraph, inp: PlanInput) -> str`
- `backend/src/hmap/agents/refine/adapters/plan.py::plan_critics`: `def plan_critics(*, judge: bool=True) -> list[Any]`
- `backend/src/hmap/agents/refine/adapters/plan.py::PlanChange`: `class PlanChange(BaseModel)`
- `backend/src/hmap/agents/refine/adapters/plan.py::PlanChangeAnswer`: `class PlanChangeAnswer(BaseModel)`
- `backend/src/hmap/agents/refine/adapters/plan.py::PlanPatchReviser`: “Targeted plan reviser: dependency and acceptance-criterion patches, rebuilt by Member 3's ``finalize``.”
- `backend/src/hmap/agents/refine/adapters/plan.py::PlanPatchReviser.__init__`: `def __init__(self, role: str | None=None, max_tokens: int=2000) -> None`
- `backend/src/hmap/agents/refine/adapters/plan.py::PlanPatchReviser.revise`: `async def revise(self, output: TaskGraph, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *, task_input: PlanInput | None=None, strategy: Strategy='targeted') -> Revision`
- `backend/src/hmap/agents/refine/adapters/plan.py::apply_changes`: “Apply the guarded changes to a working copy and rebuild it with Member 3's ``finalize``.”
- `backend/src/hmap/agents/refine/adapters/plan.py::ReplanReviser`: “``full`` strategy: Member 3's ``replan`` with the critique as feedback (may add / change / remove steps).”
- `backend/src/hmap/agents/refine/adapters/plan.py::ReplanReviser.revise`: `async def revise(self, output: TaskGraph, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *, task_input: PlanInput | None=None, strategy: Strategy='full') -> Revision`
- `backend/src/hmap/agents/refine/adapters/plan.py::plan_reviser`: `def plan_reviser() -> Any`
- `backend/src/hmap/agents/refine/adapters/plan.py::plan_setup`: `def plan_setup(inp: PlanInput, *, judge: bool=True, stop: StopPolicy | None=None, reflexion: bool=True) -> RefineSetup`
- `backend/src/hmap/agents/refine/adapters/plan.py::build_setup`: “``Plugin.refiners["plan.generate"]``: requirements from the task's inputs, the report from the result.”

## `backend/src/hmap/agents/refine/agent.py`

“``RefineAgent`` (Sprint 4 item 4.12): the standalone ``refine.run`` capability, for the Manager (or a person, from the Refinement tab) to check and improve an existing artifact.”

- `backend/src/hmap/agents/refine/agent.py::generic_setup`: `def generic_setup(artifact_type: str, contract: str | None, rubric: Rubric, objective: str, stop: dict[str, Any] | None, reflexion: bool) -> RefineSetup`
- `backend/src/hmap/agents/refine/agent.py::RefineAgent`: `class RefineAgent(BaseAgent)`
- `backend/src/hmap/agents/refine/agent.py::RefineAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/agents/refine/core.py`

“Core abstractions of the refinement library (Sprint 4 item 4.1).”

- `backend/src/hmap/agents/refine/core.py::max_severity`: `def max_severity(issues: Sequence[Issue]) -> str | None`
- `backend/src/hmap/agents/refine/core.py::to_jsonable`: “Outputs are pydantic models, dicts, lists or strings; the trace stores their JSON form.”
- `backend/src/hmap/agents/refine/core.py::canonical`: `def canonical(obj: Any) -> str`
- `backend/src/hmap/agents/refine/core.py::digest`: “Short stable hash of outputs / rubrics / prompt versions (caching, plan D10).”
- `backend/src/hmap/agents/refine/core.py::Usage`: “Tokens and wall-clock time spent by one refinement loop (budget stop policy, trace).”
- `backend/src/hmap/agents/refine/core.py::Usage.tokens`: `def tokens(self) -> int`
- `backend/src/hmap/agents/refine/core.py::Usage.seconds`: `def seconds(self) -> float`
- `backend/src/hmap/agents/refine/core.py::Usage.add`: `def add(self, resp: LLMResponse) -> None`
- `backend/src/hmap/agents/refine/core.py::CountingLLM`: “An ``LLMClient`` that adds every call's tokens to a :class:`Usage` — so calls made inside other members' functions (Member 3's ``replan``, Member 2's extraction) count against the loop's budget too.”
- `backend/src/hmap/agents/refine/core.py::CountingLLM.__init__`: `def __init__(self, inner: LLMClient, usage: Usage) -> None`
- `backend/src/hmap/agents/refine/core.py::CountingLLM.generate`: `async def generate(self, role: Role, messages: list[Message] | list[dict[str, str]], *, schema: type[T] | None=None, max_tokens: int=1024, temperature: float=0.2, think: bool=False, seed: int | None=None) -> LLMResponse`
- `backend/src/hmap/agents/refine/core.py::CountingLLM.embed`: `async def embed(self, texts: list[str]) -> list[list[float]]`
- `backend/src/hmap/agents/refine/core.py::CountingLLM.classify`: `async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]`
- `backend/src/hmap/agents/refine/core.py::CountingLLM.read_images`: `async def read_images(self, prompt: str, images: list[bytes], *, max_tokens: int=4096) -> LLMResponse`
- `backend/src/hmap/agents/refine/core.py::RefineContext`: “What critics and revisers may use.”
- `backend/src/hmap/agents/refine/core.py::RefineContext.cancelled`: “Raise :class:`~hmap.core.errors.Cancelled` if the surrounding task was cancelled.”
- `backend/src/hmap/agents/refine/core.py::RefineContext.has_llm`: `def has_llm(self) -> bool`
- `backend/src/hmap/agents/refine/core.py::RefineContext.generate`: “A schema-constrained model call, with its tokens counted against the loop's budget.”
- `backend/src/hmap/agents/refine/core.py::RefineContext.classify`: `async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]`
- `backend/src/hmap/agents/refine/core.py::Critic`: “Reviews one output.”
- `backend/src/hmap/agents/refine/core.py::Critic.review`: `async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique`
- `backend/src/hmap/agents/refine/core.py::Revision`: “A reviser's answer: the new output and what it changed (shown in the UI next to the diff).”
- `backend/src/hmap/agents/refine/core.py::Reviser`: “Turns ``output`` + its critique into a new output.”
- `backend/src/hmap/agents/refine/core.py::Reviser.revise`: `async def revise(self, output: Any, critique: Critique, history: Sequence['Attempt'], ctx: RefineContext, *, task_input: Any=None, strategy: Strategy='targeted') -> Revision`
- `backend/src/hmap/agents/refine/core.py::Attempt`: “One critiqued output (index 0 = the producer's output).”
- `backend/src/hmap/agents/refine/core.py::Attempt.score`: `def score(self) -> float`
- `backend/src/hmap/agents/refine/core.py::Attempt.issues_by_category`: `def issues_by_category(self) -> dict[str, int]`
- `backend/src/hmap/agents/refine/core.py::RefinementResult`: `class RefinementResult`
- `backend/src/hmap/agents/refine/core.py::RefinementResult.base_score`: `def base_score(self) -> float | None`
- `backend/src/hmap/agents/refine/core.py::RefinementResult.best_score`: `def best_score(self) -> float | None`
- `backend/src/hmap/agents/refine/core.py::RefinementResult.improved`: `def improved(self) -> bool`
- `backend/src/hmap/agents/refine/core.py::RefinementResult.iterations`: “Revisions made (attempts after the first).”

## `backend/src/hmap/agents/refine/critics/__init__.py`

“Critics (Sprint 4 item 4.3): programmatic checks first, an LLM rubric for what code cannot check, and a composite in which verified findings override the model's opinion.”


## `backend/src/hmap/agents/refine/critics/composite.py`

“``CompositeCritic``: several critics, one critique (spec §4, plan D8).”

- `backend/src/hmap/agents/refine/critics/composite.py::CompositeCritic`: `class CompositeCritic`
- `backend/src/hmap/agents/refine/critics/composite.py::CompositeCritic.__init__`: `def __init__(self, critics: Sequence[Critic], *, weights: Mapping[str, float] | None=None, caps: Mapping[str, float]=CAPS, llm_caps: Mapping[str, float]=LLM_CAPS) -> None`
- `backend/src/hmap/agents/refine/critics/composite.py::CompositeCritic.weight`: `def weight(self, name: str | None) -> float`
- `backend/src/hmap/agents/refine/critics/composite.py::CompositeCritic.names`: `def names(self) -> list[str]`
- `backend/src/hmap/agents/refine/critics/composite.py::CompositeCritic.review_all`: “The merged critique and each critic's own (for the trace and the judge-agreement metric).”
- `backend/src/hmap/agents/refine/critics/composite.py::CompositeCritic.review`: `async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique`

## `backend/src/hmap/agents/refine/critics/programmatic.py`

“``ProgrammaticCritic``: wraps a check written in code — a schema validator, Member 3's DAG validator, a quote matcher, a test runner.”

- `backend/src/hmap/agents/refine/critics/programmatic.py::score_from_issues`: `def score_from_issues(issues: Iterable[Issue], penalty: Mapping[str, float]=PENALTY) -> float`
- `backend/src/hmap/agents/refine/critics/programmatic.py::ProgrammaticCritic`: `class ProgrammaticCritic`
- `backend/src/hmap/agents/refine/critics/programmatic.py::ProgrammaticCritic.__init__`: “``covers``: issue categories this check verifies completely.”
- `backend/src/hmap/agents/refine/critics/programmatic.py::ProgrammaticCritic.review`: `async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique`

## `backend/src/hmap/agents/refine/critics/rubric.py`

“``LLMRubricCritic``: a model reviews the output criterion by criterion (spec §4, plan D7).”

- `backend/src/hmap/agents/refine/critics/rubric.py::Criterion`: `class Criterion`
- `backend/src/hmap/agents/refine/critics/rubric.py::Rubric`: `class Rubric`
- `backend/src/hmap/agents/refine/critics/rubric.py::Rubric.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/critics/rubric.py::CriterionScore`: `class CriterionScore(BaseModel)`
- `backend/src/hmap/agents/refine/critics/rubric.py::RubricIssue`: `class RubricIssue(BaseModel)`
- `backend/src/hmap/agents/refine/critics/rubric.py::RubricAnswer`: `class RubricAnswer(BaseModel)`
- `backend/src/hmap/agents/refine/critics/rubric.py::default_render`: `def default_render(output: Any, task_input: Any) -> str`
- `backend/src/hmap/agents/refine/critics/rubric.py::LLMRubricCritic`: `class LLMRubricCritic`
- `backend/src/hmap/agents/refine/critics/rubric.py::LLMRubricCritic.__init__`: “``render(output, task_input)`` is the material shown to the judge (the output plus whatever source it is checked against).”
- `backend/src/hmap/agents/refine/critics/rubric.py::LLMRubricCritic.messages`: `def messages(self, material: str) -> list[Message]`
- `backend/src/hmap/agents/refine/critics/rubric.py::LLMRubricCritic.answer`: `async def answer(self, output: Any, task_input: Any, ctx: RefineContext) -> RubricAnswer`
- `backend/src/hmap/agents/refine/critics/rubric.py::LLMRubricCritic.review`: `async def review(self, output: Any, task_input: Any, ctx: RefineContext) -> Critique`
- `backend/src/hmap/agents/refine/critics/rubric.py::RubricSet`: “Named rubrics (the ``refine.run`` agent picks one by name).”
- `backend/src/hmap/agents/refine/critics/rubric.py::RubricSet.get`: `def get(self, name: str) -> Rubric | None`

## `backend/src/hmap/agents/refine/diff.py`

“Differences between two versions of an output, for the "what did this revision change" view (item 4.13).”

- `backend/src/hmap/agents/refine/diff.py::diff`: `def diff(a: Any, b: Any, path: str='') -> list[dict[str, Any]]`

## `backend/src/hmap/agents/refine/integration.py`

“How agents opt in to refinement (Sprint 4 item 4.8, plan D1/D2).”

- `backend/src/hmap/agents/refine/integration.py::RefineSetup`: “What to refine in a result and how.”
- `backend/src/hmap/agents/refine/integration.py::write_next_version`: `async def write_next_version(output: Any, ref: ArtifactRef, ctx: AgentContext, dump: Callable[[Any], Any]) -> list[ArtifactRef]`
- `backend/src/hmap/agents/refine/integration.py::refine_result`: “Critique and revise ``result``'s ``setup.artifact_type`` artifact; returns the result to report.”
- `backend/src/hmap/agents/refine/integration.py::CapabilityAdapter`: “A ``RefineAdapter`` for ``Plugin.refiners`` (plan D1): builds the setup from the task and the agent's result (``None`` = nothing to refine) and runs :func:`refine_result`.”
- `backend/src/hmap/agents/refine/integration.py::CapabilityAdapter.__init__`: `def __init__(self, build: SetupBuilder, *, name: str='adapter') -> None`
- `backend/src/hmap/agents/refine/integration.py::refinable`: “Decorate ``BaseAgent.handle``: with ``task.refine`` the successful result is refined before it is returned.”
- `backend/src/hmap/agents/refine/integration.py::RefinementMixin`: “Mix into a ``BaseAgent``; override :meth:`refine_setup`; end ``handle`` with ``return await self.refine(task, result, ctx)``.”
- `backend/src/hmap/agents/refine/integration.py::RefinementMixin.refine_setup`: `def refine_setup(self, task: TaskAssign, ctx: AgentContext) -> RefineSetup | Awaitable[RefineSetup | None] | None`
- `backend/src/hmap/agents/refine/integration.py::RefinementMixin.refine`: `async def refine(self, task: TaskAssign, result: TaskResult, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/agents/refine/plugin.py`

“Member 4 plug-in: self-reflection and refinement (Sprint 4).”

- `backend/src/hmap/agents/refine/plugin.py::announce_refinement`: “``task.progress`` with a refinement record -> ``refine.iteration`` (running) / ``refine.stopped`` (final).”
- `backend/src/hmap/agents/refine/plugin.py::apply_refined_plan`: “A standalone check of the plan that produced a better version replaces the plan (approval needed again).”

## `backend/src/hmap/agents/refine/refiner.py`

“The refinement loop (Sprint 4 item 4.2): Self-Refine, optionally with Reflexion.”

- `backend/src/hmap/agents/refine/refiner.py::Refiner`: `class Refiner`
- `backend/src/hmap/agents/refine/refiner.py::Refiner.__init__`: `def __init__(self, producer: Producer | None=None, critics: Sequence[Critic] | CompositeCritic=(), reviser: Reviser | None=None, stop: StopPolicy | None=None, memory: ReflectionMemory | None=None, *, classifier: IssueClassifier | None=None, name: str='refine', producer_name: str | None=None, on_attempt: OnAttempt | None=None, hard_max_iters: int=HARD_MAX_ITERS) -> None`
- `backend/src/hmap/agents/refine/refiner.py::Refiner.spec`: `def spec(self) -> RefinementSpec`
- `backend/src/hmap/agents/refine/refiner.py::Refiner.run`: `async def run(self, task_input: Any, ctx: RefineContext | None=None, *, output: Any=None) -> RefinementResult`

## `backend/src/hmap/agents/refine/reflexion.py`

“Reflexion (Sprint 4 item 4.5, plan D6): a short verbal note after each failed attempt — what failed and what to change — injected into the next revision, plus a **strategy change** when the same kind of problem survives a fix.”

- `backend/src/hmap/agents/refine/reflexion.py::failing_categories`: `def failing_categories(attempt: Attempt, at_least: str='major') -> set[str]`
- `backend/src/hmap/agents/refine/reflexion.py::NoteAnswer`: `class NoteAnswer(BaseModel)`
- `backend/src/hmap/agents/refine/reflexion.py::MemoryStore`: `class MemoryStore(Protocol)`
- `backend/src/hmap/agents/refine/reflexion.py::MemoryStore.load`: `async def load(self, key: str) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/refine/reflexion.py::MemoryStore.save`: `async def save(self, key: str, notes: list[dict[str, Any]]) -> None`
- `backend/src/hmap/agents/refine/reflexion.py::InMemoryStore`: `class InMemoryStore`
- `backend/src/hmap/agents/refine/reflexion.py::InMemoryStore.load`: `async def load(self, key: str) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/refine/reflexion.py::InMemoryStore.save`: `async def save(self, key: str, notes: list[dict[str, Any]]) -> None`
- `backend/src/hmap/agents/refine/reflexion.py::ArtifactMemoryStore`: “Notes as a versioned ``reflection-memory`` artifact of the project (plan D6: no migration; private to the project and erased with it).”
- `backend/src/hmap/agents/refine/reflexion.py::ArtifactMemoryStore.__init__`: `def __init__(self, artifacts: Any, project_id: str, created_by: str='refine') -> None`
- `backend/src/hmap/agents/refine/reflexion.py::ArtifactMemoryStore.artifact_id`: `def artifact_id(key: str) -> str`
- `backend/src/hmap/agents/refine/reflexion.py::ArtifactMemoryStore.load`: `async def load(self, key: str) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/refine/reflexion.py::ArtifactMemoryStore.save`: `async def save(self, key: str, notes: list[dict[str, Any]]) -> None`
- `backend/src/hmap/agents/refine/reflexion.py::ReflectionMemory`: “Per-loop Reflexion state + the project's remembered notes for ``key`` (e.g.”
- `backend/src/hmap/agents/refine/reflexion.py::ReflectionMemory.__init__`: `def __init__(self, key: str, store: MemoryStore | None=None, *, use_llm: bool=True, role: str='fast', at_least: str='major') -> None`
- `backend/src/hmap/agents/refine/reflexion.py::ReflectionMemory.load`: `async def load(self) -> 'ReflectionMemory'`
- `backend/src/hmap/agents/refine/reflexion.py::ReflectionMemory.remembered`: “Notes from earlier runs of similar tasks (shown to the reviser before its first attempt).”
- `backend/src/hmap/agents/refine/reflexion.py::ReflectionMemory.start_strategy`: “A category that a targeted fix could not solve in an earlier run starts at ``full``.”
- `backend/src/hmap/agents/refine/reflexion.py::ReflectionMemory.choose_strategy`: “Strategy for the next revision.”
- `backend/src/hmap/agents/refine/reflexion.py::ReflectionMemory.reflect`: “Write the note for the latest attempt (model ``fast`` role; a rule-made note without a model).”
- `backend/src/hmap/agents/refine/reflexion.py::ReflectionMemory.finish`: “Mark how the loop ended and persist the notes (fixed categories are recorded as such).”

## `backend/src/hmap/agents/refine/revisers/__init__.py`

“Revisers (Sprint 4 item 4.4): targeted patch (only flagged parts change), full rewrite, constrained-schema rewrite, and a strategy dispatcher.”


## `backend/src/hmap/agents/refine/revisers/patch.py`

“JSON-pointer patches (RFC 6901 paths; ``add`` / ``replace`` / ``remove`` like RFC 6902) on plain JSON values.”

- `backend/src/hmap/agents/refine/revisers/patch.py::PatchError`: `class PatchError(ValueError)`
- `backend/src/hmap/agents/refine/revisers/patch.py::Patch`: `class Patch`
- `backend/src/hmap/agents/refine/revisers/patch.py::parts`: `def parts(path: str) -> list[str]`
- `backend/src/hmap/agents/refine/revisers/patch.py::resolve`: `def resolve(doc: Any, path: str) -> Any`
- `backend/src/hmap/agents/refine/revisers/patch.py::exists`: `def exists(doc: Any, path: str) -> bool`
- `backend/src/hmap/agents/refine/revisers/patch.py::apply`: “A new document with ``patch`` applied (``add`` with a last segment ``-`` appends to a list).”
- `backend/src/hmap/agents/refine/revisers/patch.py::apply_all`: `def apply_all(doc: Any, patches: list[Patch]) -> Any`
- `backend/src/hmap/agents/refine/revisers/patch.py::within`: “``path`` is ``scope`` or below it (``/a/1/b`` is within ``/a/1``; ``/a/-`` is within ``/a``).”
- `backend/src/hmap/agents/refine/revisers/patch.py::canonical_bytes`: `def canonical_bytes(value: Any) -> bytes`

## `backend/src/hmap/agents/refine/revisers/rewrite.py`

“Full-rewrite and constrained-schema revisers (item 4.4): used when targeted patches keep failing (Reflexion's strategy change) or for outputs without stable locations.”

- `backend/src/hmap/agents/refine/revisers/rewrite.py::FullRewriteReviser`: “Asks for the whole corrected result (``schema`` constrains it).”
- `backend/src/hmap/agents/refine/revisers/rewrite.py::FullRewriteReviser.__init__`: `def __init__(self, schema: type[BaseModel], *, render_input: Callable[[Any], str] | None=None, role: str | None=None, max_tokens: int=4000, validate: Callable[[Any], str | None] | None=None) -> None`
- `backend/src/hmap/agents/refine/revisers/rewrite.py::FullRewriteReviser.revise`: `async def revise(self, output: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *, task_input: Any=None, strategy: Strategy='full') -> Revision`
- `backend/src/hmap/agents/refine/revisers/rewrite.py::SchemaReviser`: “Constrained-schema reviser: the rewrite is generated against the contract's JSON Schema (the gateway repairs invalid JSON up to twice) and must validate as ``schema``; otherwise the old output is kept.”

## `backend/src/hmap/agents/refine/revisers/strategic.py`

“Strategy dispatch (items 4.4 + 4.5): one reviser per strategy, chosen by the loop.”

- `backend/src/hmap/agents/refine/revisers/strategic.py::StrategicReviser`: “Dispatches on the loop's strategy: ``targeted`` first; ``full`` / ``widen`` when Reflexion asks for a different approach.”
- `backend/src/hmap/agents/refine/revisers/strategic.py::StrategicReviser.__init__`: `def __init__(self, revisers: dict[str, Any]) -> None`
- `backend/src/hmap/agents/refine/revisers/strategic.py::StrategicReviser.pick`: `def pick(self, strategy: Strategy) -> Any`
- `backend/src/hmap/agents/refine/revisers/strategic.py::StrategicReviser.revise`: `async def revise(self, output: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *, task_input: Any=None, strategy: Strategy='targeted') -> Revision`

## `backend/src/hmap/agents/refine/revisers/targeted.py`

“Revisers (Sprint 4 item 4.4): targeted patch, full rewrite, schema-constrained rewrite, and a dispatcher that picks one by the loop's strategy (Reflexion changes it after repeated failures).”

- `backend/src/hmap/agents/refine/revisers/targeted.py::issue_lines`: `def issue_lines(critique: Critique) -> str`
- `backend/src/hmap/agents/refine/revisers/targeted.py::reflection_lines`: “Reflexion: notes written after earlier failed attempts of this loop, plus remembered notes from earlier runs of similar tasks in the same project.”
- `backend/src/hmap/agents/refine/revisers/targeted.py::PatchOp`: `class PatchOp(BaseModel)`
- `backend/src/hmap/agents/refine/revisers/targeted.py::PatchAnswer`: `class PatchAnswer(BaseModel)`
- `backend/src/hmap/agents/refine/revisers/targeted.py::TargetedReviser`: `class TargetedReviser`
- `backend/src/hmap/agents/refine/revisers/targeted.py::TargetedReviser.__init__`: “``load(json_value)`` turns the patched JSON back into the output type (e.g.”
- `backend/src/hmap/agents/refine/revisers/targeted.py::TargetedReviser.propose`: `async def propose(self, doc: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, task_input: Any, strategy: Strategy) -> PatchAnswer`
- `backend/src/hmap/agents/refine/revisers/targeted.py::TargetedReviser.revise`: `async def revise(self, output: Any, critique: Critique, history: Sequence[Attempt], ctx: RefineContext, *, task_input: Any=None, strategy: Strategy='targeted') -> Revision`

## `backend/src/hmap/agents/refine/router.py`

“Refinement API (Sprint 4 item 4.13), mounted at ``/api/refine``.”

- `backend/src/hmap/agents/refine/router.py::RefineIn`: `class RefineIn(BaseModel)`
- `backend/src/hmap/agents/refine/router.py::policy`: `async def policy(info: CurrentSession) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/router.py::list_runs`: `async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/refine/router.py::get_run`: `async def get_run(project_id: str, run_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/router.py::get_output`: `async def get_output(project_id: str, run_id: str, index: int, info: CurrentSession, m: ManagerDep) -> Any`
- `backend/src/hmap/agents/refine/router.py::get_diff`: `async def get_diff(project_id: str, run_id: str, info: CurrentSession, m: ManagerDep, a: Annotated[int, Query(ge=0)]=0, b: Annotated[int, Query(ge=0)]=1) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/router.py::start_run`: “Check and improve one artifact of the project now (a ``refine.run`` task; its context artifacts — the document model for requirements, the requirements and report for a plan — are attached automatically).”

## `backend/src/hmap/agents/refine/stop.py`

“Stop policies (Sprint 4 item 4.6, plan D9): when does a refinement loop end?”

- `backend/src/hmap/agents/refine/stop.py::LoopState`: “Scores (0..1) and issues of every critiqued attempt so far (index 0 = the producer's output).”
- `backend/src/hmap/agents/refine/stop.py::LoopState.attempts`: `def attempts(self) -> int`
- `backend/src/hmap/agents/refine/stop.py::LoopState.revisions`: `def revisions(self) -> int`
- `backend/src/hmap/agents/refine/stop.py::LoopState.latest_score`: `def latest_score(self) -> float | None`
- `backend/src/hmap/agents/refine/stop.py::LoopState.latest_issues`: `def latest_issues(self) -> tuple[Issue, ...]`
- `backend/src/hmap/agents/refine/stop.py::LoopState.record`: `def record(self, score: float, issues: Sequence[Issue]=(), *, tokens: int | None=None, seconds: float | None=None, output: Any=None) -> 'LoopState'`
- `backend/src/hmap/agents/refine/stop.py::StopPolicy`: `class StopPolicy(Protocol)`
- `backend/src/hmap/agents/refine/stop.py::StopPolicy.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::StopPolicy.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::MaxIters`: “Stop after ``n`` revisions (each revision costs about two model calls: critique + revise).”
- `backend/src/hmap/agents/refine/stop.py::MaxIters.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::MaxIters.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::Threshold`: “Stop when the latest score is at least ``theta``.”
- `backend/src/hmap/agents/refine/stop.py::Threshold.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::Threshold.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::NoCritical`: “Stop when no issue of severity ``at_least`` or worse is left (default: nothing major or critical).”
- `backend/src/hmap/agents/refine/stop.py::NoCritical.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::NoCritical.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::Plateau`: “Stop when each of the last ``k`` revisions gained less than ``eps`` (a drop counts as no gain).”
- `backend/src/hmap/agents/refine/stop.py::Plateau.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::Plateau.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::Budget`: “Stop when the loop has used ``tokens`` model tokens or ``seconds`` of wall-clock time.”
- `backend/src/hmap/agents/refine/stop.py::Budget.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::Budget.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::TestsPass`: “Stop when ``passes(latest_output)`` is true (Member 8's code <-> test loop: the tests are green).”
- `backend/src/hmap/agents/refine/stop.py::TestsPass.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::TestsPass.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::AnyOf`: `class AnyOf`
- `backend/src/hmap/agents/refine/stop.py::AnyOf.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::AnyOf.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::AllOf`: “Stop only when every policy wants to stop; the reason is the last policy's.”
- `backend/src/hmap/agents/refine/stop.py::AllOf.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/refine/stop.py::AllOf.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/stop.py::any_of`: `def any_of(*policies: StopPolicy) -> AnyOf`
- `backend/src/hmap/agents/refine/stop.py::all_of`: `def all_of(*policies: StopPolicy) -> AllOf`
- `backend/src/hmap/agents/refine/stop.py::default_policy`: “Plan D9.”
- `backend/src/hmap/agents/refine/stop.py::policy_from_dict`: “``RefinementSpec.stop_policy`` (``{"max_iters": 3, "threshold": 0.9, ...}``) -> a policy; missing keys take the defaults.”
- `backend/src/hmap/agents/refine/stop.py::best_index`: “Regression guard: the attempt to keep is the highest score; on a tie the EARLIER one (a revision must strictly improve to replace what we have).”

## `backend/src/hmap/agents/refine/taxonomy.py`

“Error taxonomy (Sprint 4 item 4.7): every issue gets one of 10 categories x 4 severities.”

- `backend/src/hmap/agents/refine/taxonomy.py::Classification`: “One taxonomy decision (kept in the trace; labelled data for Sprint 11).”
- `backend/src/hmap/agents/refine/taxonomy.py::Classification.as_dict`: `def as_dict(self) -> dict[str, Any]`
- `backend/src/hmap/agents/refine/taxonomy.py::rule_label`: “(category, rule name) from an issue code or the wording; (None, None) when no rule applies.”
- `backend/src/hmap/agents/refine/taxonomy.py::issue_text`: `def issue_text(issue: Issue) -> str`
- `backend/src/hmap/agents/refine/taxonomy.py::question`: `def question() -> ClassifyQuestion`
- `backend/src/hmap/agents/refine/taxonomy.py::IssueClassifier`: “``classify(issues, ctx, programmatic=...)`` returns the issues with final categories and the decisions.”
- `backend/src/hmap/agents/refine/taxonomy.py::IssueClassifier.__init__`: `def __init__(self, *, use_llm: bool=True) -> None`
- `backend/src/hmap/agents/refine/taxonomy.py::IssueClassifier.classify`: `async def classify(self, issues: Sequence[Issue], ctx: RefineContext, *, programmatic: bool=False, codes: Sequence[str | None] | None=None) -> tuple[list[Issue], list[Classification]]`
- `backend/src/hmap/agents/refine/taxonomy.py::severity_ok`: `def severity_ok(severity: str) -> bool`

## `backend/src/hmap/agents/refine/trace.py`

“Refinement traces (Sprint 4 item 4.9, plan D4/D5).”

- `backend/src/hmap/agents/refine/trace.py::build_trace`: `def build_trace(spec: RefinementSpec, attempts: Sequence[Attempt], best: int | None, reason: StopReason, output_refs: Sequence[ArtifactRef | None] | None=None) -> RefinementTrace`
- `backend/src/hmap/agents/refine/trace.py::CriticScore`: `class CriticScore(BaseModel)`
- `backend/src/hmap/agents/refine/trace.py::IterationRecord`: “A ``RefinementIteration`` plus what the UI shows on an iteration card.”
- `backend/src/hmap/agents/refine/trace.py::RefineRun`: “Artifact body of ``refinement-progress`` / ``refinement-trace``.”
- `backend/src/hmap/agents/refine/trace.py::RefineRun.to_trace`: `def to_trace(self) -> RefinementTrace`
- `backend/src/hmap/agents/refine/trace.py::iteration_record`: `def iteration_record(a: Attempt, output_ref: ArtifactRef | None) -> IterationRecord`
- `backend/src/hmap/agents/refine/trace.py::run_id_for`: `def run_id_for(task_id: str | None, fallback: str) -> str`
- `backend/src/hmap/agents/refine/trace.py::TraceRecorder`: “``Refiner(on_attempt=recorder.on_attempt)``: stores outputs, progress and the final trace as they happen.”
- `backend/src/hmap/agents/refine/trace.py::TraceRecorder.__init__`: `def __init__(self, artifacts: Any, project_id: str, *, run_id: str, spec: RefinementSpec, task_id: str | None=None, capability: str | None=None, subject: str='result', created_by: str='refine', progress: ProgressFn | None=None, usage: Any=None, dump: Callable[[Any], Any] | None=None) -> None`
- `backend/src/hmap/agents/refine/trace.py::TraceRecorder.on_attempt`: `async def on_attempt(self, attempts: list[Attempt], reason: StopReason | None) -> None`
- `backend/src/hmap/agents/refine/trace.py::TraceRecorder.finish`: `async def finish(self, reason: StopReason, *, best: int, applied: bool, output_artifact: ArtifactRef | None=None, error: str | None=None) -> ArtifactRef`

## `backend/src/hmap/agents/research/__init__.py`

“Autonomous research (Member 5, Sprint 5): ``research.run`` -> a cited ``ResearchReport``.”


## `backend/src/hmap/agents/research/agent.py`

“``ResearchAgent`` (Sprint 5 item 5.10): the real ``research.run``.”

- `backend/src/hmap/agents/research/agent.py::build_brief`: `async def build_brief(task: TaskAssign, ctx: AgentContext) -> ResearchBrief`
- `backend/src/hmap/agents/research/agent.py::project_pages`: “The project's own uploaded documents as local pages (``project://<doc id>``), from Member 2's document model.”
- `backend/src/hmap/agents/research/agent.py::failure_injection`: “The platform's test / demo hooks, honoured like the stub did (chaos tests, the mid-eval failure injection): ``inputs.stub_fail`` (+ ``stub_fail_times``) fails the first attempts with that error code; ``inputs.stub_delay_s`` keeps the step b”
- `backend/src/hmap/agents/research/agent.py::ResearchAgent`: `class ResearchAgent(BaseAgent)`
- `backend/src/hmap/agents/research/agent.py::ResearchAgent.__init__`: `def __init__(self, settings: Settings | None=None, **deps: Any) -> None`
- `backend/src/hmap/agents/research/agent.py::ResearchAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/agents/research/clean.py`

“From fetched bytes to the cleaned text that evidence quotes are checked against (Sprint 5 item 5.4, plan D6).”

- `backend/src/hmap/agents/research/clean.py::CleanError`: “Nothing usable in the page (too short, unsupported type, unparsable).”
- `backend/src/hmap/agents/research/clean.py::clean`: `async def clean(data: bytes, *, url: str, media_type: str, hit: Hit | None=None, final_url: str | None=None, kind: Kind | None=None, provider: str='') -> Page`
- `backend/src/hmap/agents/research/clean.py::page_from_text`: `def page_from_text(text: str, *, url: str, title: str='', kind: Kind='web', provider: str='', media_type: str='text/plain', published: str | None=None, final_url: str | None=None, from_cache: bool=False, license: str | None=None, min_chars: int=MIN_TEXT_CHARS) -> Page`

## `backend/src/hmap/agents/research/corpus.py`

“The offline corpus (Sprint 5 item 5.14, plan D16): cleaned pages committed under ``samples/research/corpus/`` (permissive licences only, see ``samples/research/LICENSES.md``) plus anything fetched earlier into the local cache (``data/resear”

- `backend/src/hmap/agents/research/corpus.py::tokens`: `def tokens(text: str) -> list[str]`
- `backend/src/hmap/agents/research/corpus.py::PageStore`: “Pages by URL from several folders (the first folder that has a URL wins); ``save`` writes to ``write_dir``.”
- `backend/src/hmap/agents/research/corpus.py::PageStore.__init__`: `def __init__(self, dirs: Iterable[Path], write_dir: Path | None=None) -> None`
- `backend/src/hmap/agents/research/corpus.py::PageStore.get`: `def get(self, url: str) -> Page | None`
- `backend/src/hmap/agents/research/corpus.py::PageStore.pages`: `def pages(self) -> list[Page]`
- `backend/src/hmap/agents/research/corpus.py::PageStore.save`: `def save(self, page: Page) -> None`
- `backend/src/hmap/agents/research/corpus.py::PageStore.search`: “BM25 over title + text of every page (title words count three times).”
- `backend/src/hmap/agents/research/corpus.py::corpus_meta`: “Summary of the committed corpus (for the API / docs).”

## `backend/src/hmap/agents/research/evidence.py`

“Evidence extraction with quote-must-match (Sprint 5 item 5.7, plan D9).”

- `backend/src/hmap/agents/research/evidence.py::TriageAnswer`: `class TriageAnswer(BaseModel)`
- `backend/src/hmap/agents/research/evidence.py::ExtractedQuote`: `class ExtractedQuote(BaseModel)`
- `backend/src/hmap/agents/research/evidence.py::ExtractAnswer`: `class ExtractAnswer(BaseModel)`
- `backend/src/hmap/agents/research/evidence.py::Candidate`: “A selected chunk with its sub-question and page.”
- `backend/src/hmap/agents/research/evidence.py::Extraction`: `class Extraction`
- `backend/src/hmap/agents/research/evidence.py::triage`: `async def triage(cands: Sequence[Candidate], llm: LLMClient | None) -> list[Candidate]`
- `backend/src/hmap/agents/research/evidence.py::rule_quote`: “The sentence of ``text`` that shares most words with the sub-question (≥ 2 words), verbatim.”
- `backend/src/hmap/agents/research/evidence.py::extract`: `async def extract(cands: Sequence[Candidate], llm: LLMClient | None, *, first_id: int, known: set[tuple[str, int]]) -> Extraction`

## `backend/src/hmap/agents/research/fetch.py`

“Fetcher (Sprint 5 item 5.3, plan D5): from a search hit to a cleaned :class:`Page`, politely and safely.”

- `backend/src/hmap/agents/research/fetch.py::Blocked`: “The URL is not allowed (scheme, port, address, robots.txt).”
- `backend/src/hmap/agents/research/fetch.py::system_resolver`: `async def system_resolver(host: str) -> list[str]`
- `backend/src/hmap/agents/research/fetch.py::check_url`: “Raise :class:`Blocked` unless ``url`` is a public http(s) URL on a default port.”
- `backend/src/hmap/agents/research/fetch.py::FetchResult`: `class FetchResult`
- `backend/src/hmap/agents/research/fetch.py::Fetcher`: `class Fetcher`
- `backend/src/hmap/agents/research/fetch.py::Fetcher.fetch`: `async def fetch(self, hit: Hit) -> FetchResult`
- `backend/src/hmap/agents/research/fetch.py::Fetcher.aclose`: `async def aclose(self) -> None`

## `backend/src/hmap/agents/research/index.py`

“Chunk + embed + hybrid retrieval (Sprint 5 item 5.5, plan D7).”

- `backend/src/hmap/agents/research/index.py::split_sentences`: `def split_sentences(text: str) -> list[tuple[int, int]]`
- `backend/src/hmap/agents/research/index.py::chunk_page`: “Sentence-aligned chunks of about ``size`` characters; the next chunk repeats the last sentences up to ``overlap`` characters so a fact split across a boundary is still found whole.”
- `backend/src/hmap/agents/research/index.py::Retrieved`: `class Retrieved`
- `backend/src/hmap/agents/research/index.py::Backend`: `class Backend(Protocol)`
- `backend/src/hmap/agents/research/index.py::Backend.has`: `async def has(self, project_id: str, url: str, sha: str) -> bool`
- `backend/src/hmap/agents/research/index.py::Backend.add`: `async def add(self, project_id: str, sha: str, chunks: Sequence[Chunk], vectors: Sequence[list[float]]) -> None`
- `backend/src/hmap/agents/research/index.py::Backend.dense`: `async def dense(self, project_id: str, vector: list[float], k: int, urls: set[str] | None) -> list[tuple[Chunk, list[float]]]`
- `backend/src/hmap/agents/research/index.py::Backend.keyword`: `async def keyword(self, project_id: str, query: str, k: int, urls: set[str] | None) -> list[Chunk]`
- `backend/src/hmap/agents/research/index.py::Backend.vectors`: `async def vectors(self, project_id: str, chunk_ids: Sequence[str]) -> dict[str, list[float]]`
- `backend/src/hmap/agents/research/index.py::Backend.delete_project`: `async def delete_project(self, project_id: str) -> int`
- `backend/src/hmap/agents/research/index.py::cosine`: `def cosine(a: Sequence[float], b: Sequence[float]) -> float`
- `backend/src/hmap/agents/research/index.py::MemoryBackend`: `class MemoryBackend`
- `backend/src/hmap/agents/research/index.py::MemoryBackend.__init__`: `def __init__(self) -> None`
- `backend/src/hmap/agents/research/index.py::MemoryBackend.has`: `async def has(self, project_id: str, url: str, sha: str) -> bool`
- `backend/src/hmap/agents/research/index.py::MemoryBackend.add`: `async def add(self, project_id: str, sha: str, chunks: Sequence[Chunk], vectors: Sequence[list[float]]) -> None`
- `backend/src/hmap/agents/research/index.py::MemoryBackend.dense`: `async def dense(self, project_id: str, vector: list[float], k: int, urls: set[str] | None) -> list[tuple[Chunk, list[float]]]`
- `backend/src/hmap/agents/research/index.py::MemoryBackend.keyword`: `async def keyword(self, project_id: str, query: str, k: int, urls: set[str] | None) -> list[Chunk]`
- `backend/src/hmap/agents/research/index.py::MemoryBackend.vectors`: `async def vectors(self, project_id: str, chunk_ids: Sequence[str]) -> dict[str, list[float]]`
- `backend/src/hmap/agents/research/index.py::MemoryBackend.delete_project`: `async def delete_project(self, project_id: str) -> int`
- `backend/src/hmap/agents/research/index.py::PgBackend`: “``research_chunks`` in Postgres (pgvector).”
- `backend/src/hmap/agents/research/index.py::PgBackend.__init__`: `def __init__(self, db: Any) -> None`
- `backend/src/hmap/agents/research/index.py::PgBackend.has`: `async def has(self, project_id: str, url: str, sha: str) -> bool`
- `backend/src/hmap/agents/research/index.py::PgBackend.add`: `async def add(self, project_id: str, sha: str, chunks: Sequence[Chunk], vectors: Sequence[list[float]]) -> None`
- `backend/src/hmap/agents/research/index.py::PgBackend.dense`: `async def dense(self, project_id: str, vector: list[float], k: int, urls: set[str] | None) -> list[tuple[Chunk, list[float]]]`
- `backend/src/hmap/agents/research/index.py::PgBackend.keyword`: `async def keyword(self, project_id: str, query: str, k: int, urls: set[str] | None) -> list[Chunk]`
- `backend/src/hmap/agents/research/index.py::PgBackend.vectors`: `async def vectors(self, project_id: str, chunk_ids: Sequence[str]) -> dict[str, list[float]]`
- `backend/src/hmap/agents/research/index.py::PgBackend.delete_project`: `async def delete_project(self, project_id: str) -> int`
- `backend/src/hmap/agents/research/index.py::HybridIndex`: “``keyword_only`` turns on by itself when the embedding model fails (no Ollama, a missing recording): the keyword ranking keeps working and ``embed_error`` says why (shown in the trace).”
- `backend/src/hmap/agents/research/index.py::HybridIndex.add`: “Index ``page`` for ``project_id`` (no-op when this exact text is already indexed).”
- `backend/src/hmap/agents/research/index.py::HybridIndex.search`: `async def search(self, project_id: str, query: str, k: int=6, urls: set[str] | None=None, pool: int=20) -> list[Retrieved]`
- `backend/src/hmap/agents/research/index.py::HybridIndex.delete_project`: `async def delete_project(self, project_id: str) -> int`
- `backend/src/hmap/agents/research/index.py::backend_for`: “Postgres when the platform runs on Postgres (the agent shares the context store's database and schema), else memory (shared per process, so one research step's pages are reused by the next).”

## `backend/src/hmap/agents/research/model.py`

“Internal data of the research agent (Sprint 5).”

- `backend/src/hmap/agents/research/model.py::now`: `def now() -> datetime`
- `backend/src/hmap/agents/research/model.py::sha256_text`: `def sha256_text(text: str) -> str`
- `backend/src/hmap/agents/research/model.py::url_key`: `def url_key(url: str) -> str`
- `backend/src/hmap/agents/research/model.py::Hit`: “One search result.”
- `backend/src/hmap/agents/research/model.py::Page`: “A fetched and cleaned page.”
- `backend/src/hmap/agents/research/model.py::Page.host`: `def host(self) -> str`
- `backend/src/hmap/agents/research/model.py::Chunk`: `class Chunk(BaseModel)`
- `backend/src/hmap/agents/research/model.py::Scored`: `class Scored(BaseModel)`
- `backend/src/hmap/agents/research/model.py::EvidenceDraft`: “Evidence after the quote check (the contract ``Evidence`` is made from it at the end).”
- `backend/src/hmap/agents/research/model.py::RoundTrace`: `class RoundTrace(BaseModel)`
- `backend/src/hmap/agents/research/model.py::ResearchTrace`: “Body of the ``research-trace`` artifact: everything the Research tab shows besides the report.”

## `backend/src/hmap/agents/research/pipeline.py`

“The research loop (Sprint 5 §4): plan -> rounds of search / fetch / index / select / extract / track -> stop -> synthesise.”

- `backend/src/hmap/agents/research/pipeline.py::ResearchDeps`: `class ResearchDeps`
- `backend/src/hmap/agents/research/pipeline.py::ResearchOutcome`: `class ResearchOutcome`
- `backend/src/hmap/agents/research/pipeline.py::run_research`: `async def run_research(brief: ResearchBrief, deps: ResearchDeps, *, previous: ResearchReport | None=None, trace: ResearchTrace | None=None) -> ResearchOutcome`
- `backend/src/hmap/agents/research/pipeline.py::build_report`: `def build_report(task_id: str, questions: Sequence[str], subs: Sequence[SubQuestion], claims: Sequence[Claim], claim_sub: dict[str, str], evidence: Sequence[EvidenceDraft], pages: dict[str, Page], best: dict[str, Scored], stop_reason: str, page_refs: dict[str, Any] | None=None) -> ResearchReport`

## `backend/src/hmap/agents/research/planner.py`

“Research planner (Sprint 5 item 5.1): brief questions -> sub-questions, 2-3 search queries each, and what would count as answered.”

- `backend/src/hmap/agents/research/planner.py::DraftSubQuestion`: `class DraftSubQuestion(BaseModel)`
- `backend/src/hmap/agents/research/planner.py::PlanAnswer`: `class PlanAnswer(BaseModel)`
- `backend/src/hmap/agents/research/planner.py::rule_plan`: “Without a model: one sub-question per brief question; queries = the question, its key words, and its key words with the scope's key words.”
- `backend/src/hmap/agents/research/planner.py::finalise`: `def finalise(brief: ResearchBrief, drafts: list[DraftSubQuestion]) -> list[SubQuestion]`
- `backend/src/hmap/agents/research/planner.py::plan`: “(sub-questions, "model" | "rules").”

## `backend/src/hmap/agents/research/plugin.py`

“Member 5 plug-in: autonomous research (Sprint 5).”

- `backend/src/hmap/agents/research/plugin.py::announce_research`: `async def announce_research(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/research/plugin.py::forget_project`: `async def forget_project(event: DomainEvent, manager: ManagerHandle) -> None`

## `backend/src/hmap/agents/research/providers/__init__.py`

“Public search-provider registry (Sprint 5 item 5.2; reused by Member 6, Sprint 6 item 6.4).”

- `backend/src/hmap/agents/research/providers/__init__.py::page_store`: `def page_store(settings: Settings | None=None) -> PageStore`
- `backend/src/hmap/agents/research/providers/__init__.py::get_providers`: “Providers in the given order, each behind the search cache and obeying ``mode`` (``local`` keeps only the local provider).”

## `backend/src/hmap/agents/research/providers/base.py`

“Search providers (Sprint 5 item 5.2, plan D4): one small protocol, a cache in front of every provider, and a public registry (Member 6 reuses the providers for independent verification queries, Sprint 6 item 6.4).”

- `backend/src/hmap/agents/research/providers/base.py::SearchError`: “A provider failed (network, rate limit, bad answer).”
- `backend/src/hmap/agents/research/providers/base.py::SearchProvider`: `class SearchProvider(Protocol)`
- `backend/src/hmap/agents/research/providers/base.py::SearchProvider.search`: `async def search(self, query: str, k: int=5) -> list[Hit]`
- `backend/src/hmap/agents/research/providers/base.py::normalise_query`: `def normalise_query(query: str) -> str`
- `backend/src/hmap/agents/research/providers/base.py::SearchCache`: “Search results by (provider, normalised query).”
- `backend/src/hmap/agents/research/providers/base.py::SearchCache.__init__`: `def __init__(self, read_dirs: Sequence[Path], write_dir: Path | None) -> None`
- `backend/src/hmap/agents/research/providers/base.py::SearchCache.get`: `def get(self, provider: str, query: str) -> list[Hit] | None`
- `backend/src/hmap/agents/research/providers/base.py::SearchCache.put`: `def put(self, provider: str, query: str, hits: list[Hit]) -> None`
- `backend/src/hmap/agents/research/providers/base.py::CachedProvider`: “A provider behind the search cache, obeying the research mode.”
- `backend/src/hmap/agents/research/providers/base.py::CachedProvider.__init__`: `def __init__(self, inner: SearchProvider, cache: SearchCache, mode: str) -> None`
- `backend/src/hmap/agents/research/providers/base.py::CachedProvider.search`: `async def search(self, query: str, k: int=5) -> list[Hit]`

## `backend/src/hmap/agents/research/providers/local.py`

“The ``local`` provider (Sprint 5 item 5.2 "LocalCorpus"): BM25 over the offline corpus, the local page cache and the project's own uploaded documents.”

- `backend/src/hmap/agents/research/providers/local.py::LocalProvider`: `class LocalProvider`
- `backend/src/hmap/agents/research/providers/local.py::LocalProvider.__init__`: `def __init__(self, store: PageStore, project_pages: list[Page] | None=None) -> None`
- `backend/src/hmap/agents/research/providers/local.py::LocalProvider.search`: `async def search(self, query: str, k: int=5) -> list[Hit]`

## `backend/src/hmap/agents/research/providers/web.py`

“Live search providers (Sprint 5 item 5.2): Wikipedia and arXiv over their public APIs (``httpx``), DuckDuckGo via ``ddgs``.”

- `backend/src/hmap/agents/research/providers/web.py::http_client`: `def http_client(transport: httpx.AsyncBaseTransport | None=None, timeout: float=10.0) -> httpx.AsyncClient`
- `backend/src/hmap/agents/research/providers/web.py::WikipediaProvider`: “English Wikipedia search; the article's plain text comes inline (TextExtracts API), so nothing is scraped.”
- `backend/src/hmap/agents/research/providers/web.py::WikipediaProvider.__init__`: `def __init__(self, client: httpx.AsyncClient) -> None`
- `backend/src/hmap/agents/research/providers/web.py::WikipediaProvider.search`: `async def search(self, query: str, k: int=5) -> list[Hit]`
- `backend/src/hmap/agents/research/providers/web.py::ArxivProvider`: “arXiv search (Atom API).”
- `backend/src/hmap/agents/research/providers/web.py::ArxivProvider.__init__`: `def __init__(self, client: httpx.AsyncClient) -> None`
- `backend/src/hmap/agents/research/providers/web.py::ArxivProvider.search`: `async def search(self, query: str, k: int=5) -> list[Hit]`
- `backend/src/hmap/agents/research/providers/web.py::DuckDuckGoProvider`: “DuckDuckGo web search via ``ddgs`` (no API key).”
- `backend/src/hmap/agents/research/providers/web.py::DuckDuckGoProvider.search`: `async def search(self, query: str, k: int=5) -> list[Hit]`

## `backend/src/hmap/agents/research/quotes.py`

“Quote-must-match (Sprint 5 item 5.7, plan D9): a quote counts only if it is a verbatim substring of the page's cleaned text.”

- `backend/src/hmap/agents/research/quotes.py::normalise`: “Normalised text + for each of its characters the index of the original character it came from.”
- `backend/src/hmap/agents/research/quotes.py::clean_quote`: `def clean_quote(quote: str) -> str`
- `backend/src/hmap/agents/research/quotes.py::locate`: “(start, end) of ``quote`` in ``text`` (original offsets), or ``None`` when it is not there verbatim.”
- `backend/src/hmap/agents/research/quotes.py::verify`: “The verbatim quote as it appears in ``text`` (original characters), or ``None``.”
- `backend/src/hmap/agents/research/quotes.py::words`: `def words(text: str) -> set[str]`

## `backend/src/hmap/agents/research/router.py`

“Research API (Sprint 5 item 5.13), mounted at ``/api/research``.”

- `backend/src/hmap/agents/research/router.py::ResearchIn`: `class ResearchIn(BaseModel)`
- `backend/src/hmap/agents/research/router.py::providers`: `async def providers(info: CurrentSession) -> dict[str, Any]`
- `backend/src/hmap/agents/research/router.py::list_runs`: `async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/research/router.py::get_run`: `async def get_run(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/research/router.py::get_page`: `async def get_page(project_id: str, artifact_id: str, info: CurrentSession, m: ManagerDep, task_id: str | None=Query(default=None, max_length=80)) -> dict[str, Any]`
- `backend/src/hmap/agents/research/router.py::start_run`: “Research one or more questions now (an ad-hoc ``research.run`` task in this project).”

## `backend/src/hmap/agents/research/sanitize.py`

“Untrusted-content hygiene (Sprint 5 item 5.12, plan D12).”

- `backend/src/hmap/agents/research/sanitize.py::strip_hidden_html`: “HTML without the parts a reader cannot see (and without scripts / styles / templates / comments).”
- `backend/src/hmap/agents/research/sanitize.py::clean_text`: “Text without invisible characters and without AI-directed lines; returns (text, lines removed).”
- `backend/src/hmap/agents/research/sanitize.py::looks_injected`: `def looks_injected(text: str) -> bool`
- `backend/src/hmap/agents/research/sanitize.py::wrap`: “Page text for a prompt: delimited and labelled with where it came from.”

## `backend/src/hmap/agents/research/select.py`

“Source scoring and selection (Sprint 5 item 5.6, plan D8).”

- `backend/src/hmap/agents/research/select.py::authority`: `def authority(url: str) -> float`
- `backend/src/hmap/agents/research/select.py::recency`: `def recency(published: str | None, question: str, now: datetime | None=None) -> float`
- `backend/src/hmap/agents/research/select.py::shingles`: `def shingles(text: str, n: int=5) -> set[str]`
- `backend/src/hmap/agents/research/select.py::jaccard`: `def jaccard(a: set[str], b: set[str]) -> float`
- `backend/src/hmap/agents/research/select.py::select`: “The top ``k`` chunks for one sub-question, greedily (novelty and page diversity recomputed after each pick: an answer needs two independent sources, so a second passage from the same page is worth less).”

## `backend/src/hmap/agents/research/stop.py`

“Coverage tracking and stopping (Sprint 5 item 5.8, plan D10), built on Member 4's stop policies.”

- `backend/src/hmap/agents/research/stop.py::coverage`: “(sites + min(0.5, 0.25 x further quotes)) / 2, at most 1: an answer needs two independent sites - one site alone tops out at 75 % however many quotes it gives (one quote 50 %, two 62.5 %, three or more 75 %).”
- `backend/src/hmap/agents/research/stop.py::update`: `def update(subs: Sequence[SubQuestion], evidence: Sequence[EvidenceDraft], round_index: int, exhausted: set[str]) -> list[SubQuestion]`
- `backend/src/hmap/agents/research/stop.py::AllCovered`: “Every sub-question is covered (the round's mean coverage reached ``COVERED``).”
- `backend/src/hmap/agents/research/stop.py::AllCovered.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/research/stop.py::AllCovered.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/research/stop.py::LowNovelty`: “The last round added less than ``eps`` of the evidence (after the first round), or nothing is left to search (every open sub-question has used all its queries).”
- `backend/src/hmap/agents/research/stop.py::LowNovelty.check`: `def check(self, state: LoopState) -> StopReason | None`
- `backend/src/hmap/agents/research/stop.py::LowNovelty.describe`: `def describe(self) -> dict[str, Any]`
- `backend/src/hmap/agents/research/stop.py::research_policy`: “The default budget is in tokens (identical when a recorded run is replayed); a time limit applies only when the brief sets ``max_seconds`` — wall-clock time differs between recording and replay, so a default time cut would make replays take”
- `backend/src/hmap/agents/research/stop.py::research_reason`: `def research_reason(reason: str | None) -> str`

## `backend/src/hmap/agents/research/synthesize.py`

“Synthesis with citations (Sprint 5 item 5.9, plan D11).”

- `backend/src/hmap/agents/research/synthesize.py::DraftClaim`: `class DraftClaim(BaseModel)`
- `backend/src/hmap/agents/research/synthesize.py::SynthesisAnswer`: `class SynthesisAnswer(BaseModel)`
- `backend/src/hmap/agents/research/synthesize.py::check_claims`: “The citation critic: one issue per claim that is not properly cited (location ``/claims/<n>``).”
- `backend/src/hmap/agents/research/synthesize.py::rule_claims`: `def rule_claims(evidence: Sequence[EvidenceDraft], subs: Sequence[SubQuestion]) -> tuple[list[Claim], dict[str, str]]`
- `backend/src/hmap/agents/research/synthesize.py::synthesize`: “(claims, claim id -> sub-question id, dropped claims with reasons, "model" | "rules").”
- `backend/src/hmap/agents/research/synthesize.py::summary_markdown`: “A short readable report: per question, its sub-questions and their claims with numbered citations.”
- `backend/src/hmap/agents/research/synthesize.py::refine_setup`: “Member 4's ``RefineSetup`` for a research report (used when the task has ``refine=true``).”

## `backend/src/hmap/agents/stubs/__init__.py`

“hmap package.”


## `backend/src/hmap/agents/stubs/agents.py`

“Sprint-1 stub agents (item 1.16): one per capability in ``STUBBED_CAPABILITIES`` plus ``echo``.”

- `backend/src/hmap/agents/stubs/agents.py::env_delay`: “``HMAP_STUB_DELAY_S`` (environment or .env); 0 when unset or invalid.”
- `backend/src/hmap/agents/stubs/agents.py::maybe_fail`: “Injected failure (``inputs["stub_fail"]``) for the first ``stub_fail_times`` attempts (default: all).”
- `backend/src/hmap/agents/stubs/agents.py::simulate_work`: `async def simulate_work(task: TaskAssign, ctx: AgentContext) -> None`
- `backend/src/hmap/agents/stubs/agents.py::canned_output`: “The contract example re-validated with this task's ids (``project_id``/``task_id`` fields only).”
- `backend/src/hmap/agents/stubs/agents.py::StubAgent`: “Base for the canned-output stubs; subclasses set ``capabilities``, ``example`` and ``artifact_type``.”
- `backend/src/hmap/agents/stubs/agents.py::StubAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`
- `backend/src/hmap/agents/stubs/agents.py::EchoAgent`: `class EchoAgent(BaseAgent)`
- `backend/src/hmap/agents/stubs/agents.py::EchoAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`
- `backend/src/hmap/agents/stubs/agents.py::DocumentExtractStub`: `class DocumentExtractStub(StubAgent)`
- `backend/src/hmap/agents/stubs/agents.py::PlanGenerateStub`: `class PlanGenerateStub(StubAgent)`
- `backend/src/hmap/agents/stubs/agents.py::ResearchRunStub`: `class ResearchRunStub(StubAgent)`
- `backend/src/hmap/agents/stubs/agents.py::VerifyClaimsStub`: `class VerifyClaimsStub(StubAgent)`
- `backend/src/hmap/agents/stubs/agents.py::CodeImplementStub`: `class CodeImplementStub(StubAgent)`
- `backend/src/hmap/agents/stubs/agents.py::TestRunStub`: `class TestRunStub(StubAgent)`
- `backend/src/hmap/agents/stubs/agents.py::DocsGenerateStub`: `class DocsGenerateStub(StubAgent)`
- `backend/src/hmap/agents/stubs/agents.py::ReviewFinalStub`: `class ReviewFinalStub(StubAgent)`

## `backend/src/hmap/agents/stubs/plugin.py`

“Stub plug-in (priority 0): yields each capability automatically once a real plug-in declares it.”


## `backend/src/hmap/agents/testing/__init__.py`

“Member 8: automated testing & execution (Sprint 8).”


## `backend/src/hmap/agents/testing/agent.py`

“``TestingAgent`` (Sprint 8 item 8.10): the real ``test.run``.”

- `backend/src/hmap/agents/testing/agent.py::find_workspace`: “Plan D8: the coding step's workspace, then ``inputs.workspace_ref``, then the project head.”
- `backend/src/hmap/agents/testing/agent.py::TestingAgent`: `class TestingAgent(BaseAgent)`
- `backend/src/hmap/agents/testing/agent.py::TestingAgent.__init__`: `def __init__(self, settings: Settings | None=None, **deps: Any) -> None`
- `backend/src/hmap/agents/testing/agent.py::TestingAgent.on_start`: `async def on_start(self) -> None`
- `backend/src/hmap/agents/testing/agent.py::TestingAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`
- `backend/src/hmap/agents/testing/agent.py::run_mutation`: `async def run_mutation(view: View, backend: Backend, settings: Settings, cancelled: Any=None) -> mutation.MutationResult`
- `backend/src/hmap/agents/testing/agent.py::run_fuzz`: `async def run_fuzz(view: View, backend: Backend, cancelled: Any=None) -> tuple[dict[str, Any], list[Any]]`
- `backend/src/hmap/agents/testing/agent.py::acceptance_tests`: “``inputs.tests``: test files supplied with the step (the assignment's own tests, a teacher's checks).”
- `backend/src/hmap/agents/testing/agent.py::contract_failure`: `def contract_failure(f: Any) -> TestFailure`

## `backend/src/hmap/agents/testing/analyze.py`

“Failure analyser and classifier (Sprint 8 item 8.8, plan D6).”

- `backend/src/hmap/agents/testing/analyze.py::workspace_frame`: “The most relevant (file, line) of a traceback inside the workspace: the deepest frame in the code under test (or in a test when ``prefer_code`` is false or no code frame exists).”
- `backend/src/hmap/agents/testing/analyze.py::is_test_path`: `def is_test_path(rel: str) -> bool`
- `backend/src/hmap/agents/testing/analyze.py::exception_of`: “(exception type, message) of the last exception line in ``text``.”
- `backend/src/hmap/agents/testing/analyze.py::category_for_exception`: `def category_for_exception(exc: str | None, text: str) -> Category | None`
- `backend/src/hmap/agents/testing/analyze.py::rule_hint`: `def rule_hint(f: FailureRecord, exc: str | None=None, timeout_s: float | None=None) -> str`
- `backend/src/hmap/agents/testing/analyze.py::parse_ruff`: `def parse_ruff(output: str, stage: str='static') -> list[FailureRecord]`
- `backend/src/hmap/agents/testing/analyze.py::parse_mypy`: `def parse_mypy(output: str) -> list[FailureRecord]`
- `backend/src/hmap/agents/testing/analyze.py::parse_traceback_output`: “One failure from a crashed command (py_compile, the import check, a script).”
- `backend/src/hmap/agents/testing/analyze.py::parse_junit`: “(tests run, tests failed, failures, unclear node ids) from pytest's JUnit XML.”
- `backend/src/hmap/agents/testing/analyze.py::passed_nodes`: “Node ids of the tests that passed (no failure, error or skip) in a JUnit XML report.”
- `backend/src/hmap/agents/testing/analyze.py::node_id`: `def node_id(case: ET.Element) -> str`
- `backend/src/hmap/agents/testing/analyze.py::parse_bandit`: `def parse_bandit(json_text: str) -> list[FailureRecord]`
- `backend/src/hmap/agents/testing/analyze.py::code_slice`: `def code_slice(files: dict[str, str], rel: str | None, line: int | None, around: int=6) -> str`
- `backend/src/hmap/agents/testing/analyze.py::model_hints`: “Better hints for the top failures with one ``reasoner`` call; returns (model calls, tokens).”
- `backend/src/hmap/agents/testing/analyze.py::model_categories`: “``classify`` for failures whose output names no exception type (rare: custom test frameworks, bare ``sys.exit``); the rule default stays when the model is not available.”
- `backend/src/hmap/agents/testing/analyze.py::to_dicts`: `def to_dicts(failures: list[FailureRecord]) -> list[dict[str, Any]]`

## `backend/src/hmap/agents/testing/deps.py`

“Dependency audit (Sprint 8 item 8.6, the "pip-audit" part; research §3).”

- `backend/src/hmap/agents/testing/deps.py::Dep`: `class Dep`
- `backend/src/hmap/agents/testing/deps.py::AuditResult`: `class AuditResult`
- `backend/src/hmap/agents/testing/deps.py::AuditResult.as_dict`: `def as_dict(self) -> dict[str, Any]`
- `backend/src/hmap/agents/testing/deps.py::find`: `def find(files: dict[str, str]) -> tuple[list[Dep], list[str]]`
- `backend/src/hmap/agents/testing/deps.py::osv_query`: “One batch request to OSV; per query the list of advisories (id, summary when present).”
- `backend/src/hmap/agents/testing/deps.py::highest`: “The newest of the fixed versions (a pin at or above it is safe from every listed advisory).”
- `backend/src/hmap/agents/testing/deps.py::fixed_versions`: `def fixed_versions(advisory: dict[str, Any]) -> list[str]`
- `backend/src/hmap/agents/testing/deps.py::audit`: `async def audit(files: dict[str, str], mode: str, *, query: Query | None=None, cache_path: Path=CACHE) -> tuple[AuditResult, list[FailureRecord]]`

## `backend/src/hmap/agents/testing/fuzz.py`

“Fuzzing (Sprint 8 stretch; research §1: property-based testing finds edge cases a model would not think of).”

- `backend/src/hmap/agents/testing/fuzz.py::targets`: `def targets(files: dict[str, str], code_files: list[str]) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/testing/fuzz.py::plan_files`: `def plan_files(tgts: list[dict[str, Any]]) -> dict[str, str]`
- `backend/src/hmap/agents/testing/fuzz.py::parse`: `def parse(output: str, tgts: list[dict[str, Any]]) -> tuple[dict[str, Any], list[FailureRecord]]`

## `backend/src/hmap/agents/testing/governor.py`

“Resource governance for a 16 GB laptop (Sprint 8 item 8.11, plan D11).”

- `backend/src/hmap/agents/testing/governor.py::slot`: `async def slot(settings: Settings) -> AsyncIterator[None]`
- `backend/src/hmap/agents/testing/governor.py::waiting`: “True when a run would have to wait (for the UI's progress text).”
- `backend/src/hmap/agents/testing/governor.py::startup_cleanup`: `async def startup_cleanup(settings: Settings) -> int`

## `backend/src/hmap/agents/testing/hooks.py`

“Manager hook of the testing agent (Sprint 8, plan D10, D15).”

- `backend/src/hmap/agents/testing/hooks.py::result_refs`: `async def result_refs(event: DomainEvent, task: dict[str, Any]) -> list[ArtifactRef]`
- `backend/src/hmap/agents/testing/hooks.py::on_tests_done`: `async def on_tests_done(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/testing/hooks.py::start_revision`: `async def start_revision(manager: ManagerHandle, task: dict[str, Any], trace: TestingTrace, report_ref: ArtifactRef, changes: list[str]) -> tuple[str, str]`

## `backend/src/hmap/agents/testing/model.py`

“Artifact types, ids and the testing trace (Sprint 8, plan D12).”

- `backend/src/hmap/agents/testing/model.py::report_id`: `def report_id(task_id: str) -> str`
- `backend/src/hmap/agents/testing/model.py::log_id`: `def log_id(task_id: str) -> str`
- `backend/src/hmap/agents/testing/model.py::trace_id`: `def trace_id(task_id: str) -> str`
- `backend/src/hmap/agents/testing/model.py::generated_id`: `def generated_id(task_id: str) -> str`
- `backend/src/hmap/agents/testing/model.py::StepRecord`: “One command inside a stage (what ran, how it ended).”
- `backend/src/hmap/agents/testing/model.py::StageRecord`: `class StageRecord(BaseModel)`
- `backend/src/hmap/agents/testing/model.py::FailureRecord`: “A failure as the analyser found it; ``TestFailure`` in the report is the contract view of it.”
- `backend/src/hmap/agents/testing/model.py::FailureRecord.short`: `def short(self) -> str`
- `backend/src/hmap/agents/testing/model.py::LoopState`: “The test -> revise loop this run belongs to (plan D10).”
- `backend/src/hmap/agents/testing/model.py::TestingTrace`: `class TestingTrace(BaseModel)`

## `backend/src/hmap/agents/testing/mutation.py`

“Mutation testing (Sprint 8 stretch; research §2: "a better quality signal than coverage").”

- `backend/src/hmap/agents/testing/mutation.py::Mutant`: `class Mutant`
- `backend/src/hmap/agents/testing/mutation.py::MutationResult`: `class MutationResult`
- `backend/src/hmap/agents/testing/mutation.py::MutationResult.score`: `def score(self) -> float | None`
- `backend/src/hmap/agents/testing/mutation.py::MutationResult.as_dict`: `def as_dict(self) -> dict[str, Any]`
- `backend/src/hmap/agents/testing/mutation.py::make_mutants`: `def make_mutants(files: dict[str, str], code_files: list[str], limit: int) -> list[Mutant]`
- `backend/src/hmap/agents/testing/mutation.py::plan_files`: `def plan_files(mutants: list[Mutant]) -> dict[str, str]`
- `backend/src/hmap/agents/testing/mutation.py::parse`: `def parse(output: str, mutants: list[Mutant]) -> MutationResult`

## `backend/src/hmap/agents/testing/pipeline.py`

“The stage pipeline (Sprint 8 item 8.2, plan D5, D7).”

- `backend/src/hmap/agents/testing/pipeline.py::normalise`: “Replay-stable, path-free command output (what prompts and logs may contain).”
- `backend/src/hmap/agents/testing/pipeline.py::PipelineResult`: `class PipelineResult`
- `backend/src/hmap/agents/testing/pipeline.py::PipelineResult.passed`: “No failure that counts: LINT findings, flaky tests and fuzz findings are reported but do not fail the run.”
- `backend/src/hmap/agents/testing/pipeline.py::PipelineResult.pass_ratio`: `def pass_ratio(self) -> float`
- `backend/src/hmap/agents/testing/pipeline.py::PipelineResult.log_text`: `def log_text(self) -> str`
- `backend/src/hmap/agents/testing/pipeline.py::dedupe`: “One failure per (category, file, line): ruff and py_compile both report the same syntax error.”
- `backend/src/hmap/agents/testing/pipeline.py::all_steps`: `def all_steps(view: View) -> list[Step]`
- `backend/src/hmap/agents/testing/pipeline.py::record_steps`: `def record_steps(run: RunResult) -> list[StepRecord]`
- `backend/src/hmap/agents/testing/pipeline.py::run_pipeline`: `async def run_pipeline(view: View, backend: Backend, *, cancelled: asyncio.Event | None=None, flaky_check: bool=True) -> PipelineResult`
- `backend/src/hmap/agents/testing/pipeline.py::recheck_flaky`: “Re-run each failed test once; pass-then-fail is FLAKY (research §5).”

## `backend/src/hmap/agents/testing/plugin.py`

“Member 8 plug-in: automated testing & execution (Sprint 8).”


## `backend/src/hmap/agents/testing/quarantine.py`

“Flaky-test quarantine (Sprint 8 stretch, research §5).”

- `backend/src/hmap/agents/testing/quarantine.py::quarantine_id`: `def quarantine_id(project_id: str) -> str`
- `backend/src/hmap/agents/testing/quarantine.py::Entry`: `class Entry(BaseModel)`
- `backend/src/hmap/agents/testing/quarantine.py::Quarantine`: `class Quarantine(BaseModel)`
- `backend/src/hmap/agents/testing/quarantine.py::Quarantine.active`: `def active(self) -> set[str]`
- `backend/src/hmap/agents/testing/quarantine.py::load`: `async def load(store: ArtifactStore, project_id: str) -> Quarantine`
- `backend/src/hmap/agents/testing/quarantine.py::save`: `async def save(store: ArtifactStore, q: Quarantine, created_by: str) -> None`
- `backend/src/hmap/agents/testing/quarantine.py::apply`: “Mark failures of quarantined tests as flaky; returns the node ids that were quarantined in this run.”
- `backend/src/hmap/agents/testing/quarantine.py::update`: “New flaky tests in, clean passes counted, released after ``RELEASE_AFTER``; returns True when it changed.”
- `backend/src/hmap/agents/testing/quarantine.py::release`: `def release(q: Quarantine, node: str) -> bool`
- `backend/src/hmap/agents/testing/quarantine.py::as_dict`: `def as_dict(q: Quarantine) -> dict[str, Any]`

## `backend/src/hmap/agents/testing/refine_loop.py`

“The code -> test -> revise loop with Member 7 (Sprint 8 item 8.9, plan D10).”

- `backend/src/hmap/agents/testing/refine_loop.py::Decision`: `class Decision`
- `backend/src/hmap/agents/testing/refine_loop.py::actionable`: `def actionable(failures: list[FailureRecord]) -> list[FailureRecord]`
- `backend/src/hmap/agents/testing/refine_loop.py::signature`: `def signature(failures: list[FailureRecord]) -> list[str]`
- `backend/src/hmap/agents/testing/refine_loop.py::required_changes`: `def required_changes(failures: list[FailureRecord]) -> list[str]`
- `backend/src/hmap/agents/testing/refine_loop.py::decide`: `def decide(trace: TestingTrace, *, enabled: bool, max_rounds: int) -> Decision`

## `backend/src/hmap/agents/testing/router.py`

“Testing API (Sprint 8 item 8.14, plan D16), mounted at ``/api/testing``.”

- `backend/src/hmap/agents/testing/router.py::summary`: `def summary(trace: dict[str, Any]) -> dict[str, Any]`
- `backend/src/hmap/agents/testing/router.py::list_runs`: `async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/testing/router.py::get_run`: `async def get_run(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/testing/router.py::get_log`: `async def get_log(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> str`
- `backend/src/hmap/agents/testing/router.py::rerun`: `async def rerun(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/testing/router.py::ReleaseIn`: `class ReleaseIn(BaseModel)`
- `backend/src/hmap/agents/testing/router.py::get_quarantine`: `async def get_quarantine(project_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/testing/router.py::release_test`: `async def release_test(project_id: str, body: ReleaseIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`

## `backend/src/hmap/agents/testing/sandbox/__init__.py`

“Where generated code runs (Sprint 8 items 8.1 / 8.11, plan D1-D4, D11).”

- `backend/src/hmap/agents/testing/sandbox/__init__.py::Step`: `class Step`
- `backend/src/hmap/agents/testing/sandbox/__init__.py::Step.plan`: `def plan(self) -> dict[str, object]`
- `backend/src/hmap/agents/testing/sandbox/__init__.py::StepResult`: `class StepResult`
- `backend/src/hmap/agents/testing/sandbox/__init__.py::StepResult.ok`: `def ok(self) -> bool`
- `backend/src/hmap/agents/testing/sandbox/__init__.py::RunResult`: `class RunResult`
- `backend/src/hmap/agents/testing/sandbox/__init__.py::RunResult.get`: `def get(self, name: str) -> StepResult | None`
- `backend/src/hmap/agents/testing/sandbox/__init__.py::Backend`: `class Backend(Protocol)`
- `backend/src/hmap/agents/testing/sandbox/__init__.py::Backend.run`: `async def run(self, files: dict[str, str], steps: list[Step], *, cancelled: asyncio.Event | None=None, image: str | None=None) -> RunResult`
- `backend/src/hmap/agents/testing/sandbox/__init__.py::choose`: `async def choose(settings: Settings) -> Backend`

## `backend/src/hmap/agents/testing/sandbox/docker.py`

“Docker sandbox (Sprint 8 item 8.1, plan D1, D3, D4; ported from ``samples/testing/sandbox/run_sandbox.py``).”

- `backend/src/hmap/agents/testing/sandbox/docker.py::docker_ready`: “Docker answers and the sandbox image exists (cached for a minute; a task never builds the image).”
- `backend/src/hmap/agents/testing/sandbox/docker.py::forget_ready`: `def forget_ready() -> None`
- `backend/src/hmap/agents/testing/sandbox/docker.py::tar_files`: `def tar_files(files: dict[str, str]) -> bytes`
- `backend/src/hmap/agents/testing/sandbox/docker.py::docker_args`: “Under runc the cgroup limits stop the program itself (the OOM killer picks the hog, ``fork`` fails at the pids limit) and the runner adds a process cap.”
- `backend/src/hmap/agents/testing/sandbox/docker.py::reap`: “Remove sandbox containers left behind by a crashed process (exited, or running longer than any run may).”
- `backend/src/hmap/agents/testing/sandbox/docker.py::DockerBackend`: `class DockerBackend`
- `backend/src/hmap/agents/testing/sandbox/docker.py::DockerBackend.__init__`: `def __init__(self, settings: Settings) -> None`
- `backend/src/hmap/agents/testing/sandbox/docker.py::DockerBackend.run`: `async def run(self, files: dict[str, str], steps: list[Step], *, cancelled: asyncio.Event | None=None, image: str | None=None) -> RunResult`

## `backend/src/hmap/agents/testing/sandbox/local.py`

“Local fallback sandbox (plan D2): Member 7's jailed runner when Docker is not running.”

- `backend/src/hmap/agents/testing/sandbox/local.py::LocalBackend`: `class LocalBackend`
- `backend/src/hmap/agents/testing/sandbox/local.py::LocalBackend.__init__`: `def __init__(self, settings: Settings) -> None`
- `backend/src/hmap/agents/testing/sandbox/local.py::LocalBackend.run`: `async def run(self, files: dict[str, str], steps: list[Step], *, cancelled: asyncio.Event | None=None, image: str | None=None) -> RunResult`

## `backend/src/hmap/agents/testing/sandbox/stages.py`

“Runs INSIDE the sandbox container (plan D3, D5); copied into the image as ``/opt/hmap/stages.py`` (both the Python and the Node image).”

- `backend/src/hmap/agents/testing/sandbox/stages.py::cap`: `def cap(text: str, limit: int=STEP_OUTPUT_CAP) -> str`
- `backend/src/hmap/agents/testing/sandbox/stages.py::command`: `def command(step: dict[str, Any]) -> list[str]`
- `backend/src/hmap/agents/testing/sandbox/stages.py::set_limits`: “Runs in the child before exec: per-process limits (processes for this user, address space).”
- `backend/src/hmap/agents/testing/sandbox/stages.py::run_step`: `def run_step(step: dict[str, Any]) -> dict[str, Any]`
- `backend/src/hmap/agents/testing/sandbox/stages.py::extract`: “Regular files only, relative paths only (no "..", no links): the workspace tar is untrusted.”
- `backend/src/hmap/agents/testing/sandbox/stages.py::main`: `def main() -> None`

## `backend/src/hmap/agents/testing/stages/__init__.py`

“The stages of a test run (Sprint 8 items 8.2-8.6, plan D5), cheapest first:”

- `backend/src/hmap/agents/testing/stages/__init__.py::is_test_file`: `def is_test_file(rel: str) -> bool`
- `backend/src/hmap/agents/testing/stages/__init__.py::is_integration_test`: `def is_integration_test(rel: str, text: str) -> bool`
- `backend/src/hmap/agents/testing/stages/__init__.py::View`: `class View`
- `backend/src/hmap/agents/testing/stages/__init__.py::View.names`: `def names(self) -> set[str]`
- `backend/src/hmap/agents/testing/stages/__init__.py::View.py_files`: `def py_files(self) -> list[str]`
- `backend/src/hmap/agents/testing/stages/__init__.py::View.code_files`: `def code_files(self) -> list[str]`
- `backend/src/hmap/agents/testing/stages/__init__.py::View.integration_tests`: `def integration_tests(self) -> list[str]`
- `backend/src/hmap/agents/testing/stages/__init__.py::View.unit_tests`: `def unit_tests(self) -> list[str]`
- `backend/src/hmap/agents/testing/stages/__init__.py::View.modules`: `def modules(self) -> list[str]`
- `backend/src/hmap/agents/testing/stages/__init__.py::View.has_mypy_config`: `def has_mypy_config(self) -> bool`

## `backend/src/hmap/agents/testing/stages/build.py`

“Build / import (item 8.2): every Python file compiles, then every module of the code under test imports.”

- `backend/src/hmap/agents/testing/stages/build.py::steps`: `def steps(view: View) -> list[Step]`
- `backend/src/hmap/agents/testing/stages/build.py::evaluate`: `def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]`

## `backend/src/hmap/agents/testing/stages/execution.py`

“Execution (item 8.2, plan D5): run the program's entry point with a sample input, only when the task names one (``inputs.entrypoint`` = ``"main.py --flag"``, ``inputs.sample_input`` = stdin text).”

- `backend/src/hmap/agents/testing/stages/execution.py::parse_entrypoint`: `def parse_entrypoint(raw: object) -> list[str]`
- `backend/src/hmap/agents/testing/stages/execution.py::steps`: `def steps(view: View) -> list[Step]`
- `backend/src/hmap/agents/testing/stages/execution.py::evaluate`: `def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]`

## `backend/src/hmap/agents/testing/stages/integration.py`

“Integration tests (item 8.5): tests in an ``integration`` folder / file name or marked ``pytest.mark.integration`` (e.g.”

- `backend/src/hmap/agents/testing/stages/integration.py::steps`: `def steps(view: View) -> list[Step]`
- `backend/src/hmap/agents/testing/stages/integration.py::evaluate`: `def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]`

## `backend/src/hmap/agents/testing/stages/node.py`

“JavaScript / TypeScript projects (Sprint 8 stretch: JS/TS + per-language images).”

- `backend/src/hmap/agents/testing/stages/node.py::is_js_project`: `def is_js_project(files: dict[str, str]) -> bool`
- `backend/src/hmap/agents/testing/stages/node.py::js_files`: `def js_files(view: View) -> list[str]`
- `backend/src/hmap/agents/testing/stages/node.py::ts_files`: `def ts_files(view: View) -> list[str]`
- `backend/src/hmap/agents/testing/stages/node.py::is_test`: `def is_test(rel: str) -> bool`
- `backend/src/hmap/agents/testing/stages/node.py::steps`: `def steps(view: View) -> list[Step]`
- `backend/src/hmap/agents/testing/stages/node.py::parse_eslint`: “ESLint's JSON report (``--format json``; the plain formats left ESLint core in v9).”
- `backend/src/hmap/agents/testing/stages/node.py::parse_tsc`: “(syntax errors for build, type errors for static).”
- `backend/src/hmap/agents/testing/stages/node.py::scan_js`: `def scan_js(rel: str, text: str) -> list[FailureRecord]`
- `backend/src/hmap/agents/testing/stages/node.py::evaluate`: `def evaluate(view: View, run: RunResult) -> dict[str, tuple[StageRecord, list[FailureRecord]]]`

## `backend/src/hmap/agents/testing/stages/security.py`

“Security (item 8.6): bandit inside the Docker sandbox, plus built-in rules that run on the host on every backend (they parse the code with ``ast`` and never execute it) and a secret-pattern scan.”

- `backend/src/hmap/agents/testing/stages/security.py::steps`: `def steps(view: View) -> list[Step]`
- `backend/src/hmap/agents/testing/stages/security.py::scan_source`: “Built-in rules (a small bandit subset that needs no execution and no extra package).”
- `backend/src/hmap/agents/testing/stages/security.py::evaluate`: `def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]`

## `backend/src/hmap/agents/testing/stages/static.py`

“Static analysis (item 8.3): ruff with an explicit rule list (E4, E7, E9, F: syntax, undefined / unused names, statement problems; defaults change between ruff versions) and mypy when the workspace configures it (Docker only: mypy can load p”

- `backend/src/hmap/agents/testing/stages/static.py::steps`: `def steps(view: View) -> list[Step]`
- `backend/src/hmap/agents/testing/stages/static.py::evaluate`: `def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]`

## `backend/src/hmap/agents/testing/stages/unit.py`

“Unit tests (item 8.4): pytest over the workspace's tests (integration tests excluded), per-test results from JUnit XML, coverage % of the code under test (Docker image only: ``coverage`` is not in the local coding venv).”

- `backend/src/hmap/agents/testing/stages/unit.py::pytest_step`: `def pytest_step(view: View, stage: str, files: list[str], timeout: float, *, coverage: bool=False) -> Step`
- `backend/src/hmap/agents/testing/stages/unit.py::steps`: `def steps(view: View) -> list[Step]`
- `backend/src/hmap/agents/testing/stages/unit.py::coverage_of`: `def coverage_of(res: StepResult) -> float | None`
- `backend/src/hmap/agents/testing/stages/unit.py::evaluate_tests`: `def evaluate_tests(view: View, run: RunResult, stage: str) -> tuple[StageRecord, list[FailureRecord]]`
- `backend/src/hmap/agents/testing/stages/unit.py::last_test`: “The test that was running when the stage was killed (pytest -q prints nothing per test; take the last node id it mentioned).”
- `backend/src/hmap/agents/testing/stages/unit.py::evaluate`: `def evaluate(view: View, run: RunResult) -> tuple[StageRecord, list[FailureRecord]]`

## `backend/src/hmap/agents/testing/testgen.py`

“Tests written from the acceptance criteria (Sprint 8 item 8.7, plan D9).”

- `backend/src/hmap/agents/testing/testgen.py::Generated`: `class Generated`
- `backend/src/hmap/agents/testing/testgen.py::Generated.deselect`: `def deselect(self) -> list[str]`
- `backend/src/hmap/agents/testing/testgen.py::Generated.summary`: `def summary(self) -> dict[str, object]`
- `backend/src/hmap/agents/testing/testgen.py::wanted`: `def wanted(view: View, criteria: list[str], *, asked: bool, enabled: bool) -> bool`
- `backend/src/hmap/agents/testing/testgen.py::outline`: `def outline(view: View) -> str`
- `backend/src/hmap/agents/testing/testgen.py::extract_code`: `def extract_code(text: str) -> str`
- `backend/src/hmap/agents/testing/testgen.py::stub_source`: “The same module with every function body replaced by ``raise NotImplementedError`` (the known-bad version the gate needs).”
- `backend/src/hmap/agents/testing/testgen.py::generate`: `async def generate(llm: LLMClient, view: View, criteria: list[str], objective: str) -> Generated`
- `backend/src/hmap/agents/testing/testgen.py::gate`: “Run the generated tests against the known-bad stub; keep only those that fail there.”

## `backend/src/hmap/agents/verify/__init__.py`

“Member 6 (Sprint 6): research verification — ``verify.claims``.”


## `backend/src/hmap/agents/verify/agent.py`

“``VerifyAgent`` (Sprint 6 item 6.7): the real ``verify.claims``.”

- `backend/src/hmap/agents/verify/agent.py::failure_injection`: “The platform's test / demo hooks, only when a task asks for them (as the stub and Member 5's agent do).”
- `backend/src/hmap/agents/verify/agent.py::report_ref_of`: `def report_ref_of(task: TaskAssign) -> ArtifactRef | None`
- `backend/src/hmap/agents/verify/agent.py::summary_line`: `def summary_line(report: VerificationReport) -> str`
- `backend/src/hmap/agents/verify/agent.py::providers_for`: “Member 5's providers behind the VERIFIER's own search cache (never the researcher's queries).”
- `backend/src/hmap/agents/verify/agent.py::VerifyAgent`: `class VerifyAgent(BaseAgent)`
- `backend/src/hmap/agents/verify/agent.py::VerifyAgent.__init__`: `def __init__(self, settings: Settings | None=None, **deps: Any) -> None`
- `backend/src/hmap/agents/verify/agent.py::VerifyAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/agents/verify/aggregate.py`

“Aggregator: layer results → verdict + confidence + explanation (Sprint 6 item 6.6).”

- `backend/src/hmap/agents/verify/aggregate.py::Row`: `class Row`
- `backend/src/hmap/agents/verify/aggregate.py::decide`: `def decide(atom: AtomCheck, layers: frozenset[str]) -> AtomCheck`
- `backend/src/hmap/agents/verify/aggregate.py::explain`: `def explain(atom: AtomCheck, row: Row) -> str`
- `backend/src/hmap/agents/verify/aggregate.py::roll_up`: `def roll_up(claim: ClaimCheck) -> ClaimCheck`
- `backend/src/hmap/agents/verify/aggregate.py::follow_up_questions`: “Gap questions for follow-up research (6.8): the flagged claims, least settled first.”

## `backend/src/hmap/agents/verify/benchmark.py`

“The seeded-hallucination benchmark (``samples/verify/``, item 6.9) as Python objects, and one item verified.”

- `backend/src/hmap/agents/verify/benchmark.py::Item`: `class Item`
- `backend/src/hmap/agents/verify/benchmark.py::load`: `def load(path: Path=BENCHMARK) -> list[Item]`
- `backend/src/hmap/agents/verify/benchmark.py::page_file`: `def page_file(rel: str) -> Page | None`
- `backend/src/hmap/agents/verify/benchmark.py::load_page`: `async def load_page(q: Quote) -> Page | None`
- `backend/src/hmap/agents/verify/benchmark.py::counter_passages`: `def counter_passages(item: Item) -> list[Passage]`
- `backend/src/hmap/agents/verify/benchmark.py::verify_item`: `async def verify_item(item: Item, deps: VerifyDeps, *, use_counter: bool=True) -> ClaimCheck`

## `backend/src/hmap/agents/verify/claims.py`

“Claim atomization and check-worthiness (Sprint 6 item 6.1).”

- `backend/src/hmap/agents/verify/claims.py::Atom`: `class Atom`
- `backend/src/hmap/agents/verify/claims.py::check_worthy`: `def check_worthy(text: str) -> bool`
- `backend/src/hmap/agents/verify/claims.py::split_claim`: “The atomic parts of a claim (at least one: the claim itself).”
- `backend/src/hmap/agents/verify/claims.py::atomize`: `def atomize(claim_id: str, text: str) -> list[Atom]`

## `backend/src/hmap/agents/verify/compare.py`

“L4 — cross-source comparison and conflict detection (Sprint 6 item 6.5).”

- `backend/src/hmap/agents/verify/compare.py::signals`: `def signals(claim: str, passage: str) -> list[str]`
- `backend/src/hmap/agents/verify/compare.py::compare`: `async def compare(claim: str, passages: Sequence[Passage], *, llm: LLMClient | None, usage: Usage, max_judged: int=MAX_JUDGED) -> list[Comparison]`
- `backend/src/hmap/agents/verify/compare.py::independent_sites`: `def independent_sites(comps: Sequence[Comparison], cited_urls: Sequence[str]) -> list[str]`
- `backend/src/hmap/agents/verify/compare.py::newer_source`: `def newer_source(comps: Sequence[Comparison]) -> str`

## `backend/src/hmap/agents/verify/entail.py`

“L2 — does the quoted text support the claim?”

- `backend/src/hmap/agents/verify/entail.py::EntailAnswer`: `class EntailAnswer(BaseModel)`
- `backend/src/hmap/agents/verify/entail.py::Usage`: `class Usage`
- `backend/src/hmap/agents/verify/entail.py::messages`: `def messages(claim: str, passages: Sequence[tuple[str, str]], *, swapped: bool=False) -> list[dict[str, str]]`
- `backend/src/hmap/agents/verify/entail.py::rules_label`: `def rules_label(claim: str, passages: Sequence[tuple[str, str]]) -> tuple[Label, str]`
- `backend/src/hmap/agents/verify/entail.py::guard`: `def guard(claim: str, passages: Sequence[tuple[str, str]], label: Label) -> tuple[Label, str]`
- `backend/src/hmap/agents/verify/entail.py::judge`: “One judgement of ``claim`` against ``passages`` [(source, text)].”

## `backend/src/hmap/agents/verify/hooks.py`

“Manager hooks of the verifier (Sprint 6 items 6.7 / 6.8).”

- `backend/src/hmap/agents/verify/hooks.py::result_refs`: `async def result_refs(manager: ManagerHandle, task: dict[str, Any]) -> list[ArtifactRef]`
- `backend/src/hmap/agents/verify/hooks.py::request_follow_up`: “Create follow-up research + a re-check; ``None`` when there is nothing to do or the round cap is reached.”
- `backend/src/hmap/agents/verify/hooks.py::on_verified`: `async def on_verified(event: DomainEvent, manager: ManagerHandle) -> None`
- `backend/src/hmap/agents/verify/hooks.py::report_json`: `def report_json(raw: bytes) -> dict[str, Any]`

## `backend/src/hmap/agents/verify/independent.py`

“L3 — independent retrieval (Sprint 6 item 6.4).”

- `backend/src/hmap/agents/verify/independent.py::Queries`: `class Queries(BaseModel)`
- `backend/src/hmap/agents/verify/independent.py::Retrieval`: `class Retrieval`
- `backend/src/hmap/agents/verify/independent.py::rule_query`: `def rule_query(claim: str) -> str`
- `backend/src/hmap/agents/verify/independent.py::make_queries`: `async def make_queries(llm: LLMClient | None, claim: str, usage: Usage) -> list[str]`
- `backend/src/hmap/agents/verify/independent.py::best_passages`: `def best_passages(claim: str, page: Page, *, origin: Literal['independent', 'counter']='independent', query: str='') -> list[Passage]`
- `backend/src/hmap/agents/verify/independent.py::retrieve`: “Search with the verifier's own queries; candidate passages from pages the claim does not already cite.”

## `backend/src/hmap/agents/verify/mechanical.py`

“L1 — the mechanical check (Sprint 6 item 6.2).”

- `backend/src/hmap/agents/verify/mechanical.py::check_quote`: `def check_quote(q: Quote, page: Page | None) -> L1Result`
- `backend/src/hmap/agents/verify/mechanical.py::check_claim`: `async def check_claim(evidence_ids: Sequence[str], evidence: dict[str, Quote], load: PageLoader) -> list[L1Result]`
- `backend/src/hmap/agents/verify/mechanical.py::passed`: `def passed(results: Sequence[L1Result]) -> bool`

## `backend/src/hmap/agents/verify/model.py`

“Working records of the verifier (Sprint 6) and the ``verification-trace`` artifact body.”

- `backend/src/hmap/agents/verify/model.py::now`: `def now() -> datetime`
- `backend/src/hmap/agents/verify/model.py::Quote`: “One piece of cited evidence as the verifier sees it (from a ``ResearchReport`` or a benchmark item).”
- `backend/src/hmap/agents/verify/model.py::L1Result`: `class L1Result(BaseModel)`
- `backend/src/hmap/agents/verify/model.py::Judgement`: “One entailment decision (L2 on the cited quotes, L4 on a passage from another source).”
- `backend/src/hmap/agents/verify/model.py::Judgement.unsure`: `def unsure(self) -> bool`
- `backend/src/hmap/agents/verify/model.py::Passage`: “A sentence or two from another source (L3), or a counter-source handed in (benchmark).”
- `backend/src/hmap/agents/verify/model.py::Comparison`: “L4 on one passage: rule signals + (when asked) a judgement.”
- `backend/src/hmap/agents/verify/model.py::Comparison.conflict`: `def conflict(self) -> bool`
- `backend/src/hmap/agents/verify/model.py::Comparison.agrees`: `def agrees(self) -> bool`
- `backend/src/hmap/agents/verify/model.py::AtomCheck`: “Every layer's result for one atomic claim.”
- `backend/src/hmap/agents/verify/model.py::ClaimCheck`: `class ClaimCheck(BaseModel)`
- `backend/src/hmap/agents/verify/model.py::VerificationTrace`: “Body of the ``verification-trace`` artifact (``vt-<task_id>``): what the Verify tab shows besides the report.”

## `backend/src/hmap/agents/verify/pipeline.py`

“The verification pipeline (Sprint 6 §4): claim → atoms → L1 → L2 → L3 → L4 → decision table → roll-up.”

- `backend/src/hmap/agents/verify/pipeline.py::VerifyDeps`: `class VerifyDeps`
- `backend/src/hmap/agents/verify/pipeline.py::quotes_of`: `def quotes_of(report: ResearchReport) -> dict[str, Quote]`
- `backend/src/hmap/agents/verify/pipeline.py::check_claim`: `async def check_claim(claim_id: str, text: str, evidence_ids: Sequence[str], evidence: dict[str, Quote], deps: VerifyDeps, *, counter: Sequence[Passage]=()) -> ClaimCheck`
- `backend/src/hmap/agents/verify/pipeline.py::verify_report`: “Check every claim of ``report``; fills ``trace`` and returns the ``VerificationReport``.”
- `backend/src/hmap/agents/verify/pipeline.py::build_report`: `def build_report(trace: VerificationTrace) -> VerificationReport`

## `backend/src/hmap/agents/verify/plugin.py`

“Member 6 plug-in: research verification (Sprint 6).”


## `backend/src/hmap/agents/verify/router.py`

“Verify API (Sprint 6 item 6.11), mounted at ``/api/verify``.”

- `backend/src/hmap/agents/verify/router.py::FollowUpIn`: `class FollowUpIn(BaseModel)`
- `backend/src/hmap/agents/verify/router.py::decision_table`: `async def decision_table(info: CurrentSession) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/verify/router.py::security`: “Platform-wide (like the agents page): what agents may send, and what was refused recently.”
- `backend/src/hmap/agents/verify/router.py::list_runs`: `async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]`
- `backend/src/hmap/agents/verify/router.py::get_run`: `async def get_run(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/agents/verify/router.py::follow_up`: “A human asks for more research: on the chosen claims (default: what the check flagged) + a re-check.”

## `backend/src/hmap/agents/verify/textual.py`

“Small text signals shared by the layers: content words, numbers, years, negation.”

- `backend/src/hmap/agents/verify/textual.py::normalise`: `def normalise(text: str) -> str`
- `backend/src/hmap/agents/verify/textual.py::content_words`: `def content_words(text: str) -> list[str]`
- `backend/src/hmap/agents/verify/textual.py::overlap`: “Share of the claim's distinct content words that occur in ``text`` (0..1).”
- `backend/src/hmap/agents/verify/textual.py::numbers`: `def numbers(text: str) -> set[str]`
- `backend/src/hmap/agents/verify/textual.py::years`: `def years(text: str) -> set[str]`
- `backend/src/hmap/agents/verify/textual.py::negated`: `def negated(text: str) -> bool`
- `backend/src/hmap/agents/verify/textual.py::missing_numbers`: “Numbers the claim states that the evidence never mentions (a changed figure is the commonest error).”
- `backend/src/hmap/agents/verify/textual.py::host`: `def host(url: str) -> str`
- `backend/src/hmap/agents/verify/textual.py::site`: “The registrable-ish domain (``en.wikipedia.org`` → ``wikipedia.org``) for domain-diversity counting.”

## `backend/src/hmap/api/__init__.py`

“hmap package.”


## `backend/src/hmap/api/app.py`

“FastAPI application (Sprint 1 item 1.15).”

- `backend/src/hmap/api/app.py::build_mailer`: `def build_mailer(settings: Settings) -> Mailer`
- `backend/src/hmap/api/app.py::allowed_origins`: `def allowed_origins(settings: Settings) -> list[str]`
- `backend/src/hmap/api/app.py::create_app`: “With no ``hmap_system`` one is built from the environment.”

## `backend/src/hmap/api/deps.py`

“FastAPI dependencies: the running system lives on ``app.state``; the signed-in user comes from the session cookie.”

- `backend/src/hmap/api/deps.py::get_system`: `def get_system(request: Request) -> HmapSystem`
- `backend/src/hmap/api/deps.py::get_manager`: `def get_manager(request: Request) -> Manager`
- `backend/src/hmap/api/deps.py::get_feed`: `def get_feed(request: Request) -> EventFeed`
- `backend/src/hmap/api/deps.py::get_accounts`: `def get_accounts(request: Request) -> AccountService`
- `backend/src/hmap/api/deps.py::client_address`: “The caller's address for rate limiting.”
- `backend/src/hmap/api/deps.py::check_csrf`: `def check_csrf(request: Request) -> None`
- `backend/src/hmap/api/deps.py::current_session`: `async def current_session(request: Request) -> SessionInfo`

## `backend/src/hmap/api/feed.py`

“Live event feed for the UI: subscribes to every domain event (``#``), keeps a bounded history (snapshot for reconnecting clients) and fans events out to WebSocket listeners.”

- `backend/src/hmap/api/feed.py::EventFeed`: `class EventFeed`
- `backend/src/hmap/api/feed.py::EventFeed.__init__`: `def __init__(self, bus: Bus, *, history: int=5000, listener_queue: int=1000) -> None`
- `backend/src/hmap/api/feed.py::EventFeed.start`: `async def start(self) -> None`
- `backend/src/hmap/api/feed.py::EventFeed.preload_from`: “Fill the history with the newest stored events (``hmap.db.Database``); returns how many were loaded.”
- `backend/src/hmap/api/feed.py::EventFeed.stop`: `async def stop(self) -> None`
- `backend/src/hmap/api/feed.py::EventFeed.snapshot`: `def snapshot(self, *, project_id: str | None=None, after_seq: int=0) -> list[dict[str, Any]]`
- `backend/src/hmap/api/feed.py::EventFeed.listen`: `def listen(self) -> asyncio.Queue[dict[str, Any]]`
- `backend/src/hmap/api/feed.py::EventFeed.unlisten`: `def unlisten(self, q: asyncio.Queue[dict[str, Any]]) -> None`

## `backend/src/hmap/api/routers/__init__.py`

“Core API routers (Member 1).”


## `backend/src/hmap/api/routers/auth.py`

“Accounts API: register, sign in/out, profile, password change, password reset, WebSocket tickets.”

- `backend/src/hmap/api/routers/auth.py::RegisterIn`: `class RegisterIn(BaseModel)`
- `backend/src/hmap/api/routers/auth.py::LoginIn`: `class LoginIn(BaseModel)`
- `backend/src/hmap/api/routers/auth.py::ProfileIn`: `class ProfileIn(BaseModel)`
- `backend/src/hmap/api/routers/auth.py::PasswordIn`: `class PasswordIn(BaseModel)`
- `backend/src/hmap/api/routers/auth.py::ForgotIn`: `class ForgotIn(BaseModel)`
- `backend/src/hmap/api/routers/auth.py::ResetIn`: `class ResetIn(BaseModel)`
- `backend/src/hmap/api/routers/auth.py::register`: `async def register(body: RegisterIn, request: Request, response: Response, accounts: AccountsDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/auth.py::login`: `async def login(body: LoginIn, request: Request, response: Response, accounts: AccountsDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/auth.py::logout`: “Ends this session.”
- `backend/src/hmap/api/routers/auth.py::logout_all`: `async def logout_all(info: CurrentSession, request: Request, accounts: AccountsDep) -> Response`
- `backend/src/hmap/api/routers/auth.py::me`: `async def me(info: CurrentSession, request: Request, response: Response) -> dict[str, Any]`
- `backend/src/hmap/api/routers/auth.py::update_me`: `async def update_me(body: ProfileIn, info: CurrentSession, accounts: AccountsDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/auth.py::change_password`: `async def change_password(body: PasswordIn, info: CurrentSession, accounts: AccountsDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/auth.py::forgot`: `async def forgot(body: ForgotIn, request: Request, accounts: AccountsDep) -> dict[str, str]`
- `backend/src/hmap/api/routers/auth.py::reset`: `async def reset(body: ResetIn, request: Request, accounts: AccountsDep) -> Response`
- `backend/src/hmap/api/routers/auth.py::ws_ticket`: “A single-use, 60-second ticket for opening the live-event WebSocket (browsers cannot send our cookies to the API's WebSocket port through the Next.js proxy).”

## `backend/src/hmap/api/routers/projects.py`

“Projects, runs, documents, plans, approvals, tasks and artifacts (Sprint 1 item 1.15) — all owner-scoped.”

- `backend/src/hmap/api/routers/projects.py::ProjectIn`: `class ProjectIn(BaseModel)`
- `backend/src/hmap/api/routers/projects.py::ProjectPatch`: `class ProjectPatch(BaseModel)`
- `backend/src/hmap/api/routers/projects.py::RunIn`: `class RunIn(BaseModel)`
- `backend/src/hmap/api/routers/projects.py::StopIn`: `class StopIn(BaseModel)`
- `backend/src/hmap/api/routers/projects.py::ApprovalIn`: `class ApprovalIn(BaseModel)`
- `backend/src/hmap/api/routers/projects.py::TaskIn`: `class TaskIn(BaseModel)`
- `backend/src/hmap/api/routers/projects.py::CancelIn`: `class CancelIn(BaseModel)`
- `backend/src/hmap/api/routers/projects.py::owned_project`: “The project if the signed-in user owns it; 404 otherwise (unknown, deleted or someone else's).”
- `backend/src/hmap/api/routers/projects.py::create_project`: `async def create_project(body: ProjectIn, info: CurrentSession, m: ManagerDep, request: Request) -> dict[str, Any]`
- `backend/src/hmap/api/routers/projects.py::list_projects`: “The signed-in user's projects (never anyone else's).”
- `backend/src/hmap/api/routers/projects.py::get_project`: `async def get_project(project_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/projects.py::update_project`: `async def update_project(project_id: str, body: ProjectPatch, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/projects.py::delete_project`: “Stops running work, erases the project's files and removes it from the workspace (irreversible).”
- `backend/src/hmap/api/routers/projects.py::start_run`: “Run the project again with a (new) request; earlier runs stay in the history.”
- `backend/src/hmap/api/routers/projects.py::list_tasks`: `async def list_tasks(project_id: str, info: CurrentSession, m: ManagerDep, run: int | None=None) -> list[dict[str, Any]]`
- `backend/src/hmap/api/routers/projects.py::upload_document`: “Store the uploads as immutable artifacts and start ONE run with all of them (the pipeline begins with extraction).”
- `backend/src/hmap/api/routers/projects.py::submit_plan`: “Submit a TaskGraph directly (normally the pipeline does this after plan.generate).”
- `backend/src/hmap/api/routers/projects.py::stop_project`: “The human's Stop button: cancel all unfinished tasks and close the run (409 if it already finished).”
- `backend/src/hmap/api/routers/projects.py::decide_approval`: “Human-in-the-loop gate: approve or reject the submitted plan.”
- `backend/src/hmap/api/routers/projects.py::create_task`: `async def create_task(project_id: str, body: TaskIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/projects.py::get_task`: `async def get_task(task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/projects.py::cancel_task`: `async def cancel_task(task_id: str, body: CancelIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]`
- `backend/src/hmap/api/routers/projects.py::list_artifacts`: “Every stored file of the project, newest first, with the task (and run) that produced it; uploads carry the ``name`` they were uploaded as ("Part A/brief.pdf", or "request.txt" for a typed request).”
- `backend/src/hmap/api/routers/projects.py::download_artifact`: “The file's bytes, SHA-256 verified.”

## `backend/src/hmap/api/routers/system.py`

“Agents, capabilities, events, dead letters, health (Sprint 1 item 1.15) + the live WebSocket.”

- `backend/src/hmap/api/routers/system.py::ProjectAccess`: “Which project ids a user may see, cached per request/connection; learns new projects on demand.”
- `backend/src/hmap/api/routers/system.py::ProjectAccess.__init__`: `def __init__(self, manager: Manager, user_id: str) -> None`
- `backend/src/hmap/api/routers/system.py::ProjectAccess.load`: `async def load(self) -> 'ProjectAccess'`
- `backend/src/hmap/api/routers/system.py::ProjectAccess.allowed`: `async def allowed(self, project_id: str | None) -> bool`
- `backend/src/hmap/api/routers/system.py::ProjectAccess.allowed_event`: “Like :meth:`allowed`; a ``project.deleted`` event is delivered, then the project is hidden from then on.”
- `backend/src/hmap/api/routers/system.py::health`: “Public: lets the sign-in page show whether the server is up.”
- `backend/src/hmap/api/routers/system.py::agents`: `async def agents(info: CurrentSession, s: SystemDep) -> list[dict[str, Any]]`
- `backend/src/hmap/api/routers/system.py::capabilities`: “Which plug-in serves each capability, and whether it is still a stub ("no silent stubs", Sprint 10).”
- `backend/src/hmap/api/routers/system.py::llm_usage`: “Gateway mode and team key-pool counters per key fingerprint (no secrets; ``{}`` without keys or in fake mode).”
- `backend/src/hmap/api/routers/system.py::events`: “Recent events the user may see (newest ``limit``), oldest first.”
- `backend/src/hmap/api/routers/system.py::dead_letters`: “Messages that exhausted their retries, for the user's projects.”
- `backend/src/hmap/api/routers/system.py::ws_events`: “Reconnect-safe live events.”

## `backend/src/hmap/core/__init__.py`

“Platform core (owner: Member 1).”


## `backend/src/hmap/core/bus/__init__.py`

“Message bus (owner: Member 1).”


## `backend/src/hmap/core/bus/base.py`

“Message-bus interface (research §22, §26, §27).”

- `backend/src/hmap/core/bus/base.py::capability_queue`: `def capability_queue(capability: str) -> str`
- `backend/src/hmap/core/bus/base.py::Delivery`: “One delivery of a message to one consumer.”
- `backend/src/hmap/core/bus/base.py::Delivery.body`: `def body(self) -> Envelope | DomainEvent`
- `backend/src/hmap/core/bus/base.py::Delivery.attempt`: `def attempt(self) -> int`
- `backend/src/hmap/core/bus/base.py::Delivery.redelivered`: `def redelivered(self) -> bool`
- `backend/src/hmap/core/bus/base.py::Delivery.ack`: `async def ack(self) -> None`
- `backend/src/hmap/core/bus/base.py::Delivery.nack`: `async def nack(self, *, requeue: bool=True, delay_s: float | None=None) -> None`
- `backend/src/hmap/core/bus/base.py::Delivery.reject`: `async def reject(self, reason: str) -> None`
- `backend/src/hmap/core/bus/base.py::DeadLetter`: `class DeadLetter`
- `backend/src/hmap/core/bus/base.py::Subscription`: `class Subscription(Protocol)`
- `backend/src/hmap/core/bus/base.py::Subscription.cancel`: `async def cancel(self) -> None`
- `backend/src/hmap/core/bus/base.py::Bus`: `class Bus(Protocol)`
- `backend/src/hmap/core/bus/base.py::Bus.start`: `async def start(self) -> None`
- `backend/src/hmap/core/bus/base.py::Bus.close`: `async def close(self) -> None`
- `backend/src/hmap/core/bus/base.py::Bus.send_command`: “Publish a command to the capability queue (publisher-confirmed in RabbitMQ).”
- `backend/src/hmap/core/bus/base.py::Bus.publish_event`: “Publish a fact to the topic exchange.”
- `backend/src/hmap/core/bus/base.py::Bus.send_reply`: “Agent -> manager reports (task.ack/started/progress/result, error, agent.*) on queue ``hmap.manager``.”
- `backend/src/hmap/core/bus/base.py::Bus.consume_commands`: “Competing consumers on ``hmap.cap.<capability>``.”
- `backend/src/hmap/core/bus/base.py::Bus.consume_replies`: “The manager consumes ``hmap.manager``.”
- `backend/src/hmap/core/bus/base.py::Bus.subscribe_events`: “Topic pattern like ``task.*`` or ``#``.”
- `backend/src/hmap/core/bus/base.py::Bus.dead_letters`: “Inspect the DLQ (UI / operator; replay is an explicit new execution, never automatic).”
- `backend/src/hmap/core/bus/base.py::Bus.queue_depths`: `async def queue_depths(self) -> dict[str, int]`

## `backend/src/hmap/core/bus/inbox.py`

“Inbox deduplication (research §24): an in-memory ``InboxStore`` and the ``idempotent`` handler wrapper.”

- `backend/src/hmap/core/bus/inbox.py::InMemoryInboxStore`: “``InboxStore`` kept in a set.”
- `backend/src/hmap/core/bus/inbox.py::InMemoryInboxStore.__init__`: `def __init__(self) -> None`
- `backend/src/hmap/core/bus/inbox.py::InMemoryInboxStore.seen`: `async def seen(self, consumer_id: str, message_id: str) -> bool`
- `backend/src/hmap/core/bus/inbox.py::InMemoryInboxStore.record`: `async def record(self, consumer_id: str, message_id: str) -> bool`
- `backend/src/hmap/core/bus/inbox.py::dedup_key`: “The id a consumer deduplicates on: ``message_id`` (Envelope) or ``event_id`` (DomainEvent).”
- `backend/src/hmap/core/bus/inbox.py::idempotent`: “Wrap a command/event handler so each message is *processed* at most once per ``consumer_id``.”

## `backend/src/hmap/core/bus/memory.py`

“In-process ``Bus`` that mimics the RabbitMQ topology in ``base.py`` (tests, Phase A).”

- `backend/src/hmap/core/bus/memory.py::BusClosedError`: “Raised when the bus is used after ``close()``.”
- `backend/src/hmap/core/bus/memory.py::InMemoryBus`: “``base.Bus`` implemented in-process.”
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.__init__`: `def __init__(self, *, max_attempts: int=DEFAULT_MAX_ATTEMPTS, retry_delays_s: Sequence[float]=DEFAULT_RETRY_DELAYS_S) -> None`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.start`: `async def start(self) -> None`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.close`: “Cancel every consumer (unacked deliveries are requeued, in-flight handler tasks cancelled) and every pending delayed retry.”
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.send_command`: `async def send_command(self, capability: str, envelope: Envelope) -> None`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.publish_event`: `async def publish_event(self, event: DomainEvent) -> None`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.send_reply`: `async def send_reply(self, envelope: Envelope) -> None`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.consume_commands`: `async def consume_commands(self, capability: str, handler: CommandHandler, *, prefetch: int=1) -> _MemorySubscription`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.consume_replies`: `async def consume_replies(self, handler: CommandHandler, *, prefetch: int=16) -> _MemorySubscription`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.subscribe_events`: `async def subscribe_events(self, pattern: str, handler: EventHandler, *, queue: str | None=None, prefetch: int=16) -> _MemorySubscription`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.dead_letters`: `async def dead_letters(self) -> list[DeadLetter]`
- `backend/src/hmap/core/bus/memory.py::InMemoryBus.queue_depths`: “Ready (not in-flight) messages per declared queue, plus ``hmap.retry`` (waiting for a delayed retry) and ``hmap.dlq``.”

## `backend/src/hmap/core/bus/outbox.py`

“Transactional outbox (research §22): an in-memory ``OutboxStore`` and the ``OutboxPublisher`` that drains it.”

- `backend/src/hmap/core/bus/outbox.py::InMemoryOutboxStore`: “``OutboxStore`` kept in a dict.”
- `backend/src/hmap/core/bus/outbox.py::InMemoryOutboxStore.__init__`: `def __init__(self) -> None`
- `backend/src/hmap/core/bus/outbox.py::InMemoryOutboxStore.add`: `async def add(self, kind: str, body: DomainEvent | Envelope, capability: str | None=None) -> int`
- `backend/src/hmap/core/bus/outbox.py::InMemoryOutboxStore.unpublished`: `async def unpublished(self, limit: int=100) -> Sequence[OutboxRow]`
- `backend/src/hmap/core/bus/outbox.py::InMemoryOutboxStore.mark_published`: “Idempotent; the first publication time is kept.”
- `backend/src/hmap/core/bus/outbox.py::InMemoryOutboxStore.all_rows`: “Every row in ``seq`` order (tests / inspection; not part of the protocol).”
- `backend/src/hmap/core/bus/outbox.py::OutboxPublisher`: “Drains an ``OutboxStore`` to a ``Bus``.”
- `backend/src/hmap/core/bus/outbox.py::OutboxPublisher.__init__`: `def __init__(self, store: OutboxStore, bus: Bus, *, batch_size: int=100) -> None`
- `backend/src/hmap/core/bus/outbox.py::OutboxPublisher.run_once`: “Publish every unpublished row in ``seq`` order; return how many were published.”
- `backend/src/hmap/core/bus/outbox.py::OutboxPublisher.run_forever`: “Poll every ``interval_s`` (or sooner after ``notify()``) until ``stop()``.”
- `backend/src/hmap/core/bus/outbox.py::OutboxPublisher.notify`: “Hint that new rows were committed: ``run_forever`` drains now instead of at the next tick.”
- `backend/src/hmap/core/bus/outbox.py::OutboxPublisher.stop`: “Ask ``run_forever`` to return after the current drain.”

## `backend/src/hmap/core/bus/pg_stores.py`

“Postgres ``OutboxStore`` / ``InboxStore`` (Sprint 1 item 1.8; research §22, §24).”

- `backend/src/hmap/core/bus/pg_stores.py::validate_outbox_row`: “The same checks (and exception types) as ``InMemoryOutboxStore.add``.”
- `backend/src/hmap/core/bus/pg_stores.py::insert_outbox_rows`: “Append ``items`` to the outbox (+ ``events`` / ``messages`` logs) on ``conn``, which MUST be inside a transaction.”
- `backend/src/hmap/core/bus/pg_stores.py::PostgresOutboxStore`: “``OutboxStore`` on the ``outbox`` table.”
- `backend/src/hmap/core/bus/pg_stores.py::PostgresOutboxStore.__init__`: `def __init__(self, db: Database) -> None`
- `backend/src/hmap/core/bus/pg_stores.py::PostgresOutboxStore.add`: `async def add(self, kind: str, body: DomainEvent | Envelope, capability: str | None=None) -> int`
- `backend/src/hmap/core/bus/pg_stores.py::PostgresOutboxStore.unpublished`: `async def unpublished(self, limit: int=100) -> Sequence[OutboxRow]`
- `backend/src/hmap/core/bus/pg_stores.py::PostgresOutboxStore.mark_published`: “Idempotent; the first publication time is kept.”
- `backend/src/hmap/core/bus/pg_stores.py::PostgresOutboxStore.all_rows`: “Every row in ``seq`` order (tests / inspection; not part of the protocol).”
- `backend/src/hmap/core/bus/pg_stores.py::PostgresInboxStore`: “``InboxStore`` on the ``inbox`` table (PK ``(consumer_id, message_id)``).”
- `backend/src/hmap/core/bus/pg_stores.py::PostgresInboxStore.__init__`: `def __init__(self, db: Database) -> None`
- `backend/src/hmap/core/bus/pg_stores.py::PostgresInboxStore.seen`: `async def seen(self, consumer_id: str, message_id: str) -> bool`
- `backend/src/hmap/core/bus/pg_stores.py::PostgresInboxStore.record`: `async def record(self, consumer_id: str, message_id: str) -> bool`
- `backend/src/hmap/core/bus/pg_stores.py::PostgresInboxStore.count`: `async def count(self) -> int`
- `backend/src/hmap/core/bus/pg_stores.py::record_inbox`: “Insert the inbox key on ``conn`` (inside the caller's transaction, if any); False if it already existed.”

## `backend/src/hmap/core/bus/rabbitmq.py`

“RabbitMQ ``Bus`` adapter (Phase B, research §22-27).”

- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus`: “``base.Bus`` on RabbitMQ.”
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.__init__`: `def __init__(self, url: str, *, max_attempts: int=DEFAULT_MAX_ATTEMPTS, retry_delays_s: Sequence[float]=DEFAULT_RETRY_DELAYS_S, namespace: str='', connection_name: str='hmap-bus', reconnect_interval_s: float=2.0, publish_timeout_s: float=30.0) -> None`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.connection`: `def connection(self) -> AbstractRobustConnection | None`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.publish_channel`: `def publish_channel(self) -> AbstractRobustChannel | None`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.start`: `async def start(self) -> None`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.close`: “Cancel every consumer (in-flight handler tasks cancelled, unacked deliveries requeued by the broker) and close the connection.”
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.send_command`: `async def send_command(self, capability: str, envelope: Envelope) -> None`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.publish_event`: `async def publish_event(self, event: DomainEvent) -> None`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.send_reply`: `async def send_reply(self, envelope: Envelope) -> None`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.consume_commands`: `async def consume_commands(self, capability: str, handler: CommandHandler, *, prefetch: int=1) -> _RabbitSubscription`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.consume_replies`: `async def consume_replies(self, handler: CommandHandler, *, prefetch: int=16) -> _RabbitSubscription`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.subscribe_events`: `async def subscribe_events(self, pattern: str, handler: EventHandler, *, queue: str | None=None, prefetch: int=16) -> _RabbitSubscription`
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.dead_letters`: “Read (without consuming) up to ``limit`` DLQ messages, oldest first: they are fetched unacked with ``basic.get`` and returned to the queue in their original order when the inspection channel closes.”
- `backend/src/hmap/core/bus/rabbitmq.py::RabbitBus.queue_depths`: “Ready (not in-flight) messages per queue declared by this bus, plus ``hmap.retry`` (all retry queues summed: messages waiting for a delayed retry) and ``hmap.dlq``.”

## `backend/src/hmap/core/bus/stores.py`

“Outbox / inbox store interfaces (research §22, §24).”

- `backend/src/hmap/core/bus/stores.py::OutboxRow`: `class OutboxRow`
- `backend/src/hmap/core/bus/stores.py::OutboxStore`: `class OutboxStore(Protocol)`
- `backend/src/hmap/core/bus/stores.py::OutboxStore.add`: `async def add(self, kind: str, body: DomainEvent | Envelope, capability: str | None=None) -> int`
- `backend/src/hmap/core/bus/stores.py::OutboxStore.unpublished`: `async def unpublished(self, limit: int=100) -> Sequence[OutboxRow]`
- `backend/src/hmap/core/bus/stores.py::OutboxStore.mark_published`: `async def mark_published(self, seq: int) -> None`
- `backend/src/hmap/core/bus/stores.py::InboxStore`: `class InboxStore(Protocol)`
- `backend/src/hmap/core/bus/stores.py::InboxStore.seen`: `async def seen(self, consumer_id: str, message_id: str) -> bool`
- `backend/src/hmap/core/bus/stores.py::InboxStore.record`: “Insert; return False if the pair already existed (duplicate delivery).”

## `backend/src/hmap/core/bus/topics.py`

“AMQP topic-pattern matching (RabbitMQ topic-exchange semantics), shared by the in-memory bus and by anything that filters events in-process (e.g.”

- `backend/src/hmap/core/bus/topics.py::validate_pattern`: “Raise ``ValueError`` for an empty pattern or one with empty words (``a..b``).”
- `backend/src/hmap/core/bus/topics.py::topic_matches`: “True if ``routing_key`` matches the topic ``pattern``.”

## `backend/src/hmap/core/config.py`

“Settings read from the environment (see /.env.example).”

- `backend/src/hmap/core/config.py::read_env_file`: “Minimal reader for the local ``.env`` (KEY=VALUE lines, ``#`` comments, optional ``export`` and quotes).”
- `backend/src/hmap/core/config.py::env_file_values`: “Values from ``<repo>/.env`` (or ``HMAP_ENV_FILE``; ``none`` disables it — the test suite does).”
- `backend/src/hmap/core/config.py::parse_role_map`: “``"reasoner=qwen3.5:9b,embed=nomic-embed-text"`` -> ``{"reasoner": "qwen3.5:9b", ...}``.”
- `backend/src/hmap/core/config.py::parse_key_list`: “``"k1, k2,,"`` -> ``["k1", "k2"]`` (blanks ignored, duplicates dropped keeping the first).”
- `backend/src/hmap/core/config.py::parse_cloud_role_map`: “``"coder=groq:<model>|gemini:<model>,reasoner=gemini:<model>"`` -> ``{"coder": [("groq", m), ("gemini", m)], ...}``; ``none``/``off``/``local`` -> ``{}`` (every role local).”
- `backend/src/hmap/core/config.py::Settings`: Defines a Pydantic model holding configuration values loaded from environment variables.
- `backend/src/hmap/core/config.py::Settings.from_env`: Creates a Settings instance from a given env dict or os.environ if none provided.
- `backend/src/hmap/core/config.py::Settings.cloud_keys`: “The raw keys for ``provider`` (``groq`` | ``gemini`` | legacy ``cloud``).”
- `backend/src/hmap/core/config.py::Settings.cloud_base_url_for`: Returns the base URL for a specified cloud provider, or None if not configured.
- `backend/src/hmap/core/config.py::Settings.enabled_plugins`: “``None`` means every discovered plug-in.”

## `backend/src/hmap/core/contracts/__init__.py`

“Cross-process contracts (owner: Member 1).”


## `backend/src/hmap/core/contracts/capabilities.py`

“Capability names (routing keys for per-capability queues) and the descriptor agents register with.”

- `backend/src/hmap/core/contracts/capabilities.py::CapabilityDescriptor`: “Research §20: matched by name/version first, then load and health.”

## `backend/src/hmap/core/contracts/common.py`

“Shared building blocks for every contract.”

- `backend/src/hmap/core/contracts/common.py::utcnow`: `def utcnow() -> datetime`
- `backend/src/hmap/core/contracts/common.py::Contract`: “Base class of all contracts: unknown fields ignored (forward-compatible), enums serialised as values.”
- `backend/src/hmap/core/contracts/common.py::Priority`: `class Priority(StrEnum)`
- `backend/src/hmap/core/contracts/common.py::AgentRef`: `class AgentRef(Contract)`
- `backend/src/hmap/core/contracts/common.py::ContextRef`: “Pinned immutable context snapshot ``CTX-42@3`` (research §14).”
- `backend/src/hmap/core/contracts/common.py::ArtifactRef`: “Immutable, content-addressed artifact reference (research §15).”
- `backend/src/hmap/core/contracts/common.py::parse_version`: `def parse_version(version: str) -> tuple[int, int]`
- `backend/src/hmap/core/contracts/common.py::is_compatible`: “Same major as something we support.”
- `backend/src/hmap/core/contracts/common.py::ensure_compatible`: `def ensure_compatible(version: str) -> None`
- `backend/src/hmap/core/contracts/common.py::negotiate`: “Highest version both sides support (manager vs agent registration), or None -> SCHEMA_UNSUPPORTED.”

## `backend/src/hmap/core/contracts/domain.py`

“Cross-sprint "handoff" contracts (doc 01 §4).”

- `backend/src/hmap/core/contracts/domain.py::SourceRef`: “Where an item came from in the source document (traceability, Sprint 2).”
- `backend/src/hmap/core/contracts/domain.py::Requirement`: Defines a requirement with id, text, type, priority, source reference, and confidence.
- `backend/src/hmap/core/contracts/domain.py::Constraint`: Specifies a constraint with id, text, kind, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::Deliverable`: Represents a deliverable with id, name, format, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::RubricLevel`: Describes a rubric level with label, description, and optional marks.
- `backend/src/hmap/core/contracts/domain.py::EvaluationCriterion`: Defines an evaluation criterion with id, criterion text, max marks, rubric levels, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::RequirementSet`: Aggregates project requirements, constraints, deliverables, evaluation criteria, and validates uniqueness and mark totals.
- `backend/src/hmap/core/contracts/domain.py::PlanTask`: Models a plan task with id, title, description, capability, requirement IDs, acceptance criteria, dependencies, priority, effort, phase, and research questions.
- `backend/src/hmap/core/contracts/domain.py::Phase`: Defines a phase with id, name, task IDs, and optional parent phase.
- `backend/src/hmap/core/contracts/domain.py::Milestone`: Represents a milestone with name and associated task IDs.
- `backend/src/hmap/core/contracts/domain.py::Roadmap`: Contains phases, milestones, and optional markdown description.
- `backend/src/hmap/core/contracts/domain.py::TaskGraph`: Encapsulates a project task graph with tasks, roadmap, coverage matrix, and computed edges.
- `backend/src/hmap/core/contracts/domain.py::TaskGraph.edges`: “``[{from, to}]`` derived from ``depends_on`` (single source of truth).”
- `backend/src/hmap/core/contracts/domain.py::TaskGraph.task`: Retrieves a task by its ID from the task graph.
- `backend/src/hmap/core/contracts/domain.py::Issue`: Describes an issue with id, title, description, severity, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::Critique`: Represents a critique with id, title, description, severity, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::RefinementSpec`: Specifies a refinement with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::RefinementIteration`: Defines a refinement iteration with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::RefinementTrace`: Tracks a refinement trace with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::ResearchBudget`: Outlines a research budget with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::ResearchBrief`: Provides a research brief with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::Evidence`: Captures evidence with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::Claim`: States a claim with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::Source`: Represents a source with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::SubQuestion`: “One node of the research plan (Sprint 5): a brief question split into answerable parts.”
- `backend/src/hmap/core/contracts/domain.py::ResearchReport`: Details a research report with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::ClaimVerdict`: Records a claim verdict with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::VerificationReport`: Presents a verification report with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::VerificationReport.summary`: Returns a dictionary summarizing verification results as integer counts.
- `backend/src/hmap/core/contracts/domain.py::CommandRun`: Logs a command execution with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::CodeChangeSet`: Describes a code change set with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::StageResult`: Captures a stage result with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::TestFailure`: Represents a test failure with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::TestReport`: Provides a test report with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::AccuracyReport`: Details an accuracy report with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::DocBundle`: Encapsulates a document bundle with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::RequirementResult`: Records a requirement result with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::RubricScore`: Captures a rubric score with id, title, description, and optional source reference.
- `backend/src/hmap/core/contracts/domain.py::ReviewFailure`: `class ReviewFailure(Contract)`
- `backend/src/hmap/core/contracts/domain.py::RevisionPlan`: `class RevisionPlan(Contract)`

## `backend/src/hmap/core/contracts/envelope.py`

“The common message envelope (research §7) with typed payload validation and version checks.”

- `backend/src/hmap/core/contracts/envelope.py::Envelope`: `class Envelope(Contract)`
- `backend/src/hmap/core/contracts/envelope.py::Envelope.typed_payload`: `def typed_payload(self) -> Contract`
- `backend/src/hmap/core/contracts/envelope.py::register_signer`: “Sprint 6 (Member 6): ``hmap.core.policy.install`` registers the process's signer; every envelope built by :func:`make_envelope` is then signed (``auth``).”
- `backend/src/hmap/core/contracts/envelope.py::make_envelope`: “Build a validated envelope from a payload model; the message_type is derived from the payload class.”
- `backend/src/hmap/core/contracts/envelope.py::parse_envelope`: “Validate an incoming message.”

## `backend/src/hmap/core/contracts/events.py`

“Domain events (research §10): facts written to the outbox in the same transaction as the state change.”

- `backend/src/hmap/core/contracts/events.py::EventType`: `class EventType(StrEnum)`
- `backend/src/hmap/core/contracts/events.py::DomainEvent`: `class DomainEvent(Contract)`
- `backend/src/hmap/core/contracts/events.py::DomainEvent.model_post_init`: `def model_post_init(self, __context: Any) -> None`

## `backend/src/hmap/core/contracts/examples.py`

“One valid, realistic example of every contract.”

- `backend/src/hmap/core/contracts/examples.py::artifact`: `def artifact(artifact_id: str='ART-91', artifact_type: str='json', *, version: int=1, media_type: str='application/json', created_by: str='stub-agent') -> ArtifactRef`
- `backend/src/hmap/core/contracts/examples.py::all_examples`: `def all_examples() -> dict[str, Any]`

## `backend/src/hmap/core/contracts/export.py`

“Export JSON Schemas (draft 2020-12) for every contract.”

- `backend/src/hmap/core/contracts/export.py::schema_for`: `def schema_for(model: type[Contract], title: str) -> dict[str, Any]`
- `backend/src/hmap/core/contracts/export.py::all_schemas`: `def all_schemas() -> dict[str, dict[str, Any]]`
- `backend/src/hmap/core/contracts/export.py::export`: `def export(out_dir: Path=DEFAULT_OUT) -> list[Path]`

## `backend/src/hmap/core/contracts/messages.py`

“Payloads of the 15 message types (research §8).”

- `backend/src/hmap/core/contracts/messages.py::TaskAssign`: `class TaskAssign(Contract)`
- `backend/src/hmap/core/contracts/messages.py::TaskAck`: `class TaskAck(Contract)`
- `backend/src/hmap/core/contracts/messages.py::TaskStarted`: `class TaskStarted(Contract)`
- `backend/src/hmap/core/contracts/messages.py::TaskProgress`: `class TaskProgress(Contract)`
- `backend/src/hmap/core/contracts/messages.py::TaskResult`: `class TaskResult(Contract)`
- `backend/src/hmap/core/contracts/messages.py::Feedback`: `class Feedback(Contract)`
- `backend/src/hmap/core/contracts/messages.py::RevisionRequest`: `class RevisionRequest(Contract)`
- `backend/src/hmap/core/contracts/messages.py::ContextRequest`: `class ContextRequest(Contract)`
- `backend/src/hmap/core/contracts/messages.py::ErrorPayload`: `class ErrorPayload(Contract)`
- `backend/src/hmap/core/contracts/messages.py::RetryRequest`: `class RetryRequest(Contract)`
- `backend/src/hmap/core/contracts/messages.py::TaskCancel`: `class TaskCancel(Contract)`
- `backend/src/hmap/core/contracts/messages.py::TaskCompleted`: `class TaskCompleted(Contract)`
- `backend/src/hmap/core/contracts/messages.py::AgentHeartbeat`: `class AgentHeartbeat(Contract)`
- `backend/src/hmap/core/contracts/messages.py::AgentRegister`: `class AgentRegister(Contract)`
- `backend/src/hmap/core/contracts/messages.py::AgentDeregister`: `class AgentDeregister(Contract)`

## `backend/src/hmap/core/contracts/states.py`

“State enums shared by Manager, registry, API and UI.”

- `backend/src/hmap/core/contracts/states.py::TaskState`: “Logical task lifecycle (research §9) + NEEDS_REVISION (review loop, Sprint 10).”
- `backend/src/hmap/core/contracts/states.py::ExecutionStatus`: “One attempt at a task (research §18: a retry is a new execution; the old one is superseded).”
- `backend/src/hmap/core/contracts/states.py::AgentState`: “Advertised agent lifecycle (research §16, §21).”
- `backend/src/hmap/core/contracts/states.py::ProjectState`: “Whole-project pipeline, including the human plan-approval gate (Sprint 1 item 1.13, Sprint 3).”

## `backend/src/hmap/core/errors.py`

“Error taxonomy (research §25) and the retry classifier (§23).”

- `backend/src/hmap/core/errors.py::ErrorCode`: Defines enumeration of error taxonomy codes.
- `backend/src/hmap/core/errors.py::is_retryable`: Returns True if code is in RETRYABLE set, else False.
- `backend/src/hmap/core/errors.py::HmapError`: “Base error carrying a taxonomy code; ``retryable`` defaults from the code.”
- `backend/src/hmap/core/errors.py::HmapError.__init__`: Initializes error with message, optional code, retryable flag, and details.
- `backend/src/hmap/core/errors.py::HmapError.to_dict`: Converts error to dictionary with code, message, retryable, and details.
- `backend/src/hmap/core/errors.py::InvalidMessage`: Error subclass for INVALID_MESSAGE code.
- `backend/src/hmap/core/errors.py::SchemaUnsupported`: Error subclass for SCHEMA_UNSUPPORTED code.
- `backend/src/hmap/core/errors.py::ArtifactIntegrityError`: Error subclass for ARTIFACT_INTEGRITY code.
- `backend/src/hmap/core/errors.py::ArtifactConflict`: Error subclass for ARTIFACT_CONFLICT code.
- `backend/src/hmap/core/errors.py::TransientError`: Error subclass for TOOL_TRANSIENT code.
- `backend/src/hmap/core/errors.py::ModelTransientError`: Error subclass for MODEL_TRANSIENT code.
- `backend/src/hmap/core/errors.py::AuthorizationError`: Error subclass for AUTHORIZATION code.
- `backend/src/hmap/core/errors.py::Cancelled`: Error subclass for CANCELLED code.
- `backend/src/hmap/core/errors.py::classify`: “Map an arbitrary exception to the taxonomy so the retry scheduler can decide.”

## `backend/src/hmap/core/ids.py`

“Identifier helpers.”

- `backend/src/hmap/core/ids.py::new_uuid`: `def new_uuid() -> str`
- `backend/src/hmap/core/ids.py::new_ulid`: “26-character Crockford base32 ULID: 48-bit millisecond timestamp + 80 random bits.”
- `backend/src/hmap/core/ids.py::new_project_id`: `def new_project_id() -> str`
- `backend/src/hmap/core/ids.py::new_task_id`: `def new_task_id() -> str`
- `backend/src/hmap/core/ids.py::new_execution_id`: `def new_execution_id() -> str`
- `backend/src/hmap/core/ids.py::new_artifact_id`: `def new_artifact_id() -> str`
- `backend/src/hmap/core/ids.py::new_context_id`: `def new_context_id() -> str`
- `backend/src/hmap/core/ids.py::new_agent_instance_id`: `def new_agent_instance_id(agent_name: str) -> str`

## `backend/src/hmap/core/llm/__init__.py`

“LLM gateway (doc 01 §4, doc 02 §2).”


## `backend/src/hmap/core/llm/base.py`

“LLM gateway interface (doc 01 §4 "LLM Gateway contract", doc 02 §2).”

- `backend/src/hmap/core/llm/base.py::Message`: `class Message(Contract)`
- `backend/src/hmap/core/llm/base.py::LLMUsage`: `class LLMUsage(Contract)`
- `backend/src/hmap/core/llm/base.py::LLMResponse`: `class LLMResponse(Contract)`
- `backend/src/hmap/core/llm/base.py::ClassifyQuestion`: “A typed decision for ``classify`` (bool / choice / score).”
- `backend/src/hmap/core/llm/base.py::ClassifyAnswer`: `class ClassifyAnswer(Contract)`
- `backend/src/hmap/core/llm/base.py::LLMClient`: `class LLMClient(Protocol)`
- `backend/src/hmap/core/llm/base.py::LLMClient.generate`: “With ``schema``: JSON-schema constrained output, validated, up to 2 repair retries; ``parsed`` is set.”
- `backend/src/hmap/core/llm/base.py::LLMClient.embed`: `async def embed(self, texts: list[str]) -> list[list[float]]`
- `backend/src/hmap/core/llm/base.py::LLMClient.classify`: “Short typed decisions (doc 02 §2.2 ``classify`` role).”
- `backend/src/hmap/core/llm/base.py::LLMClient.read_images`: “Ask a vision model about PNG/JPEG ``images`` (role ``vision``, e.g.”

## `backend/src/hmap/core/llm/cache.py`

“Record/replay cache (doc 02 §2.4).”

- `backend/src/hmap/core/llm/cache.py::validate_plugin_name`: “Plug-in names become a cache folder, so they must be one safe path segment.”
- `backend/src/hmap/core/llm/cache.py::canonical_json`: `def canonical_json(obj: Any) -> str`
- `backend/src/hmap/core/llm/cache.py::key_ingredients`: “Everything that identifies a generate request — and nothing else (no preamble, no model name).”
- `backend/src/hmap/core/llm/cache.py::embed_key_ingredients`: `def embed_key_ingredients(*, plugin: str, texts: Sequence[str]) -> dict[str, Any]`
- `backend/src/hmap/core/llm/cache.py::cache_key`: `def cache_key(ingredients: dict[str, Any]) -> str`
- `backend/src/hmap/core/llm/cache.py::describe_ingredients`: `def describe_ingredients(ingredients: dict[str, Any]) -> list[str]`
- `backend/src/hmap/core/llm/cache.py::diff_ingredients`: “Names of the ingredients that differ (messages are compared per index).”
- `backend/src/hmap/core/llm/cache.py::ReplayCache`: `class ReplayCache`
- `backend/src/hmap/core/llm/cache.py::ReplayCache.__init__`: `def __init__(self, root: Path | str) -> None`
- `backend/src/hmap/core/llm/cache.py::ReplayCache.path_for`: `def path_for(self, plugin: str, key: str) -> Path`
- `backend/src/hmap/core/llm/cache.py::ReplayCache.load`: `def load(self, plugin: str, key: str) -> dict[str, Any] | None`
- `backend/src/hmap/core/llm/cache.py::ReplayCache.save`: “Atomic write (temp file + rename) so a crash never leaves half a JSON file.”
- `backend/src/hmap/core/llm/cache.py::ReplayCache.closest`: “The recorded entry (same plug-in, same role) whose ingredients differ in the fewest places.”
- `backend/src/hmap/core/llm/cache.py::ReplayCache.describe_miss`: `def describe_miss(self, plugin: str, key: str, ingredients: dict[str, Any], *, prompt_version: str, recorded_version: str | None=None) -> str`

## `backend/src/hmap/core/llm/classify.py`

“``classify`` as one schema-constrained ``generate`` (Sprint 1, doc 02 §2.2).”

- `backend/src/hmap/core/llm/classify.py::options_for`: `def options_for(question: ClassifyQuestion) -> list[str]`
- `backend/src/hmap/core/llm/classify.py::build_schema`: `def build_schema(questions: list[ClassifyQuestion]) -> type[BaseModel]`
- `backend/src/hmap/core/llm/classify.py::build_messages`: `def build_messages(state: str, questions: list[ClassifyQuestion]) -> list[Message]`
- `backend/src/hmap/core/llm/classify.py::to_answers`: `def to_answers(parsed: BaseModel, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]`

## `backend/src/hmap/core/llm/cloud.py`

“Cloud routing over the team key pool (doc 02 §2.5, item 1.14b).”

- `backend/src/hmap/core/llm/cloud.py::CloudBackend`: “One cloud provider: a keyless OpenAI-compatible client plus its key pool.”
- `backend/src/hmap/core/llm/cloud.py::CloudBackend.name`: `def name(self) -> str`
- `backend/src/hmap/core/llm/cloud.py::CloudRouter`: `class CloudRouter`
- `backend/src/hmap/core/llm/cloud.py::CloudRouter.__init__`: “``role_map`` routes naming a provider without a backend are dropped (no keys for it).”
- `backend/src/hmap/core/llm/cloud.py::CloudRouter.from_settings`: “A router for the providers named in ``settings.cloud_role_map`` that have keys; ``None`` when no mapped role can reach any keyed provider (then nothing is constructed and every call stays local).”
- `backend/src/hmap/core/llm/cloud.py::CloudRouter.handles`: `def handles(self, role: str) -> bool`
- `backend/src/hmap/core/llm/cloud.py::CloudRouter.chat`: “Answer from the cloud, or ``None`` when every route/key is cooling, disabled or failing.”
- `backend/src/hmap/core/llm/cloud.py::CloudRouter.usage`: “Per key fingerprint: provider, requests, ok, tokens in/out, rate_limited, auth_errors, errors, disabled, cooling_for_s.”
- `backend/src/hmap/core/llm/cloud.py::CloudRouter.aclose`: `async def aclose(self) -> None`

## `backend/src/hmap/core/llm/errors.py`

“LLM-specific errors.”

- `backend/src/hmap/core/llm/errors.py::LLMError`: “Non-retryable LLM gateway problem (configuration, provider rejection, cache miss).”
- `backend/src/hmap/core/llm/errors.py::LLMConfigError`: “Bad or missing configuration, e.g.”
- `backend/src/hmap/core/llm/errors.py::LLMProviderError`: “The provider rejected the request (4xx other than rate limiting): unknown model, bad request, auth.”
- `backend/src/hmap/core/llm/errors.py::ReplayMissError`: “``replay`` mode found no cached answer for the request; the message lists the key ingredients.”
- `backend/src/hmap/core/llm/errors.py::StructuredOutputError`: “The model did not produce schema-valid JSON after the repair retries.”
- `backend/src/hmap/core/llm/errors.py::FakeLLMError`: “``FakeLLM`` has no scripted answer for a call.”
- `backend/src/hmap/core/llm/errors.py::VisionUnavailable`: “No vision model can answer right now (no ``vision`` cloud route, cloud not allowed, or every key failed).”
- `backend/src/hmap/core/llm/errors.py::CloudRateLimited`: “Cloud provider kept answering 429 after bounded retries (the gateway then falls back to local).”

## `backend/src/hmap/core/llm/fake.py`

“``FakeLLM``: a deterministic, scripted ``LLMClient`` for unit tests (doc 02 §2.4 mode ``fake``).”

- `backend/src/hmap/core/llm/fake.py::FakeCall`: `class FakeCall`
- `backend/src/hmap/core/llm/fake.py::FakeLLM`: `class FakeLLM`
- `backend/src/hmap/core/llm/fake.py::FakeLLM.on_role`: `def on_role(self, role: str, *replies: Reply) -> 'FakeLLM'`
- `backend/src/hmap/core/llm/fake.py::FakeLLM.on_schema`: `def on_schema(self, schema: type[BaseModel], *replies: Reply) -> 'FakeLLM'`
- `backend/src/hmap/core/llm/fake.py::FakeLLM.on_vision`: “Script ``read_images`` answers (str, or a callable taking ``(prompt, images)``).”
- `backend/src/hmap/core/llm/fake.py::FakeLLM.on_classify`: `def on_classify(self, name: str, answer: str) -> 'FakeLLM'`
- `backend/src/hmap/core/llm/fake.py::FakeLLM.reset`: `def reset(self) -> None`
- `backend/src/hmap/core/llm/fake.py::FakeLLM.generate`: `async def generate(self, role: Role, messages: list[Message] | list[dict[str, str]], *, schema: type[T] | None=None, max_tokens: int=1024, temperature: float=0.2, think: bool=False, seed: int | None=None) -> LLMResponse`
- `backend/src/hmap/core/llm/fake.py::FakeLLM.embed`: `async def embed(self, texts: list[str]) -> list[list[float]]`
- `backend/src/hmap/core/llm/fake.py::FakeLLM.classify`: `async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]`
- `backend/src/hmap/core/llm/fake.py::FakeLLM.read_images`: `async def read_images(self, prompt: str, images: list[bytes], *, max_tokens: int=4096) -> LLMResponse`
- `backend/src/hmap/core/llm/fake.py::fake_vector`: “Deterministic pseudo-embedding in [-1, 1] derived from SHA-256 of the text.”

## `backend/src/hmap/core/llm/gateway.py`

“The LLM gateway (doc 01 §4, doc 02 §2): the only ``LLMClient`` implementation agents get.”

- `backend/src/hmap/core/llm/gateway.py::resolve_model`: “``role`` -> model via ``HMAP_ROLE_MAP``; missing role -> ``reasoner`` (``classify`` -> ``fast`` first).”
- `backend/src/hmap/core/llm/gateway.py::normalize_messages`: `def normalize_messages(messages: list[Message] | list[dict[str, str]]) -> list[Message]`
- `backend/src/hmap/core/llm/gateway.py::encode_embeddings`: “Replay-cache form of embeddings: float16, little-endian, base64 per vector.”
- `backend/src/hmap/core/llm/gateway.py::decode_embeddings`: “Both cache forms: ``embeddings`` (JSON numbers, older recordings) and ``embeddings_b64`` (float16).”
- `backend/src/hmap/core/llm/gateway.py::Gateway`: `class Gateway`
- `backend/src/hmap/core/llm/gateway.py::Gateway.__init__`: “``cloud`` (deprecated legacy lane) defaults to an :class:`OpenAICompatProvider` when ``cloud_base_url`` and ``cloud_api_key`` are both set.”
- `backend/src/hmap/core/llm/gateway.py::Gateway.for_plugin`: “A client bound to plug-in ``name`` (its cache folder); providers, cache and semaphore are shared.”
- `backend/src/hmap/core/llm/gateway.py::Gateway.local_only`: “The same client, but never the cloud (a local-only project); providers, cache and semaphore are shared.”
- `backend/src/hmap/core/llm/gateway.py::Gateway.mode`: `def mode(self) -> LLMMode`
- `backend/src/hmap/core/llm/gateway.py::Gateway.cache`: `def cache(self) -> ReplayCache`
- `backend/src/hmap/core/llm/gateway.py::Gateway.fake`: `def fake(self) -> FakeLLM | None`
- `backend/src/hmap/core/llm/gateway.py::Gateway.model_for`: `def model_for(self, role: str) -> str`
- `backend/src/hmap/core/llm/gateway.py::Gateway.cloud_router`: `def cloud_router(self) -> CloudRouter | None`
- `backend/src/hmap/core/llm/gateway.py::Gateway.cloud_usage`: “Per key fingerprint counters of the team key pool (for ``/api/llm/usage``); ``{}`` without a pool.”
- `backend/src/hmap/core/llm/gateway.py::Gateway.aclose`: `async def aclose(self) -> None`
- `backend/src/hmap/core/llm/gateway.py::Gateway.generate`: `async def generate(self, role: Role, messages: list[Message] | list[dict[str, str]], *, schema: type[T] | None=None, max_tokens: int=1024, temperature: float=0.2, think: bool=False, seed: int | None=None, allow_cloud: bool | None=None) -> LLMResponse`
- `backend/src/hmap/core/llm/gateway.py::Gateway.embed`: `async def embed(self, texts: list[str]) -> list[list[float]]`
- `backend/src/hmap/core/llm/gateway.py::Gateway.classify`: `async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]`
- `backend/src/hmap/core/llm/gateway.py::Gateway.read_images`: `async def read_images(self, prompt: str, images: list[bytes], *, max_tokens: int=4096) -> LLMResponse`
- `backend/src/hmap/core/llm/gateway.py::build_llm`: “Convenience: a gateway for ``settings`` (default: from the environment) bound to ``plugin``.”

## `backend/src/hmap/core/llm/key_pool.py`

“Per-provider pool of contributed API keys (doc 02 §2.5, item 1.14b).”

- `backend/src/hmap/core/llm/key_pool.py::fingerprint`: “``provider:<8 hex>`` — a short SHA-256 prefix of the key.”
- `backend/src/hmap/core/llm/key_pool.py::KeyLease`: “A key handed out for one request.”
- `backend/src/hmap/core/llm/key_pool.py::KeyLease.__init__`: `def __init__(self, provider: str, key: str, fp: str) -> None`
- `backend/src/hmap/core/llm/key_pool.py::KeyLease.secret`: `def secret(self) -> str`
- `backend/src/hmap/core/llm/key_pool.py::KeyState`: “Mutable per-key state + counters (no secret in here).”
- `backend/src/hmap/core/llm/key_pool.py::KeyState.snapshot`: `def snapshot(self, now: float) -> dict[str, Any]`
- `backend/src/hmap/core/llm/key_pool.py::KeyPool`: “Round-robin pool for one provider.”
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.__init__`: `def __init__(self, provider: str, keys: Sequence[str], *, clock: Callable[[], float]=time.monotonic, default_cooldown_s: float=DEFAULT_COOLDOWN_S, max_default_cooldown_s: float=MAX_DEFAULT_COOLDOWN_S) -> None`
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.fingerprints`: `def fingerprints(self) -> list[str]`
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.acquire`: “The next usable key (round-robin), skipping disabled, cooling and ``exclude``d fingerprints; ``None`` when no key is usable right now.”
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.available`: `def available(self) -> int`
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.mark_ok`: `def mark_ok(self, fp: str, *, input_tokens: int=0, output_tokens: int=0) -> None`
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.mark_rate_limited`: “Cool the key for ``retry_after`` seconds, or ``default * 2**strikes`` (capped) when absent.”
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.mark_auth_error`: “Disable the key until restart.”
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.mark_error`: `def mark_error(self, fp: str) -> None`
- `backend/src/hmap/core/llm/key_pool.py::KeyPool.usage`: `def usage(self) -> dict[str, dict[str, Any]]`

## `backend/src/hmap/core/llm/providers/__init__.py`

“LLM providers used by the gateway: local Ollama and an optional OpenAI-compatible cloud API.”


## `backend/src/hmap/core/llm/providers/base.py`

“Provider-level interface (below the gateway).”

- `backend/src/hmap/core/llm/providers/base.py::ChatRequest`: “One raw chat completion.”
- `backend/src/hmap/core/llm/providers/base.py::ChatProvider`: `class ChatProvider(Protocol)`
- `backend/src/hmap/core/llm/providers/base.py::ChatProvider.chat`: “Return text + usage.”
- `backend/src/hmap/core/llm/providers/base.py::EmbedProvider`: `class EmbedProvider(Protocol)`
- `backend/src/hmap/core/llm/providers/base.py::EmbedProvider.embed`: `async def embed(self, model: str, texts: list[str]) -> list[list[float]]`
- `backend/src/hmap/core/llm/providers/base.py::LocalProvider`: “A provider that can both chat and embed (Ollama).”

## `backend/src/hmap/core/llm/providers/ollama.py`

“Ollama provider (doc 02 §2.1): native ``/api/chat`` and ``/api/embed``, thinking off by default, JSON-Schema ``format``, and the heavy-model unload guard (``keep_alive: 0`` on the previous heavy model before switching).”

- `backend/src/hmap/core/llm/providers/ollama.py::default_is_heavy`: “Default heaviness test: every model except embedding models (name contains ``embed``).”
- `backend/src/hmap/core/llm/providers/ollama.py::OllamaProvider`: `class OllamaProvider`
- `backend/src/hmap/core/llm/providers/ollama.py::OllamaProvider.__init__`: “``keep_alive`` / ``num_ctx`` are sent only when set (else Ollama's server defaults apply).”
- `backend/src/hmap/core/llm/providers/ollama.py::OllamaProvider.aclose`: `async def aclose(self) -> None`
- `backend/src/hmap/core/llm/providers/ollama.py::OllamaProvider.chat_body`: `def chat_body(self, request: ChatRequest, *, think: bool=True) -> dict[str, Any]`
- `backend/src/hmap/core/llm/providers/ollama.py::OllamaProvider.chat`: `async def chat(self, request: ChatRequest) -> LLMResponse`
- `backend/src/hmap/core/llm/providers/ollama.py::OllamaProvider.embed`: `async def embed(self, model: str, texts: list[str]) -> list[list[float]]`

## `backend/src/hmap/core/llm/providers/openai_compat.py`

“OpenAI-compatible cloud provider, e.g.”

- `backend/src/hmap/core/llm/providers/openai_compat.py::chat_completions_url`: “``https://api.groq.com/openai/v1`` -> ``.../openai/v1/chat/completions``; ``https://generativelanguage.googleapis.com/v1beta/openai`` -> ``.../v1beta/openai/chat/completions``; an unversioned host (``https://h``) -> ``https://h/v1/chat/comp”
- `backend/src/hmap/core/llm/providers/openai_compat.py::parse_retry_after`: “``retry-after`` as seconds (``"2"``, ``"1.5"``) or an HTTP date; ``None`` when absent/unparseable.”
- `backend/src/hmap/core/llm/providers/openai_compat.py::image_mime`: `def image_mime(b64: str) -> str`
- `backend/src/hmap/core/llm/providers/openai_compat.py::with_images`: “OpenAI-style vision content parts: the last user message becomes ``[text, image_url...]`` (data URIs).”
- `backend/src/hmap/core/llm/providers/openai_compat.py::OpenAICompatProvider`: `class OpenAICompatProvider`
- `backend/src/hmap/core/llm/providers/openai_compat.py::OpenAICompatProvider.__init__`: “``model_map``: role -> cloud model name (cloud names differ from Ollama tags); falls back to ``default_model``, then to the locally resolved name.”
- `backend/src/hmap/core/llm/providers/openai_compat.py::OpenAICompatProvider.aclose`: `async def aclose(self) -> None`
- `backend/src/hmap/core/llm/providers/openai_compat.py::OpenAICompatProvider.model_for`: `def model_for(self, request: ChatRequest) -> str`
- `backend/src/hmap/core/llm/providers/openai_compat.py::OpenAICompatProvider.chat_body`: `def chat_body(self, request: ChatRequest, model: str | None=None) -> dict[str, Any]`
- `backend/src/hmap/core/llm/providers/openai_compat.py::OpenAICompatProvider.send`: “ONE request with ``api_key`` for ``model``; no retries, no sleeping, no logging (the caller logs).”
- `backend/src/hmap/core/llm/providers/openai_compat.py::OpenAICompatProvider.chat`: “Deprecated single-key path (legacy ``HMAP_CLOUD_*``): bounded 429 retries honouring ``retry-after``.”

## `backend/src/hmap/core/llm/structured.py`

“Structured output helper (doc 02 §2.3): schema -> ``format`` -> pydantic validation -> up to 2 repair retries.”

- `backend/src/hmap/core/llm/structured.py::extract_json`: “Best-effort: drop ``<think>`` blocks and code fences, then trim to the outermost JSON object/array.”
- `backend/src/hmap/core/llm/structured.py::validate_output`: “Raise ``ValidationError`` (invalid JSON included) or return the instance.”
- `backend/src/hmap/core/llm/structured.py::inline_refs`: “Inline local ``#/$defs/...`` references so small models' grammars get a flat schema.”
- `backend/src/hmap/core/llm/structured.py::generate_structured`: “Run ``call`` until its text validates against ``schema`` (1 + ``max_repairs`` attempts).”

## `backend/src/hmap/core/plugins.py`

“Plug-in declaration and discovery (Sprint 1 §3.5).”

- `backend/src/hmap/core/plugins.py::ProjectStopped`: “Raised by ``create_task`` / ``submit_graph`` when a human stopped the project.”
- `backend/src/hmap/core/plugins.py::ManagerHandle`: “What a Manager hook may do.”
- `backend/src/hmap/core/plugins.py::ManagerHandle.create_task`: “Create a READY task (or CREATED until ``depends_on`` complete); returns task_id.”
- `backend/src/hmap/core/plugins.py::ManagerHandle.submit_graph`: “Hand a TaskGraph to the executor; with approval required the project waits in AWAITING_APPROVAL.”
- `backend/src/hmap/core/plugins.py::ManagerHandle.replace_graph`: “Replan (Sprint 3): swap the current plan for a newer version, keeping completed / running plan tasks whose ids are still in ``graph``; returns plan task id -> task id.”
- `backend/src/hmap/core/plugins.py::ManagerHandle.emit`: “Publish a domain event through the outbox.”
- `backend/src/hmap/core/plugins.py::ManagerHandle.get_task`: `async def get_task(self, task_id: str) -> dict[str, Any]`
- `backend/src/hmap/core/plugins.py::RefineAdapter`: “Refinement hook for an existing capability (Sprint 4, plan D1).”
- `backend/src/hmap/core/plugins.py::Hook`: `class Hook`
- `backend/src/hmap/core/plugins.py::hook`: `def hook(event_type: str, *, capability: str | None=None) -> Callable[[HookFn], Hook]`
- `backend/src/hmap/core/plugins.py::Plugin`: `class Plugin`

## `backend/src/hmap/core/policy.py`

“Basic security layer (Sprint 6 item 6.20, owner Member 6; was Sprint 1 item 1.18) and token lifecycle (6.15).”

- `backend/src/hmap/core/policy.py::fingerprint`: “A short, non-reversible id for logs (never log a token or secret).”
- `backend/src/hmap/core/policy.py::Keyring`: “Signing keys, newest first, plus revoked agent ids.”
- `backend/src/hmap/core/policy.py::Keyring.from_settings`: `def from_settings(cls, settings: Settings | None=None, *, path: Path | None=None) -> 'Keyring'`
- `backend/src/hmap/core/policy.py::Keyring.reload`: `def reload(self, *, force: bool=False) -> None`
- `backend/src/hmap/core/policy.py::Keyring.rotate`: “Add a new key in front; the old ones keep verifying until retired.”
- `backend/src/hmap/core/policy.py::Keyring.retire`: `def retire(self, kid: str) -> None`
- `backend/src/hmap/core/policy.py::Keyring.revoke`: `def revoke(self, agent_id: str) -> None`
- `backend/src/hmap/core/policy.py::Keyring.unrevoke`: `def unrevoke(self, agent_id: str) -> None`
- `backend/src/hmap/core/policy.py::Keyring.newest`: `def newest(self) -> tuple[str, bytes]`
- `backend/src/hmap/core/policy.py::Keyring.get`: `def get(self, kid: str) -> bytes | None`
- `backend/src/hmap/core/policy.py::Keyring.is_revoked`: `def is_revoked(self, agent_id: str) -> bool`
- `backend/src/hmap/core/policy.py::Decision`: `class Decision`
- `backend/src/hmap/core/policy.py::Decision.allow`: `def allow(rule: str) -> 'Decision'`
- `backend/src/hmap/core/policy.py::Decision.deny`: `def deny(rule: str, reason: str) -> 'Decision'`
- `backend/src/hmap/core/policy.py::issue_token`: `def issue_token(keyring: Keyring, agent_id: str, *, ttl_s: int, now: float | None=None) -> str`
- `backend/src/hmap/core/policy.py::check_token`: `def check_token(keyring: Keyring, token: str | None, agent_id: str, *, now: float | None=None) -> Decision`
- `backend/src/hmap/core/policy.py::Signer`: “Signs envelopes for any sender in this process (agents and the Manager), renewing tokens at half-life and switching to the newest key after a rotation.”
- `backend/src/hmap/core/policy.py::Signer.token`: `def token(self, agent_id: str, *, now: float | None=None) -> str`
- `backend/src/hmap/core/policy.py::Signer.sign`: `def sign(self, env: Envelope) -> str`
- `backend/src/hmap/core/policy.py::check_auth`: `def check_auth(keyring: Keyring, env: Envelope, *, now: float | None=None) -> Decision`
- `backend/src/hmap/core/policy.py::AuditEntry`: `class AuditEntry`
- `backend/src/hmap/core/policy.py::AuditEntry.as_dict`: `def as_dict(self) -> dict[str, Any]`
- `backend/src/hmap/core/policy.py::AuditSink`: `class AuditSink(Protocol)`
- `backend/src/hmap/core/policy.py::AuditSink.write`: `async def write(self, entry: AuditEntry) -> None`
- `backend/src/hmap/core/policy.py::AuditSink.recent`: `async def recent(self, limit: int=100) -> list[AuditEntry]`
- `backend/src/hmap/core/policy.py::MemoryAudit`: `class MemoryAudit`
- `backend/src/hmap/core/policy.py::MemoryAudit.__init__`: `def __init__(self, maxlen: int=2000) -> None`
- `backend/src/hmap/core/policy.py::MemoryAudit.write`: `async def write(self, entry: AuditEntry) -> None`
- `backend/src/hmap/core/policy.py::MemoryAudit.recent`: `async def recent(self, limit: int=100) -> list[AuditEntry]`
- `backend/src/hmap/core/policy.py::PgAudit`: “``security_audit`` (migration 006).”
- `backend/src/hmap/core/policy.py::PgAudit.__init__`: `def __init__(self, db: Any) -> None`
- `backend/src/hmap/core/policy.py::PgAudit.write`: `async def write(self, entry: AuditEntry) -> None`
- `backend/src/hmap/core/policy.py::PgAudit.recent`: `async def recent(self, limit: int=100) -> list[AuditEntry]`
- `backend/src/hmap/core/policy.py::PolicyContext`: `class PolicyContext(Protocol)`
- `backend/src/hmap/core/policy.py::PolicyContext.agent_capabilities`: `async def agent_capabilities(self, agent_id: str) -> list[str] | None`
- `backend/src/hmap/core/policy.py::PolicyContext.execution`: “(assigned agent id, task capability) or None when unknown.”
- `backend/src/hmap/core/policy.py::Policy`: “Checks one message.”
- `backend/src/hmap/core/policy.py::Policy.__init__`: `def __init__(self, settings: Settings | None=None, *, keyring: Keyring | None=None, audit: Sequence[AuditSink]=(), manager_id: str='manager') -> None`
- `backend/src/hmap/core/policy.py::Policy.keyring`: `def keyring(self) -> Keyring`
- `backend/src/hmap/core/policy.py::Policy.check_report`: “True = handle the message.”

## `backend/src/hmap/core/runtime/__init__.py`

“hmap package.”


## `backend/src/hmap/core/runtime/base.py`

“What "an agent" is (doc 01 §4 "Agent plug-in contract").”

- `backend/src/hmap/core/runtime/base.py::AgentContext`: “Everything a handler may use.”
- `backend/src/hmap/core/runtime/base.py::AgentContext.project_id`: `def project_id(self) -> str`
- `backend/src/hmap/core/runtime/base.py::AgentContext.progress`: “Report progress (at-most-once telemetry, research §22).”
- `backend/src/hmap/core/runtime/base.py::AgentContext.check_cancelled`: “Call between steps; raises Cancelled so the runtime reports a cancelled execution.”
- `backend/src/hmap/core/runtime/base.py::AgentContext.put_json`: `async def put_json(self, obj: BaseModel | dict[str, Any], *, artifact_type: str, artifact_id: str | None=None) -> ArtifactRef`
- `backend/src/hmap/core/runtime/base.py::AgentContext.get_json`: `async def get_json(self, ref: ArtifactRef, model: type[M]) -> M`
- `backend/src/hmap/core/runtime/base.py::AgentContext.result`: `def result(self, artifact_refs: list[ArtifactRef], *, summary: str | None=None, outcome: str='success', evidence: list[str] | None=None) -> TaskResult`
- `backend/src/hmap/core/runtime/base.py::BaseAgent`: “Subclass, set ``name`` and ``capabilities``, implement ``handle``.”
- `backend/src/hmap/core/runtime/base.py::BaseAgent.on_start`: “Optional: warm caches/models before registering.”
- `backend/src/hmap/core/runtime/base.py::BaseAgent.on_stop`: “Optional: release resources.”
- `backend/src/hmap/core/runtime/base.py::BaseAgent.handle`: `async def handle(self, task: TaskAssign, ctx: AgentContext) -> TaskResult`

## `backend/src/hmap/core/runtime/discovery.py`

“Plug-in discovery (Sprint 1 item 1.18, §3.5).”

- `backend/src/hmap/core/runtime/discovery.py::PluginError`: `class PluginError(HmapError)`
- `backend/src/hmap/core/runtime/discovery.py::CapabilityConflict`: `class CapabilityConflict(PluginError)`
- `backend/src/hmap/core/runtime/discovery.py::PluginLoadError`: `class PluginLoadError`
- `backend/src/hmap/core/runtime/discovery.py::DiscoveryResult`: `class DiscoveryResult`
- `backend/src/hmap/core/runtime/discovery.py::discover_all`: “Import every ``<package>.<sub>.plugin`` and collect its ``PLUGIN``; ``enabled`` filters by plug-in name.”
- `backend/src/hmap/core/runtime/discovery.py::discover`: `def discover(enabled: set[str] | None=None, *, packages: Sequence[str]=(AGENTS_PACKAGE,), strict: bool=False) -> list[Plugin]`
- `backend/src/hmap/core/runtime/discovery.py::validate_plugin`: `def validate_plugin(plugin: Plugin) -> None`
- `backend/src/hmap/core/runtime/discovery.py::resolve_capabilities`: “capability -> (plugin, agent class) of the highest-priority provider.”
- `backend/src/hmap/core/runtime/discovery.py::agents_to_run`: “One entry per agent class that won at least one capability, with the capabilities it should serve.”
- `backend/src/hmap/core/runtime/discovery.py::CapabilityRow`: `class CapabilityRow`
- `backend/src/hmap/core/runtime/discovery.py::CapabilityRow.to_dict`: `def to_dict(self) -> dict[str, object]`
- `backend/src/hmap/core/runtime/discovery.py::capability_table`: “Every declared capability (plus ``expected`` ones nobody serves, as ``missing``), sorted by name.”

## `backend/src/hmap/core/runtime/host.py`

“Dev agent host (Sprint 1 item 1.18): ``hmap-agents`` runs every discovered agent in ONE asyncio process.”

- `backend/src/hmap/core/runtime/host.py::make_bus`: `def make_bus(settings: Settings) -> Bus`
- `backend/src/hmap/core/runtime/host.py::make_llm`: `def make_llm(settings: Settings) -> LLMClient`
- `backend/src/hmap/core/runtime/host.py::llm_for_plugin`: “The gateway binds each plug-in to its own replay-cache folder (``Gateway.for_plugin``); duck-typed.”
- `backend/src/hmap/core/runtime/host.py::make_artifacts`: `def make_artifacts(settings: Settings) -> ArtifactStore`
- `backend/src/hmap/core/runtime/host.py::make_contexts`: `def make_contexts(settings: Settings) -> ContextStore`
- `backend/src/hmap/core/runtime/host.py::make_inbox`: `def make_inbox(settings: Settings) -> InboxStore`
- `backend/src/hmap/core/runtime/host.py::HostDeps`: `class HostDeps`
- `backend/src/hmap/core/runtime/host.py::AgentHost`: `class AgentHost`
- `backend/src/hmap/core/runtime/host.py::AgentHost.build_workers`: `def build_workers(self) -> list[AgentWorker]`
- `backend/src/hmap/core/runtime/host.py::AgentHost.start`: `async def start(self) -> None`
- `backend/src/hmap/core/runtime/host.py::AgentHost.stop`: `async def stop(self, reason: str='shutdown') -> None`
- `backend/src/hmap/core/runtime/host.py::resolve_refiners`: “capability -> the refine adapter of the highest-priority plug-in that registered one (``Plugin.refiners``, Sprint 4 plan D1).”
- `backend/src/hmap/core/runtime/host.py::build_deps`: `def build_deps(settings: Settings) -> HostDeps`
- `backend/src/hmap/core/runtime/host.py::select_enabled`: `def select_enabled(settings: Settings, only: str | None) -> set[str] | None`
- `backend/src/hmap/core/runtime/host.py::run_agents`: “Discover, start one worker per resolved agent, wait for ``stop_event`` (or SIGINT/SIGTERM), then drain.”
- `backend/src/hmap/core/runtime/host.py::build_parser`: `def build_parser() -> argparse.ArgumentParser`
- `backend/src/hmap/core/runtime/host.py::format_table`: `def format_table(rows: Sequence[dict[str, Any]]) -> str`
- `backend/src/hmap/core/runtime/host.py::cmd_list`: `def cmd_list(settings: Settings, *, as_json: bool=False) -> int`
- `backend/src/hmap/core/runtime/host.py::main`: `def main(argv: Sequence[str] | None=None) -> int`

## `backend/src/hmap/core/runtime/lifecycle.py`

“Agent lifecycle FSM (research §16, §21).”

- `backend/src/hmap/core/runtime/lifecycle.py::InvalidTransition`: `class InvalidTransition(HmapError)`
- `backend/src/hmap/core/runtime/lifecycle.py::can_transition`: `def can_transition(src: AgentState, dst: AgentState) -> bool`
- `backend/src/hmap/core/runtime/lifecycle.py::Transition`: `class Transition`
- `backend/src/hmap/core/runtime/lifecycle.py::AgentLifecycle`: `class AgentLifecycle`
- `backend/src/hmap/core/runtime/lifecycle.py::AgentLifecycle.to`: “Move to ``dst`` or raise ``InvalidTransition``.”
- `backend/src/hmap/core/runtime/lifecycle.py::AgentLifecycle.try_to`: “Move if allowed; return whether the state changed (for idempotent paths like BUSY<->AVAILABLE).”
- `backend/src/hmap/core/runtime/lifecycle.py::AgentLifecycle.is_terminal`: `def is_terminal(self) -> bool`

## `backend/src/hmap/core/runtime/worker.py`

“Agent runtime (Sprint 1 item 1.12): wraps one ``BaseAgent`` instance and does everything except ``handle``.”

- `backend/src/hmap/core/runtime/worker.py::Refiner`: “A refine adapter and the plug-in that registered it (its replay cache is used for the adapter's calls).”
- `backend/src/hmap/core/runtime/worker.py::AgentWorker`: “Hosts one agent instance: registration, heartbeats, consumption, dedup, replies, cancellation, draining.”
- `backend/src/hmap/core/runtime/worker.py::AgentWorker.__init__`: `def __init__(self, agent: BaseAgent, bus: Bus, llm: LLMClient, artifacts: ArtifactStore, contexts: ContextStore, inbox: InboxStore, *, heartbeat_s: float=5.0, agent_id: str | None=None, capabilities: Sequence[str] | None=None, plugin: str | None=None, drain_timeout_s: float=30.0, cancel_grace_s: float=2.0, register_retry_delays_s: Sequence[float]=(0.5, 2.0, 5.0), refiners: Mapping[str, Refiner] | None=None) -> None`
- `backend/src/hmap/core/runtime/worker.py::AgentWorker.state`: `def state(self) -> AgentState`
- `backend/src/hmap/core/runtime/worker.py::AgentWorker.available_slots`: `def available_slots(self) -> int`
- `backend/src/hmap/core/runtime/worker.py::AgentWorker.current_execution_ids`: `def current_execution_ids(self) -> list[str]`
- `backend/src/hmap/core/runtime/worker.py::AgentWorker.start`: `async def start(self) -> None`
- `backend/src/hmap/core/runtime/worker.py::AgentWorker.stop`: “Drain gracefully: stop accepting, let in-flight work finish (up to the deadline), deregister, OFFLINE.”

## `backend/src/hmap/core/tracing.py`

“W3C ``traceparent`` propagation (research §11) and structured JSON logging.”

- `backend/src/hmap/core/tracing.py::TraceContext`: Defines an immutable trace context with trace_id, span_id, and flags.
- `backend/src/hmap/core/tracing.py::TraceContext.header`: Returns the traceparent header string for the context.
- `backend/src/hmap/core/tracing.py::parse_traceparent`: Parses a traceparent header into a TraceContext, validating format and non-zero IDs.
- `backend/src/hmap/core/tracing.py::is_valid_traceparent`: Checks if a header string is a valid traceparent, returning True or False.
- `backend/src/hmap/core/tracing.py::new_traceparent`: Generates a new traceparent header with random trace and span IDs.
- `backend/src/hmap/core/tracing.py::child_traceparent`: “Same trace, new span.”
- `backend/src/hmap/core/tracing.py::current_traceparent`: Retrieves the current traceparent from the context variable.
- `backend/src/hmap/core/tracing.py::set_current_traceparent`: Sets the current traceparent in the context variable.
- `backend/src/hmap/core/tracing.py::bind_log_context`: “Attach task/execution/message/agent ids to every log line in this async context.”
- `backend/src/hmap/core/tracing.py::clear_log_context`: Clears all context variables used for structured logging.
- `backend/src/hmap/core/tracing.py::configure_logging`: Configures structlog processors, log level, and output format for JSON or console.
- `backend/src/hmap/core/tracing.py::get_logger`: Returns a structlog logger, optionally named.

## `backend/src/hmap/db/__init__.py`

“Postgres persistence (Sprint 1 item 1.5): connection pool, schema (``tables``) and migrations (``migrate``).”


## `backend/src/hmap/db/database.py`

“Async Postgres access for the ``pg_*`` stores: URL helpers + a small psycopg 3 connection pool.”

- `backend/src/hmap/db/database.py::database_url`: “``url`` or ``$HMAP_DATABASE_URL`` or the dev default, normalised to the ``postgresql+psycopg://`` form.”
- `backend/src/hmap/db/database.py::conninfo`: “The libpq form of :func:`database_url` (``postgresql://...``) for psycopg.”
- `backend/src/hmap/db/database.py::check_schema_name`: `def check_schema_name(schema: str) -> str`
- `backend/src/hmap/db/database.py::session_options`: “libpq ``options`` used by every connection (async pool and Alembic alike).”
- `backend/src/hmap/db/database.py::PoolTimeout`: “No connection became free within ``acquire_timeout``.”
- `backend/src/hmap/db/database.py::Database`: “A bounded pool of autocommit ``AsyncConnection``s (dict rows).”
- `backend/src/hmap/db/database.py::Database.__init__`: `def __init__(self, url: str | None=None, *, schema: str | None=None, max_size: int=10, connect_timeout: float=5.0, acquire_timeout: float=30.0) -> None`
- `backend/src/hmap/db/database.py::Database.connection`: “Borrow an autocommit connection.”
- `backend/src/hmap/db/database.py::Database.transaction`: “One database transaction: COMMIT when the block exits normally, ROLLBACK on an exception.”
- `backend/src/hmap/db/database.py::Database.fetch`: `async def fetch(self, query: str, params: Any=None) -> list[DictRow]`
- `backend/src/hmap/db/database.py::Database.ping`: `async def ping(self) -> bool`
- `backend/src/hmap/db/database.py::Database.close`: “Close idle connections; connections still borrowed are closed when released.”

## `backend/src/hmap/db/migrate.py`

“Programmatic Alembic: migrate on start, and test helpers.”

- `backend/src/hmap/db/migrate.py::alembic_config`: `def alembic_config(url: str | None=None, *, schema: str | None=None, script_location: str | Path | None=None) -> Config`
- `backend/src/hmap/db/migrate.py::upgrade`: “``alembic upgrade <revision>``.”
- `backend/src/hmap/db/migrate.py::downgrade`: `def downgrade(url: str | None=None, *, schema: str | None=None, revision: str='base') -> None`
- `backend/src/hmap/db/migrate.py::current_revision`: “The revision the database is at (``None`` = empty / never migrated).”
- `backend/src/hmap/db/migrate.py::upgrade_async`: `async def upgrade_async(url: str | None=None, *, schema: str | None=None, revision: str='head') -> None`
- `backend/src/hmap/db/migrate.py::downgrade_async`: `async def downgrade_async(url: str | None=None, *, schema: str | None=None, revision: str='base') -> None`

## `backend/src/hmap/db/tables.py`

“SQLAlchemy Core table models of the Sprint 1 schema (mirrors ``alembic/versions/001_sprint_1_core.py``).”


## `backend/src/hmap/manager/__init__.py`

“Manager core (owner: Member 1): task state machine, task store, assignment, retries, watchdog, graph executor.”


## `backend/src/hmap/manager/assignment.py`

“Agent selection for READY tasks (research §20, §27).”

- `backend/src/hmap/manager/assignment.py::assignment_order`: “Highest priority first, then oldest.”
- `backend/src/hmap/manager/assignment.py::agent_load`: “In-flight executions per agent according to the task store (authoritative, unlike heartbeats).”
- `backend/src/hmap/manager/assignment.py::free_slots`: “Conservative: what the agent last advertised, but never more than ``max_slots`` minus what we assigned to it (covers assignments made since its last heartbeat).”
- `backend/src/hmap/manager/assignment.py::choose_agent`: “Keep the registry's order (real before stubs, least loaded) but drop agents without a free slot and try agents that already rejected this task last.”

## `backend/src/hmap/manager/config.py`

“Manager tunables (research §23 defaults).”

- `backend/src/hmap/manager/config.py::ManagerConfig`: `class ManagerConfig`

## `backend/src/hmap/manager/executor.py`

“Graph executor strategy (Sprint 1 item 1.13).”

- `backend/src/hmap/manager/executor.py::GraphExecutor`: `class GraphExecutor(Protocol)`
- `backend/src/hmap/manager/executor.py::GraphExecutor.order`: “Plan task ids in creation order (dependencies first).”
- `backend/src/hmap/manager/executor.py::GraphExecutor.ready`: “CREATED task ids that may become READY now.”
- `backend/src/hmap/manager/executor.py::GraphExecutor.blocked`: “CREATED task id -> dependency ids that make it unrunnable (task becomes BLOCKED).”
- `backend/src/hmap/manager/executor.py::GraphExecutor.outcome`: “COMPLETED / FAILED when the project's graph is settled, else None (keep executing).”
- `backend/src/hmap/manager/executor.py::NaiveTopologicalExecutor`: “Kahn-style: a task is ready when it is CREATED, approved, and every dependency is COMPLETED.”
- `backend/src/hmap/manager/executor.py::NaiveTopologicalExecutor.order`: `def order(self, graph: TaskGraph) -> list[str]`
- `backend/src/hmap/manager/executor.py::NaiveTopologicalExecutor.ready`: `def ready(self, tasks: Sequence[TaskRecord]) -> list[str]`
- `backend/src/hmap/manager/executor.py::NaiveTopologicalExecutor.blocked`: `def blocked(self, tasks: Sequence[TaskRecord]) -> dict[str, list[str]]`
- `backend/src/hmap/manager/executor.py::NaiveTopologicalExecutor.outcome`: `def outcome(self, tasks: Sequence[TaskRecord]) -> ProjectState | None`

## `backend/src/hmap/manager/hooks.py`

“Plug-in hook dispatch and strategy-slot resolution (Sprint 1 §3.5).”

- `backend/src/hmap/manager/hooks.py::HookDispatcher`: “Calls every ``Hook`` whose ``event_type`` equals the event's type (and, for ``task.*`` events with a ``capability`` filter, whose capability matches ``event.data['capability']``).”
- `backend/src/hmap/manager/hooks.py::HookDispatcher.__init__`: `def __init__(self, plugins: Sequence[Plugin]) -> None`
- `backend/src/hmap/manager/hooks.py::HookDispatcher.matching`: `def matching(self, event: DomainEvent) -> list[tuple[str, Hook]]`
- `backend/src/hmap/manager/hooks.py::HookDispatcher.dispatch`: `async def dispatch(self, event: DomainEvent, handle: ManagerHandle) -> None`
- `backend/src/hmap/manager/hooks.py::resolve_strategy`: “The highest-priority plug-in that provides ``slot`` (non-None) wins; a class is instantiated.”

## `backend/src/hmap/manager/manager.py`

“The Manager (Sprint 1 item 1.13): owns task state, assigns work, consumes agent reports, retries, times out, cancels and drives task graphs.”

- `backend/src/hmap/manager/manager.py::UnknownProject`: `class UnknownProject(KeyError)`
- `backend/src/hmap/manager/manager.py::UnknownTask`: `class UnknownTask(KeyError)`
- `backend/src/hmap/manager/manager.py::InvalidProjectState`: `class InvalidProjectState(ValueError)`
- `backend/src/hmap/manager/manager.py::StaleGraph`: “An approval or replan refers to a plan version that is no longer the project's current one.”
- `backend/src/hmap/manager/manager.py::InvalidTaskState`: “An operator action that does not fit the task's state (e.g.”
- `backend/src/hmap/manager/manager.py::Manager`: `class Manager`
- `backend/src/hmap/manager/manager.py::Manager.__init__`: `def __init__(self, *, bus: Bus, store: TaskStore, outbox: OutboxStore, registry: Registry, artifacts: ArtifactStore, contexts: ContextStore, plugins: Sequence[Plugin]=(), clock: Callable[[], datetime]=utcnow, config: ManagerConfig | None=None, rng: random.Random | None=None, inbox: InboxStore | None=None) -> None`
- `backend/src/hmap/manager/manager.py::Manager.start`: “Consume agent reports; optionally run ``tick`` periodically in the background.”
- `backend/src/hmap/manager/manager.py::Manager.stop`: `async def stop(self) -> None`
- `backend/src/hmap/manager/manager.py::Manager.flush_outbox`: “Dev/test helper: publish unpublished outbox rows to the bus.”
- `backend/src/hmap/manager/manager.py::Manager.create_project`: “``auto_approve``: the plan is still created and shown, then approved automatically (no human gate); the human keeps the Stop button (:meth:`stop_project`).”
- `backend/src/hmap/manager/manager.py::Manager.list_projects`: “Live (not deleted) projects, optionally only one owner's.”
- `backend/src/hmap/manager/manager.py::Manager.get_project_record`: “The record, or :class:`UnknownProject` (also for a deleted project).”
- `backend/src/hmap/manager/manager.py::Manager.get_project`: `async def get_project(self, project_id: str) -> dict[str, Any]`
- `backend/src/hmap/manager/manager.py::Manager.start_run`: “Begin a new pipeline pass (an upload or a typed goal).”
- `backend/src/hmap/manager/manager.py::Manager.record_run_documents`: “Remember which stored artifact is which document of ``run`` (``documents[i]`` is ``artifact_ids[i]``), so the file list can show each upload by its name.”
- `backend/src/hmap/manager/manager.py::Manager.update_project`: “Rename, archive, or switch cloud models / refinement on or off.”
- `backend/src/hmap/manager/manager.py::Manager.delete_project`: “Stop any running work, erase the project's files and hide the project from every API.”
- `backend/src/hmap/manager/manager.py::Manager.list_tasks`: `async def list_tasks(self, project_id: str) -> list[dict[str, Any]]`
- `backend/src/hmap/manager/manager.py::Manager.get_task`: `async def get_task(self, task_id: str) -> dict[str, Any]`
- `backend/src/hmap/manager/manager.py::Manager.list_executions`: `async def list_executions(self, task_id: str) -> list[dict[str, Any]]`
- `backend/src/hmap/manager/manager.py::Manager.emit`: `async def emit(self, event: DomainEvent) -> None`
- `backend/src/hmap/manager/manager.py::Manager.create_task`: `async def create_task(self, project_id: str, capability: str, objective: str, *, acceptance_criteria: list[str] | None=None, inputs: dict[str, Any] | None=None, artifact_refs: list[ArtifactRef] | None=None, depends_on: list[str] | None=None, parent_task_id: str | None=None) -> str`
- `backend/src/hmap/manager/manager.py::Manager.submit_graph`: `async def submit_graph(self, project_id: str, graph: TaskGraph, *, require_approval: bool=True) -> None`
- `backend/src/hmap/manager/manager.py::Manager.approve`: “Human plan-approval gate.”
- `backend/src/hmap/manager/manager.py::Manager.replace_graph`: “Replanning (Sprint 3): swap the current run's plan for ``graph`` and keep finished work.”
- `backend/src/hmap/manager/manager.py::Manager.cancel_task`: “CANCELLED + ``task.cancelled`` event (agents listen for it and stop cooperatively).”
- `backend/src/hmap/manager/manager.py::Manager.stop_project`: “The human's Stop button: cancel every unfinished task (agents get ``task.cancelled`` and stop cooperatively; late results are kept as evidence only), close pending approvals and move the project to CANCELLED.”
- `backend/src/hmap/manager/manager.py::Manager.replay_dead_letter`: “An operator replays a dead-lettered task (Sprint 4 item 4.18, plan D18; research §26: never automatic, never blind).”
- `backend/src/hmap/manager/manager.py::Manager.handle_delivery`: “Bus handler for ``hmap.manager``.”
- `backend/src/hmap/manager/manager.py::Manager.handle_message`: “Apply one agent report.”
- `backend/src/hmap/manager/manager.py::Manager.tick`: “Periodic housekeeping: ack timeouts, lease expiry + abandoned executions, due retries, graph progress, assignment.”

## `backend/src/hmap/manager/pg_store.py`

“Postgres ``TaskStore`` (Sprint 1 items 1.5/1.8; research §17, §18, §22, §34).”

- `backend/src/hmap/manager/pg_store.py::PostgresTx`: “``TaskStoreTx`` bound to one connection that is inside a transaction.”
- `backend/src/hmap/manager/pg_store.py::PostgresTx.__init__`: `def __init__(self, conn: Conn) -> None`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.insert_project`: `async def insert_project(self, project: ProjectRecord) -> ProjectRecord`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.update_project`: `async def update_project(self, project: ProjectRecord, *, expected_version: int) -> ProjectRecord`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.insert_task`: `async def insert_task(self, task: TaskRecord) -> TaskRecord`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.update_task`: `async def update_task(self, task: TaskRecord, *, expected_version: int) -> TaskRecord`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.insert_execution`: `async def insert_execution(self, execution: ExecutionRecord) -> ExecutionRecord`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.update_execution`: `async def update_execution(self, execution: ExecutionRecord) -> ExecutionRecord`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.insert_approval`: `async def insert_approval(self, approval: ApprovalRecord) -> ApprovalRecord`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.update_approval`: `async def update_approval(self, approval: ApprovalRecord) -> ApprovalRecord`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.add_event`: `async def add_event(self, event: DomainEvent) -> None`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.add_command`: `async def add_command(self, capability: str, envelope: Envelope) -> None`
- `backend/src/hmap/manager/pg_store.py::PostgresTx.record_inbox`: “Inbox dedup key in THIS transaction (research §24): False = already processed (effect committed).”
- `backend/src/hmap/manager/pg_store.py::PostgresTx.flush_outbox`: “Insert the staged outbox rows now (normally done right before COMMIT).”
- `backend/src/hmap/manager/pg_store.py::PostgresTaskStore`: “``TaskStore`` on Postgres.”
- `backend/src/hmap/manager/pg_store.py::PostgresTaskStore.__init__`: `def __init__(self, db: Database, *, local_lock: bool=True, serialize_writes: bool=False) -> None`
- `backend/src/hmap/manager/pg_store.py::PostgresTaskStore.transaction`: `def transaction(self) -> AbstractAsyncContextManager[TaskStoreTx]`

## `backend/src/hmap/manager/records.py`

“Manager-owned persistent records (research §34).”

- `backend/src/hmap/manager/records.py::Record`: `class Record(BaseModel)`
- `backend/src/hmap/manager/records.py::Record.to_dict`: `def to_dict(self) -> dict[str, Any]`
- `backend/src/hmap/manager/records.py::RunRecord`: “One pass of the pipeline over a project (an upload or a typed goal starts one).”
- `backend/src/hmap/manager/records.py::ProjectRecord`: `class ProjectRecord(Record)`
- `backend/src/hmap/manager/records.py::ProjectRecord.current_run`: `def current_run(self) -> int`
- `backend/src/hmap/manager/records.py::TaskRecord`: `class TaskRecord(Record)`
- `backend/src/hmap/manager/records.py::ExecutionRecord`: `class ExecutionRecord(Record)`
- `backend/src/hmap/manager/records.py::ApprovalRecord`: `class ApprovalRecord(Record)`

## `backend/src/hmap/manager/retry.py`

“Retry policy (research §23, §25, §26): what to do with a failed execution.”

- `backend/src/hmap/manager/retry.py::FailureAction`: `class FailureAction(StrEnum)`
- `backend/src/hmap/manager/retry.py::RetryDecision`: `class RetryDecision`
- `backend/src/hmap/manager/retry.py::to_code`: `def to_code(code: ErrorCode | str) -> ErrorCode`
- `backend/src/hmap/manager/retry.py::should_retry`: “Taxonomy first; an agent may additionally flag e.g.”
- `backend/src/hmap/manager/retry.py::backoff_delay`: “Delay before retry number ``retry_index`` (0-based): configured step + bounded jitter; honours a larger requested delay (``Retry-After`` / ``retry.request``).”
- `backend/src/hmap/manager/retry.py::decide`: `def decide(code: ErrorCode | str, *, retries_used: int, config: ManagerConfig, rng: random.Random, agent_says_retryable: bool | None=None, requested_delay_s: float | None=None) -> RetryDecision`

## `backend/src/hmap/manager/store.py`

“Task store (research §17, §24, §34): projects, tasks, executions, approvals + the outbox, written together.”

- `backend/src/hmap/manager/store.py::StoreError`: “Base class of store integrity errors.”
- `backend/src/hmap/manager/store.py::ConcurrencyConflict`: “CAS failed: the record changed since it was read (another writer won).”
- `backend/src/hmap/manager/store.py::UniqueViolation`: “A unique key (``task_id``, ``execution_id``, ``(task_id, attempt)`` ...) already exists.”
- `backend/src/hmap/manager/store.py::RecordNotFound`: “Update of a record that does not exist.”
- `backend/src/hmap/manager/store.py::TaskStoreReader`: `class TaskStoreReader(Protocol)`
- `backend/src/hmap/manager/store.py::TaskStoreReader.get_project`: `async def get_project(self, project_id: str) -> ProjectRecord | None`
- `backend/src/hmap/manager/store.py::TaskStoreReader.list_projects`: `async def list_projects(self, *, owner_id: str | None=None) -> list[ProjectRecord]`
- `backend/src/hmap/manager/store.py::TaskStoreReader.get_task`: `async def get_task(self, task_id: str) -> TaskRecord | None`
- `backend/src/hmap/manager/store.py::TaskStoreReader.list_tasks`: `async def list_tasks(self, *, project_id: str | None=None, states: Collection[TaskState] | None=None) -> list[TaskRecord]`
- `backend/src/hmap/manager/store.py::TaskStoreReader.get_execution`: `async def get_execution(self, execution_id: str) -> ExecutionRecord | None`
- `backend/src/hmap/manager/store.py::TaskStoreReader.list_executions`: `async def list_executions(self, *, task_id: str | None=None, agent_id: str | None=None, statuses: Collection[ExecutionStatus] | None=None) -> list[ExecutionRecord]`
- `backend/src/hmap/manager/store.py::TaskStoreReader.list_approvals`: `async def list_approvals(self, *, project_id: str | None=None) -> list[ApprovalRecord]`
- `backend/src/hmap/manager/store.py::TaskStoreTx`: “One unit of work.”
- `backend/src/hmap/manager/store.py::TaskStoreTx.insert_project`: `async def insert_project(self, project: ProjectRecord) -> ProjectRecord`
- `backend/src/hmap/manager/store.py::TaskStoreTx.update_project`: `async def update_project(self, project: ProjectRecord, *, expected_version: int) -> ProjectRecord`
- `backend/src/hmap/manager/store.py::TaskStoreTx.insert_task`: `async def insert_task(self, task: TaskRecord) -> TaskRecord`
- `backend/src/hmap/manager/store.py::TaskStoreTx.update_task`: `async def update_task(self, task: TaskRecord, *, expected_version: int) -> TaskRecord`
- `backend/src/hmap/manager/store.py::TaskStoreTx.insert_execution`: `async def insert_execution(self, execution: ExecutionRecord) -> ExecutionRecord`
- `backend/src/hmap/manager/store.py::TaskStoreTx.update_execution`: `async def update_execution(self, execution: ExecutionRecord) -> ExecutionRecord`
- `backend/src/hmap/manager/store.py::TaskStoreTx.insert_approval`: `async def insert_approval(self, approval: ApprovalRecord) -> ApprovalRecord`
- `backend/src/hmap/manager/store.py::TaskStoreTx.update_approval`: `async def update_approval(self, approval: ApprovalRecord) -> ApprovalRecord`
- `backend/src/hmap/manager/store.py::TaskStoreTx.add_event`: `async def add_event(self, event: DomainEvent) -> None`
- `backend/src/hmap/manager/store.py::TaskStoreTx.add_command`: `async def add_command(self, capability: str, envelope: Envelope) -> None`
- `backend/src/hmap/manager/store.py::TaskStore`: “Reads outside a transaction return committed state.”
- `backend/src/hmap/manager/store.py::TaskStore.transaction`: `def transaction(self) -> AbstractAsyncContextManager[TaskStoreTx]`
- `backend/src/hmap/manager/store.py::InMemoryTaskStore`: “Phase-A store.”
- `backend/src/hmap/manager/store.py::InMemoryTaskStore.__init__`: `def __init__(self, outbox: OutboxStore) -> None`
- `backend/src/hmap/manager/store.py::InMemoryTaskStore.transaction`: `def transaction(self) -> AbstractAsyncContextManager[TaskStoreTx]`

## `backend/src/hmap/manager/transitions.py`

“Task state machine (Sprint 1 item 1.6; research §9, §12, §17, §18).”

- `backend/src/hmap/manager/transitions.py::TransitionError`: “A transition that is not in ``ALLOWED``.”
- `backend/src/hmap/manager/transitions.py::TransitionError.__init__`: `def __init__(self, from_state: TaskState, to_state: TaskState, task_id: str | None=None) -> None`
- `backend/src/hmap/manager/transitions.py::is_terminal`: `def is_terminal(state: TaskState) -> bool`
- `backend/src/hmap/manager/transitions.py::can_transition`: `def can_transition(from_state: TaskState, to_state: TaskState) -> bool`
- `backend/src/hmap/manager/transitions.py::check_transition`: “``operator=True`` also allows :data:`OPERATOR_TRANSITIONS` (only ``Manager.replay_dead_letter`` passes it).”
- `backend/src/hmap/manager/transitions.py::is_stale`: “True if a report that would move the task to ``reported`` is late/out-of-order and must not change state: the task is already terminal, or ``reported`` is not ahead of ``current`` on the happy path.”
- `backend/src/hmap/manager/transitions.py::classify`: “How the Manager treats an agent report: apply it, record it as evidence only, or flag it.”

## `backend/src/hmap/manager/watchdog.py`

“Watchdog decisions (research §21, §25, §26, §35): ack timeouts and abandoned executions.”

- `backend/src/hmap/manager/watchdog.py::ack_timed_out`: “Assigned executions whose ack deadline passed without a ``task.ack``.”
- `backend/src/hmap/manager/watchdog.py::agent_gone`: `def agent_gone(agent_id: str | None, agents: Mapping[str, AgentRecord]) -> bool`
- `backend/src/hmap/manager/watchdog.py::OrphanScan`: `class OrphanScan`
- `backend/src/hmap/manager/watchdog.py::agent_vouches`: “The agent is live and its latest heartbeat lists this execution.”
- `backend/src/hmap/manager/watchdog.py::scan_orphans`: “An execution is orphaned when its agent went OFFLINE / deregistered (or re-registered as a fresh instance).”

## `backend/src/hmap/obs/__init__.py`

“Observability (Member 4, Sprint 4 §5b): traces, metrics, and the helpers the platform calls at a few points.”


## `backend/src/hmap/obs/metrics.py`

“Metrics (Sprint 4 item 4.17, plan D14/D17): Prometheus counters, histograms and gauges in one registry.”

- `backend/src/hmap/obs/metrics.py::exposition`: “The text format Prometheus scrapes, and its content type.”
- `backend/src/hmap/obs/metrics.py::set_process_name`: `def set_process_name(name: str) -> None`
- `backend/src/hmap/obs/metrics.py::sample_process`: `def sample_process() -> None`
- `backend/src/hmap/obs/metrics.py::task_transition`: `def task_transition(capability: str, state: str) -> None`
- `backend/src/hmap/obs/metrics.py::llm_call`: `def llm_call(role: str, provider: str, seconds: float, input_tokens: int, output_tokens: int, *, outcome: str='ok') -> None`
- `backend/src/hmap/obs/metrics.py::Sampler`: “Refreshes the gauges every ``interval_s`` from the platform's own interfaces (no RabbitMQ / Postgres exporters needed).”
- `backend/src/hmap/obs/metrics.py::Sampler.__init__`: `def __init__(self, *, bus: Any, store: Any, registry: Any, interval_s: float=5.0) -> None`
- `backend/src/hmap/obs/metrics.py::Sampler.sample`: `async def sample(self) -> None`
- `backend/src/hmap/obs/metrics.py::Sampler.start`: `def start(self) -> None`
- `backend/src/hmap/obs/metrics.py::Sampler.stop`: `async def stop(self) -> None`
- `backend/src/hmap/obs/metrics.py::serve`: “Serve ``/metrics`` on ``addr:port`` in a background thread (the agents process).”
- `backend/src/hmap/obs/metrics.py::metric_names`: `def metric_names() -> Iterable[str]`
- `backend/src/hmap/obs/metrics.py::now_s`: `def now_s() -> float`

## `backend/src/hmap/obs/telemetry.py`

“Traces (Sprint 4 item 4.15, plan D11/D13/D17): OpenTelemetry spans exported over OTLP/HTTP to Jaeger v2.”

- `backend/src/hmap/obs/telemetry.py::configure`: “Start exporting spans.”
- `backend/src/hmap/obs/telemetry.py::shutdown`: “Flush and stop the exporter (process exit, tests).”
- `backend/src/hmap/obs/telemetry.py::flush`: `def flush() -> None`
- `backend/src/hmap/obs/telemetry.py::enabled`: `def enabled() -> bool`
- `backend/src/hmap/obs/telemetry.py::task_trace_id`: “The trace id (32 hex chars) every span of ``task_id`` shares.”
- `backend/src/hmap/obs/telemetry.py::task_traceparent`: “A W3C ``traceparent`` in the task's trace with a fresh span id (used when tracing is off).”
- `backend/src/hmap/obs/telemetry.py::trace_id_of`: `def trace_id_of(traceparent: str | None) -> str | None`
- `backend/src/hmap/obs/telemetry.py::safe_attrs`: “Only short scalar values under harmless keys (D17).”
- `backend/src/hmap/obs/telemetry.py::SpanHandle`: “What the code inside :func:`span` may do.”
- `backend/src/hmap/obs/telemetry.py::SpanHandle.__init__`: `def __init__(self, otel_span: trace.Span | None=None) -> None`
- `backend/src/hmap/obs/telemetry.py::SpanHandle.recording`: `def recording(self) -> bool`
- `backend/src/hmap/obs/telemetry.py::SpanHandle.set`: `def set(self, key: str, value: Any) -> None`
- `backend/src/hmap/obs/telemetry.py::SpanHandle.update`: `def update(self, attrs: Mapping[str, Any]) -> None`
- `backend/src/hmap/obs/telemetry.py::SpanHandle.event`: `def event(self, name: str, attrs: Mapping[str, Any] | None=None) -> None`
- `backend/src/hmap/obs/telemetry.py::SpanHandle.error`: “Mark the span failed.”
- `backend/src/hmap/obs/telemetry.py::SpanHandle.traceparent`: “This span as a W3C ``traceparent`` (to put into an envelope), or None when tracing is off.”
- `backend/src/hmap/obs/telemetry.py::span`: “A span named ``name``.”
- `backend/src/hmap/obs/telemetry.py::current_traceparent`: “The active span as a ``traceparent`` (None when tracing is off or no span is active).”

## `backend/src/hmap/services/__init__.py`

“hmap package.”


## `backend/src/hmap/services/accounts/__init__.py`

“User accounts: sign-up, sessions, password reset (Member 1).”


## `backend/src/hmap/services/accounts/base.py`

“User accounts, sessions and password-reset tokens: records + the store interface (memory and Postgres).”

- `backend/src/hmap/services/accounts/base.py::User`: `class User(BaseModel)`
- `backend/src/hmap/services/accounts/base.py::User.public`: “What the API may return about the signed-in user (never the hash).”
- `backend/src/hmap/services/accounts/base.py::Session`: `class Session(BaseModel)`
- `backend/src/hmap/services/accounts/base.py::PasswordReset`: `class PasswordReset(BaseModel)`
- `backend/src/hmap/services/accounts/base.py::EmailTaken`: `class EmailTaken(ValueError)`
- `backend/src/hmap/services/accounts/base.py::AccountStore`: `class AccountStore(Protocol)`
- `backend/src/hmap/services/accounts/base.py::AccountStore.create_user`: “Raises :class:`EmailTaken` if the (normalised) email exists.”
- `backend/src/hmap/services/accounts/base.py::AccountStore.get_user`: `async def get_user(self, user_id: str) -> User | None`
- `backend/src/hmap/services/accounts/base.py::AccountStore.get_user_by_email`: `async def get_user_by_email(self, email: str) -> User | None`
- `backend/src/hmap/services/accounts/base.py::AccountStore.update_user`: `async def update_user(self, user: User) -> User`
- `backend/src/hmap/services/accounts/base.py::AccountStore.create_session`: `async def create_session(self, session: Session) -> None`
- `backend/src/hmap/services/accounts/base.py::AccountStore.get_session`: `async def get_session(self, session_hash: str) -> Session | None`
- `backend/src/hmap/services/accounts/base.py::AccountStore.touch_session`: `async def touch_session(self, session_hash: str, last_seen_at: datetime, expires_at: datetime) -> None`
- `backend/src/hmap/services/accounts/base.py::AccountStore.delete_session`: `async def delete_session(self, session_hash: str) -> None`
- `backend/src/hmap/services/accounts/base.py::AccountStore.delete_user_sessions`: `async def delete_user_sessions(self, user_id: str, *, except_hash: str | None=None) -> int`
- `backend/src/hmap/services/accounts/base.py::AccountStore.create_reset`: `async def create_reset(self, reset: PasswordReset) -> None`
- `backend/src/hmap/services/accounts/base.py::AccountStore.use_reset`: “Atomically mark an unused, unexpired reset as used and return it; otherwise None (single use).”

## `backend/src/hmap/services/accounts/mailer.py`

“Outgoing account email (password reset).”

- `backend/src/hmap/services/accounts/mailer.py::Mailer`: `class Mailer(Protocol)`
- `backend/src/hmap/services/accounts/mailer.py::Mailer.send`: `async def send(self, to: str, subject: str, body: str) -> None`
- `backend/src/hmap/services/accounts/mailer.py::FileMailer`: “Development mailbox: one ``.eml`` file per message.”
- `backend/src/hmap/services/accounts/mailer.py::FileMailer.__init__`: `def __init__(self, folder: Path) -> None`
- `backend/src/hmap/services/accounts/mailer.py::FileMailer.send`: `async def send(self, to: str, subject: str, body: str) -> None`
- `backend/src/hmap/services/accounts/mailer.py::SmtpMailer`: `class SmtpMailer`
- `backend/src/hmap/services/accounts/mailer.py::SmtpMailer.__init__`: `def __init__(self, host: str, port: int, sender: str, *, username: str | None=None, password: str | None=None, starttls: bool=True) -> None`
- `backend/src/hmap/services/accounts/mailer.py::SmtpMailer.send`: `async def send(self, to: str, subject: str, body: str) -> None`

## `backend/src/hmap/services/accounts/memory.py`

“In-memory account store (tests and ``HMAP_STORE=memory``; forgets everything on restart).”

- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore`: `class InMemoryAccountStore`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.__init__`: `def __init__(self) -> None`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.create_user`: `async def create_user(self, user: User) -> User`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.get_user`: `async def get_user(self, user_id: str) -> User | None`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.get_user_by_email`: `async def get_user_by_email(self, email: str) -> User | None`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.update_user`: `async def update_user(self, user: User) -> User`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.create_session`: `async def create_session(self, session: Session) -> None`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.get_session`: `async def get_session(self, session_hash: str) -> Session | None`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.touch_session`: `async def touch_session(self, session_hash: str, last_seen_at: datetime, expires_at: datetime) -> None`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.delete_session`: `async def delete_session(self, session_hash: str) -> None`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.delete_user_sessions`: `async def delete_user_sessions(self, user_id: str, *, except_hash: str | None=None) -> int`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.create_reset`: `async def create_reset(self, reset: PasswordReset) -> None`
- `backend/src/hmap/services/accounts/memory.py::InMemoryAccountStore.use_reset`: `async def use_reset(self, token_hash: str, now: datetime) -> PasswordReset | None`

## `backend/src/hmap/services/accounts/pg.py`

“Account store in PostgreSQL (tables ``users``, ``sessions``, ``password_resets`` — migration ``001b``).”

- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore`: `class PostgresAccountStore`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.__init__`: `def __init__(self, db: Database) -> None`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.create_user`: `async def create_user(self, user: User) -> User`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.get_user`: `async def get_user(self, user_id: str) -> User | None`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.get_user_by_email`: `async def get_user_by_email(self, email: str) -> User | None`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.update_user`: `async def update_user(self, user: User) -> User`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.create_session`: `async def create_session(self, session: Session) -> None`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.get_session`: `async def get_session(self, session_hash: str) -> Session | None`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.touch_session`: `async def touch_session(self, session_hash: str, last_seen_at: datetime, expires_at: datetime) -> None`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.delete_session`: `async def delete_session(self, session_hash: str) -> None`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.delete_user_sessions`: `async def delete_user_sessions(self, user_id: str, *, except_hash: str | None=None) -> int`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.create_reset`: `async def create_reset(self, reset: PasswordReset) -> None`
- `backend/src/hmap/services/accounts/pg.py::PostgresAccountStore.use_reset`: `async def use_reset(self, token_hash: str, now: datetime) -> PasswordReset | None`

## `backend/src/hmap/services/accounts/ratelimit.py`

“Small in-process sliding-window rate limiter for login, registration and password-reset requests.”

- `backend/src/hmap/services/accounts/ratelimit.py::RateLimiter`: `class RateLimiter`
- `backend/src/hmap/services/accounts/ratelimit.py::RateLimiter.__init__`: `def __init__(self, limit: int, window_s: float, *, clock: Callable[[], float]=time.monotonic) -> None`
- `backend/src/hmap/services/accounts/ratelimit.py::RateLimiter.allow`: “Record an attempt for ``key``; False when it is over the limit (the attempt is still counted).”
- `backend/src/hmap/services/accounts/ratelimit.py::RateLimiter.retry_after`: `def retry_after(self, key: str) -> int`
- `backend/src/hmap/services/accounts/ratelimit.py::RateLimiter.reset`: `def reset(self, key: str) -> None`

## `backend/src/hmap/services/accounts/security.py`

“Password hashing and opaque tokens (standard library only).”

- `backend/src/hmap/services/accounts/security.py::hash_password`: `def hash_password(password: str) -> str`
- `backend/src/hmap/services/accounts/security.py::verify_password`: `def verify_password(password: str, stored: str) -> bool`
- `backend/src/hmap/services/accounts/security.py::needs_rehash`: `def needs_rehash(stored: str) -> bool`
- `backend/src/hmap/services/accounts/security.py::password_problem`: “A human-readable reason the password is too weak, or None.”
- `backend/src/hmap/services/accounts/security.py::normalize_email`: `def normalize_email(email: str) -> str`
- `backend/src/hmap/services/accounts/security.py::valid_email`: `def valid_email(email: str) -> bool`
- `backend/src/hmap/services/accounts/security.py::new_token`: `def new_token() -> str`
- `backend/src/hmap/services/accounts/security.py::token_hash`: `def token_hash(token: str) -> str`

## `backend/src/hmap/services/accounts/service.py`

“Account use cases: register, sign in/out, sessions, profile, password change and reset, WebSocket tickets.”

- `backend/src/hmap/services/accounts/service.py::AccountError`: “A user-facing problem; ``field`` names the form field it belongs to (or None).”
- `backend/src/hmap/services/accounts/service.py::AccountError.__init__`: `def __init__(self, message: str, *, field: str | None=None, status: int=400) -> None`
- `backend/src/hmap/services/accounts/service.py::RateLimited`: `class RateLimited(AccountError)`
- `backend/src/hmap/services/accounts/service.py::RateLimited.__init__`: `def __init__(self, retry_after: int) -> None`
- `backend/src/hmap/services/accounts/service.py::SessionInfo`: `class SessionInfo`
- `backend/src/hmap/services/accounts/service.py::AccountService`: `class AccountService`
- `backend/src/hmap/services/accounts/service.py::AccountService.__init__`: `def __init__(self, store: AccountStore, mailer: Mailer, *, public_url: str='http://localhost:3000', session_days: float=14.0, allow_registration: bool=True) -> None`
- `backend/src/hmap/services/accounts/service.py::AccountService.register`: `async def register(self, *, name: str, email: str, password: str, client: str, user_agent: str='') -> tuple[SessionInfo, str]`
- `backend/src/hmap/services/accounts/service.py::AccountService.login`: `async def login(self, *, email: str, password: str, client: str, user_agent: str='') -> tuple[SessionInfo, str]`
- `backend/src/hmap/services/accounts/service.py::AccountService.resolve`: “The signed-in user for a session cookie, or None (unknown/expired).”
- `backend/src/hmap/services/accounts/service.py::AccountService.logout`: `async def logout(self, token: str | None) -> None`
- `backend/src/hmap/services/accounts/service.py::AccountService.logout_everywhere`: `async def logout_everywhere(self, info: SessionInfo) -> int`
- `backend/src/hmap/services/accounts/service.py::AccountService.update_profile`: `async def update_profile(self, info: SessionInfo, *, name: str) -> User`
- `backend/src/hmap/services/accounts/service.py::AccountService.change_password`: `async def change_password(self, info: SessionInfo, *, current: str, new: str) -> int`
- `backend/src/hmap/services/accounts/service.py::AccountService.request_reset`: “Always succeeds from the caller's view (no account enumeration); sends mail only for real accounts.”
- `backend/src/hmap/services/accounts/service.py::AccountService.reset_password`: `async def reset_password(self, *, token: str, new: str) -> None`
- `backend/src/hmap/services/accounts/service.py::AccountService.issue_ticket`: `def issue_ticket(self, info: SessionInfo) -> str`
- `backend/src/hmap/services/accounts/service.py::AccountService.redeem_ticket`: “The user id for a valid, unexpired ticket (single use), else None.”

## `backend/src/hmap/services/artifact/__init__.py`

“hmap package.”


## `backend/src/hmap/services/artifact/base.py`

“Artifact store interface (research §15, Sprint 1 item 1.11).”

- `backend/src/hmap/services/artifact/base.py::ArtifactStore`: `class ArtifactStore(Protocol)`
- `backend/src/hmap/services/artifact/base.py::ArtifactStore.put`: “Store bytes immutably.”
- `backend/src/hmap/services/artifact/base.py::ArtifactStore.get`: “Return bytes after verifying SHA-256 (ArtifactIntegrityError) and scope (AuthorizationError).”
- `backend/src/hmap/services/artifact/base.py::ArtifactStore.latest`: `async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None`
- `backend/src/hmap/services/artifact/base.py::ArtifactStore.list`: `async def list(self, project_id: str) -> list[ArtifactRef]`
- `backend/src/hmap/services/artifact/base.py::ArtifactStore.delete_project`: “Erase every artifact of a deleted project (the only way bytes ever leave the store); returns the number of versions removed.”

## `backend/src/hmap/services/artifact/local.py`

“``LocalFSArtifactStore``: write-once files under ``HMAP_ARTIFACT_ROOT`` (Sprint 1 item 1.11, research §15).”

- `backend/src/hmap/services/artifact/local.py::write_once`: “Atomically create ``path`` with ``data`` and make it read-only.”
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore`: `class LocalFSArtifactStore`
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore.__init__`: `def __init__(self, root: str | Path) -> None`
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore.put`: `async def put(self, data: bytes, *, project_id: str, artifact_type: str, media_type: str, created_by: str, artifact_id: str | None=None) -> ArtifactRef`
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore.get`: `async def get(self, ref: ArtifactRef, *, project_id: str) -> bytes`
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore.latest`: `async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None`
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore.list`: `async def list(self, project_id: str) -> list[ArtifactRef]`
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore.delete_project`: `async def delete_project(self, project_id: str) -> int`
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore.version_dir`: `def version_dir(self, project_id: str, artifact_id: str, version: int) -> Path`
- `backend/src/hmap/services/artifact/local.py::LocalFSArtifactStore.path_for`: “Where the bytes of ``ref`` live (scope = ``ref.access_scope``).”

## `backend/src/hmap/services/artifact/memory.py`

“In-memory ``ArtifactStore`` (tests, Phase A) plus helpers shared with ``LocalFSArtifactStore``.”

- `backend/src/hmap/services/artifact/memory.py::ArtifactNotFound`: “The artifact (or version) does not exist in the caller's project.”
- `backend/src/hmap/services/artifact/memory.py::sha256_hex`: `def sha256_hex(data: bytes) -> str`
- `backend/src/hmap/services/artifact/memory.py::check_id`: “Ids become path segments in the local store, so only ``[A-Za-z0-9._-]`` (no ``..``) is accepted.”
- `backend/src/hmap/services/artifact/memory.py::check_scope`: `def check_scope(ref: ArtifactRef, project_id: str) -> None`
- `backend/src/hmap/services/artifact/memory.py::verify`: “Return ``data`` if its hash matches both the stored metadata and the caller's ref.”
- `backend/src/hmap/services/artifact/memory.py::make_ref`: `def make_ref(data: bytes, *, scheme: str, project_id: str, artifact_id: str, version: int, artifact_type: str, media_type: str, created_by: str, supersedes: int | None) -> ArtifactRef`
- `backend/src/hmap/services/artifact/memory.py::InMemoryArtifactStore`: “``ArtifactStore`` kept in a dict ``(project_id, artifact_id) -> versions``.”
- `backend/src/hmap/services/artifact/memory.py::InMemoryArtifactStore.__init__`: `def __init__(self) -> None`
- `backend/src/hmap/services/artifact/memory.py::InMemoryArtifactStore.delete_project`: `async def delete_project(self, project_id: str) -> int`
- `backend/src/hmap/services/artifact/memory.py::InMemoryArtifactStore.put`: `async def put(self, data: bytes, *, project_id: str, artifact_type: str, media_type: str, created_by: str, artifact_id: str | None=None) -> ArtifactRef`
- `backend/src/hmap/services/artifact/memory.py::InMemoryArtifactStore.get`: `async def get(self, ref: ArtifactRef, *, project_id: str) -> bytes`
- `backend/src/hmap/services/artifact/memory.py::InMemoryArtifactStore.latest`: `async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None`
- `backend/src/hmap/services/artifact/memory.py::InMemoryArtifactStore.list`: `async def list(self, project_id: str) -> list[ArtifactRef]`

## `backend/src/hmap/services/artifact/pg_meta.py`

“Artifact metadata in Postgres (Sprint 1 item 1.11, research §15/§18): the ``artifacts`` table, unique ``(artifact_id, version)``.”

- `backend/src/hmap/services/artifact/pg_meta.py::PgArtifactMetadata`: `class PgArtifactMetadata`
- `backend/src/hmap/services/artifact/pg_meta.py::PgArtifactMetadata.__init__`: `def __init__(self, db: Database) -> None`
- `backend/src/hmap/services/artifact/pg_meta.py::PgArtifactMetadata.record`: “Insert the metadata row; an existing ``(artifact_id, version)`` -> ``ArtifactConflict`` (write-once).”
- `backend/src/hmap/services/artifact/pg_meta.py::PgArtifactMetadata.get`: `async def get(self, artifact_id: str, version: int, *, project_id: str) -> ArtifactRef | None`
- `backend/src/hmap/services/artifact/pg_meta.py::PgArtifactMetadata.latest`: `async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None`
- `backend/src/hmap/services/artifact/pg_meta.py::PgArtifactMetadata.next_version`: “1 + the highest recorded version (0 rows -> 1).”
- `backend/src/hmap/services/artifact/pg_meta.py::PgArtifactMetadata.list`: “Same order as the stores: ``(created_at, artifact_id, version)``.”

## `backend/src/hmap/services/context/__init__.py`

“hmap package.”


## `backend/src/hmap/services/context/base.py`

“Context service interface (research §13-14, Sprint 1 item 1.10).”

- `backend/src/hmap/services/context/base.py::ContextSnapshot`: `class ContextSnapshot(Contract)`
- `backend/src/hmap/services/context/base.py::ContextStore`: `class ContextStore(Protocol)`
- `backend/src/hmap/services/context/base.py::ContextStore.create`: “New context (version 1) or, with an existing ``context_id``, the next version.”
- `backend/src/hmap/services/context/base.py::ContextStore.get`: `async def get(self, ref: ContextRef) -> ContextSnapshot`
- `backend/src/hmap/services/context/base.py::ContextStore.latest`: `async def latest(self, context_id: str) -> ContextRef`
- `backend/src/hmap/services/context/base.py::ContextStore.is_stale`: “True if a newer version exists (agent must request a rebase: NEEDS_REBASE).”

## `backend/src/hmap/services/context/memory.py`

“In-memory ``ContextStore`` (Sprint 1 item 1.10, research §13-14).”

- `backend/src/hmap/services/context/memory.py::ContextNotFound`: `class ContextNotFound(HmapError)`
- `backend/src/hmap/services/context/memory.py::content_sha256`: “Hash of the canonical JSON form (sorted keys, no whitespace); raises TypeError for non-JSON content.”
- `backend/src/hmap/services/context/memory.py::InMemoryContextStore`: `class InMemoryContextStore`
- `backend/src/hmap/services/context/memory.py::InMemoryContextStore.__init__`: `def __init__(self) -> None`
- `backend/src/hmap/services/context/memory.py::InMemoryContextStore.create`: `async def create(self, project_id: str, content: dict[str, Any], *, author: str, context_id: str | None=None, change_summary: str='') -> ContextRef`
- `backend/src/hmap/services/context/memory.py::InMemoryContextStore.get`: `async def get(self, ref: ContextRef) -> ContextSnapshot`
- `backend/src/hmap/services/context/memory.py::InMemoryContextStore.latest`: `async def latest(self, context_id: str) -> ContextRef`
- `backend/src/hmap/services/context/memory.py::InMemoryContextStore.is_stale`: `async def is_stale(self, ref: ContextRef) -> bool`
- `backend/src/hmap/services/context/memory.py::InMemoryContextStore.history`: “All versions, oldest first (UI / audit).”

## `backend/src/hmap/services/context/pg.py`

“Postgres ``ContextStore`` (Sprint 1 item 1.10; research §13-14) on the ``contexts`` table (PK ``(context_id, version)``).”

- `backend/src/hmap/services/context/pg.py::PostgresContextStore`: `class PostgresContextStore`
- `backend/src/hmap/services/context/pg.py::PostgresContextStore.__init__`: `def __init__(self, db: Database) -> None`
- `backend/src/hmap/services/context/pg.py::PostgresContextStore.create`: `async def create(self, project_id: str, content: dict[str, Any], *, author: str, context_id: str | None=None, change_summary: str='') -> ContextRef`
- `backend/src/hmap/services/context/pg.py::PostgresContextStore.get`: `async def get(self, ref: ContextRef) -> ContextSnapshot`
- `backend/src/hmap/services/context/pg.py::PostgresContextStore.latest`: `async def latest(self, context_id: str) -> ContextRef`
- `backend/src/hmap/services/context/pg.py::PostgresContextStore.is_stale`: `async def is_stale(self, ref: ContextRef) -> bool`
- `backend/src/hmap/services/context/pg.py::PostgresContextStore.history`: “All versions, oldest first (UI / audit).”

## `backend/src/hmap/services/registry/__init__.py`

“hmap package.”


## `backend/src/hmap/services/registry/base.py`

“Agent registry interface (research §19-21, Sprint 1 item 1.9).”

- `backend/src/hmap/services/registry/base.py::AgentRecord`: `class AgentRecord(Contract)`
- `backend/src/hmap/services/registry/base.py::Registry`: `class Registry(Protocol)`
- `backend/src/hmap/services/registry/base.py::Registry.register`: “Validates protocol versions (SchemaUnsupported if none shared) and creates a lease.”
- `backend/src/hmap/services/registry/base.py::Registry.heartbeat`: “Renews the lease; None if the agent is unknown (it must re-register).”
- `backend/src/hmap/services/registry/base.py::Registry.deregister`: `async def deregister(self, agent_id: str, reason: str) -> None`
- `backend/src/hmap/services/registry/base.py::Registry.find_candidates`: “AVAILABLE/BUSY agents with a live lease and free slots; real agents before stubs, then least loaded.”
- `backend/src/hmap/services/registry/base.py::Registry.expire_leases`: “Marks agents with expired leases OFFLINE and returns them (manager then reconciles their executions).”
- `backend/src/hmap/services/registry/base.py::Registry.list`: `async def list(self) -> list[AgentRecord]`

## `backend/src/hmap/services/registry/memory.py`

“In-memory agent registry (Sprint 1 item 1.9; research §16, §19-21).”

- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry`: `class InMemoryRegistry`
- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry.__init__`: `def __init__(self, *, lease_s: float=DEFAULT_LEASE_S, clock: Callable[[], datetime]=utcnow, supported_versions: tuple[str, ...]=SUPPORTED_SCHEMA_VERSIONS) -> None`
- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry.register`: `async def register(self, msg: AgentRegister) -> AgentRecord`
- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry.heartbeat`: `async def heartbeat(self, msg: AgentHeartbeat) -> AgentRecord | None`
- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry.deregister`: `async def deregister(self, agent_id: str, reason: str) -> None`
- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry.find_candidates`: `async def find_candidates(self, capability: str) -> list[AgentRecord]`
- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry.expire_leases`: `async def expire_leases(self, now: datetime | None=None) -> list[AgentRecord]`
- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry.list`: `async def list(self) -> list[AgentRecord]`
- `backend/src/hmap/services/registry/memory.py::InMemoryRegistry.get`: `async def get(self, agent_id: str) -> AgentRecord | None`

## `backend/src/hmap/services/registry/pg.py`

“Postgres agent registry (Sprint 1 item 1.9; research §16, §19-21) on the ``agents`` table.”

- `backend/src/hmap/services/registry/pg.py::PostgresRegistry`: `class PostgresRegistry`
- `backend/src/hmap/services/registry/pg.py::PostgresRegistry.__init__`: `def __init__(self, db: Database, *, lease_s: float=DEFAULT_LEASE_S, clock: Callable[[], datetime]=utcnow, supported_versions: tuple[str, ...]=SUPPORTED_SCHEMA_VERSIONS) -> None`
- `backend/src/hmap/services/registry/pg.py::PostgresRegistry.register`: `async def register(self, msg: AgentRegister) -> AgentRecord`
- `backend/src/hmap/services/registry/pg.py::PostgresRegistry.heartbeat`: `async def heartbeat(self, msg: AgentHeartbeat) -> AgentRecord | None`
- `backend/src/hmap/services/registry/pg.py::PostgresRegistry.deregister`: `async def deregister(self, agent_id: str, reason: str) -> None`
- `backend/src/hmap/services/registry/pg.py::PostgresRegistry.find_candidates`: `async def find_candidates(self, capability: str) -> list[AgentRecord]`
- `backend/src/hmap/services/registry/pg.py::PostgresRegistry.expire_leases`: `async def expire_leases(self, now: datetime | None=None) -> list[AgentRecord]`
- `backend/src/hmap/services/registry/pg.py::PostgresRegistry.list`: `async def list(self) -> list[AgentRecord]`
- `backend/src/hmap/services/registry/pg.py::PostgresRegistry.get`: `async def get(self, agent_id: str) -> AgentRecord | None`

## `backend/src/hmap/system.py`

“Composition root: builds the whole platform in one process.”

- `backend/src/hmap/system.py::SystemConfig`: `class SystemConfig`
- `backend/src/hmap/system.py::Persistence`: “Everything durable.”
- `backend/src/hmap/system.py::in_memory_persistence`: `def in_memory_persistence(lease_s: float) -> Persistence`
- `backend/src/hmap/system.py::postgres_persistence`: `def postgres_persistence(database_url: str, lease_s: float) -> Persistence`
- `backend/src/hmap/system.py::HmapSystem`: `class HmapSystem`
- `backend/src/hmap/system.py::HmapSystem.__init__`: `def __init__(self, *, bus: Bus, artifacts: ArtifactStore, llm: LLMClient, plugins: list[Plugin], config: SystemConfig | None=None, persistence: Persistence | None=None) -> None`
- `backend/src/hmap/system.py::HmapSystem.in_memory`: `def in_memory(cls, *, artifact_root: Path | None=None, llm: LLMClient | None=None, plugins: list[Plugin] | None=None, config: SystemConfig | None=None) -> 'HmapSystem'`
- `backend/src/hmap/system.py::HmapSystem.from_settings`: `def from_settings(cls, settings: Settings, *, config: SystemConfig | None=None, rabbit_namespace: str='', plugins: list[Plugin] | None=None) -> 'HmapSystem'`
- `backend/src/hmap/system.py::HmapSystem.start`: `async def start(self, *, with_agents: bool=True, migrate: bool=True) -> None`
- `backend/src/hmap/system.py::HmapSystem.start_agents`: `async def start_agents(self, plugins: list[Plugin] | None=None) -> AgentHost`
- `backend/src/hmap/system.py::HmapSystem.stop`: `async def stop(self) -> None`

## `infra/observability/grafana/build_dashboard.py`

“Writes ``dashboards/hmap.json`` (the committed Grafana dashboard, Sprint 4 item 4.17).”

- `infra/observability/grafana/build_dashboard.py::panel`: `def panel(title: str, exprs: list[tuple[str, str]], *, x: int, y: int, w: int=12, h: int=8, kind: str='timeseries', unit: str='short', description: str='', stack: bool=False, thresholds: list[tuple[str, float | None]] | None=None) -> dict`
- `infra/observability/grafana/build_dashboard.py::row`: `def row(title: str, y: int) -> dict`

## `infra/observability/load/soak.py`

“Load / soak test (Sprint 4 item 4.20; reused by Member 11's release gate): N projects at once on the stub agents.”

- `infra/observability/load/soak.py::plan`: `def plan(pid: str) -> TaskGraph`
- `infra/observability/load/soak.py::Sampler`: `class Sampler`
- `infra/observability/load/soak.py::Sampler.__init__`: `def __init__(self, system: HmapSystem) -> None`
- `infra/observability/load/soak.py::Sampler.start`: `def start(self) -> None`
- `infra/observability/load/soak.py::Sampler.stop`: `async def stop(self) -> None`
- `infra/observability/load/soak.py::one_project`: `async def one_project(system: HmapSystem, n: int, gate: asyncio.Semaphore, timeout: float) -> dict[str, Any]`
- `infra/observability/load/soak.py::run`: `async def run(args: argparse.Namespace) -> dict[str, Any]`
- `infra/observability/load/soak.py::main`: `def main() -> int`

## `scripts/cloud_check.py`

“Cloud key-pool check (doc 02 §2.5): does every cloud route in the role map still answer, and which keys work?”

- `scripts/cloud_check.py::check_keys`: `async def check_keys(settings: Settings, client: httpx.AsyncClient) -> None`
- `scripts/cloud_check.py::check_routes`: `async def check_routes(settings: Settings, client: httpx.AsyncClient) -> bool`
- `scripts/cloud_check.py::main`: `async def main() -> int`

## `scripts/demo_chaos.py`

“Failure-injection rounds against the running `make demo` stack (see demo_chaos.sh).”

- `scripts/demo_chaos.py::kill_agents`: `def kill_agents() -> int`
- `scripts/demo_chaos.py::one_round`: `def one_round(n: int) -> bool`
- `scripts/demo_chaos.py::main`: `def main() -> None`

## `scripts/demo_preflight.py`

“Pre-flight check of `make demo` (Sprint 9 item 9.16): is this laptop ready to run the whole platform?”

- `scripts/demo_preflight.py::Check`: `class Check`
- `scripts/demo_preflight.py::env_file`: `def env_file() -> dict[str, str]`
- `scripts/demo_preflight.py::setting`: `def setting(name: str, file: dict[str, str]) -> str`
- `scripts/demo_preflight.py::port_busy`: `def port_busy(port: int) -> bool`
- `scripts/demo_preflight.py::free_ram_gb`: “Memory available without swapping: free + inactive + speculative pages (macOS), MemAvailable (Linux).”
- `scripts/demo_preflight.py::http_json`: `def http_json(url: str, timeout: float=2.0) -> object`
- `scripts/demo_preflight.py::ours_running`: `def ours_running() -> bool`
- `scripts/demo_preflight.py::check_tools`: `def check_tools(which: Callable[[str], str | None]=shutil.which) -> list[Check]`
- `scripts/demo_preflight.py::check_ports`: `def check_ports(busy: Callable[[int], bool]=port_busy, infra_ours: Callable[[], bool]=ours_running) -> list[Check]`
- `scripts/demo_preflight.py::key_count`: `def key_count(file: dict[str, str]) -> int`
- `scripts/demo_preflight.py::check_ram`: `def check_ram(mode: str, free: float | None, minimum: float | None=None, *, keys: int=0) -> Check`
- `scripts/demo_preflight.py::check_disk`: `def check_disk(path: Path=ROOT) -> Check`
- `scripts/demo_preflight.py::check_model`: `def check_model(mode: str, file: dict[str, str], fetch: Callable[[str], object]=http_json) -> list[Check]`
- `scripts/demo_preflight.py::check_extras`: `def check_extras(file: dict[str, str]) -> list[Check]`
- `scripts/demo_preflight.py::run`: `def run(mode: str) -> list[Check]`
- `scripts/demo_preflight.py::main`: `def main() -> int`

## `scripts/demo_sprint_1.py`

“Sprint 1 demo (DoD): upload a document -> stub pipeline -> human approval -> all tasks complete, all over the API.”

- `scripts/demo_sprint_1.py::call`: `def call(method: str, path: str, body: dict | None=None, raw: bytes | None=None, content_type: str='application/json') -> dict | list`
- `scripts/demo_sprint_1.py::sign_up`: `def sign_up(name: str, email: str, password: str) -> None`
- `scripts/demo_sprint_1.py::wait`: `def wait(path: str, pred, what: str, timeout: float=60) -> dict`
- `scripts/demo_sprint_1.py::main`: `def main() -> None`

## `scripts/demo_sprint_2.py`

“Sprint 2 demo (Member 2, document intelligence): upload documents -> requirements with sources, over the API.”

- `scripts/demo_sprint_2.py::upload`: “``files``: (relative path incl.”
- `scripts/demo_sprint_2.py::check`: `def check(ok: bool, what: str) -> None`
- `scripts/demo_sprint_2.py::show`: `def show(rs: dict) -> None`
- `scripts/demo_sprint_2.py::run_project`: `def run_project(name: str, files: list[tuple[str, Path]]) -> tuple[str, dict]`
- `scripts/demo_sprint_2.py::main`: `def main() -> None`

## `scripts/demo_sprint_3.py`

“Sprint 3 demo (Member 3, planning): PDF -> requirements -> plan -> edit -> approve -> steps run in dependency order (independent ones at the same time) -> replan with feedback, all over the API.”

- `scripts/demo_sprint_3.py::plan_of`: `def plan_of(pid: str) -> dict`
- `scripts/demo_sprint_3.py::show`: `def show(plan: dict) -> None`
- `scripts/demo_sprint_3.py::events`: `def events(pid: str) -> list[dict]`
- `scripts/demo_sprint_3.py::run_order_checks`: `def run_order_checks(pid: str) -> None`
- `scripts/demo_sprint_3.py::main`: `def main() -> None`

## `scripts/demo_sprint_4.py`

“Sprint 4 demo (Member 4: self-reflection & refinement + observability), all over the API.”

- `scripts/demo_sprint_4.py::runs`: `def runs(pid: str) -> list[dict]`
- `scripts/demo_sprint_4.py::timeline`: `def timeline(pid: str, summary: dict) -> dict`
- `scripts/demo_sprint_4.py::events`: `def events(pid: str) -> list[dict]`
- `scripts/demo_sprint_4.py::checked_project`: `def checked_project(name: str, files: list[tuple[str, Path]]) -> str`
- `scripts/demo_sprint_4.py::jaeger_trace`: `def jaeger_trace(trace_id: str) -> dict`
- `scripts/demo_sprint_4.py::prometheus_alerts`: `def prometheus_alerts() -> list[dict]`
- `scripts/demo_sprint_4.py::main`: `def main() -> None`

## `scripts/demo_sprint_5.py`

“Sprint 5 demo (Member 5: autonomous research), all over the API, offline (cached corpus + recorded answers).”

- `scripts/demo_sprint_5.py::events`: `def events(pid: str) -> list[dict]`
- `scripts/demo_sprint_5.py::show`: `def show(pid: str, task_id: str) -> dict`
- `scripts/demo_sprint_5.py::quotes_verified`: `def quotes_verified(pid: str, task_id: str, report: dict) -> tuple[int, int]`
- `scripts/demo_sprint_5.py::main`: `def main() -> None`

## `scripts/demo_sprint_6.py`

“Sprint 6 demo (Member 6: research verification + security), all over the API, offline (recorded answers).”

- `scripts/demo_sprint_6.py::show_check`: `def show_check(pid: str, task_id: str) -> dict`
- `scripts/demo_sprint_6.py::main`: `def main() -> None`

## `scripts/demo_sprint_7.py`

“Sprint 7 demo (Member 7: autonomous coding), all over the API, offline (recorded answers).”

- `scripts/demo_sprint_7.py::show_run`: `def show_run(pid: str, task_id: str) -> dict`
- `scripts/demo_sprint_7.py::main`: `def main() -> None`

## `scripts/demo_sprint_8.py`

“Sprint 8 demo (Member 8: automated testing & execution), all over the API, offline (recorded answers).”

- `scripts/demo_sprint_8.py::show`: `def show(pid: str, task_id: str) -> dict`
- `scripts/demo_sprint_8.py::main`: `def main() -> None`

## `scripts/demo_sprint_9.py`

“Sprint 9 demo (Member 9: technical documentation), all over the API, offline (recorded answers).”

- `scripts/demo_sprint_9.py::code`: `def code() -> dict[str, str]`
- `scripts/demo_sprint_9.py::run`: `def run(pid: str, capability: str, objective: str, files: dict[str, str]) -> dict`
- `scripts/demo_sprint_9.py::show`: `def show(d: dict) -> None`
- `scripts/demo_sprint_9.py::main`: `def main() -> None`

## `scripts/finetune_trial.py`

“Fine-tune TRIAL (process rehearsal for Sprint 11): LoRA on a small model with test-verified data.”

- `scripts/finetune_trial.py::unload_ollama`: “Free RAM before MLX work: ask Ollama to unload every resident model.”
- `scripts/finetune_trial.py::cmd_prepare`: `def cmd_prepare(args) -> None`
- `scripts/finetune_trial.py::cmd_train`: `def cmd_train(args) -> None`
- `scripts/finetune_trial.py::cmd_eval`: `def cmd_eval(args) -> None`
- `scripts/finetune_trial.py::main`: `def main() -> None`

## `scripts/hmaptools/__init__.py`

“Team tooling (owner: Member 1): tree manifests, ownership checks, regression attribution.”


## `scripts/hmaptools/ownership.py`

“Map changed files to owners using ownership.toml and flag edits outside a member's own paths.”

- `scripts/hmaptools/ownership.py::Ownership`: `class Ownership`
- `scripts/hmaptools/ownership.py::Ownership.load`: `def load(cls, path: Path) -> 'Ownership'`
- `scripts/hmaptools/ownership.py::Ownership.owner`: “Most specific matching pattern wins (frontend/src/features/doc_intel/** beats frontend/**).”
- `scripts/hmaptools/ownership.py::Ownership.classify`: “own | common | cross_cutting (needs Member 1 sign-off) | shared (Member 1's, needs sign-off) | foreign (another member's path: error) | unowned (no rule: needs a new ownership entry).”
- `scripts/hmaptools/ownership.py::OwnershipReport`: `class OwnershipReport`
- `scripts/hmaptools/ownership.py::OwnershipReport.errors`: `def errors(self) -> list[tuple[str, str, int | None]]`
- `scripts/hmaptools/ownership.py::OwnershipReport.needs_signoff`: `def needs_signoff(self) -> list[tuple[str, str, int | None]]`
- `scripts/hmaptools/ownership.py::check`: `def check(own: Ownership, member: int, changed: list[str]) -> OwnershipReport`

## `scripts/hmaptools/pytest_results.py`

“Tiny pytest plug-in (no dependencies): writes {nodeid: outcome} to $HMAP_RESULTS_JSON.”

- `scripts/hmaptools/pytest_results.py::pytest_runtest_logreport`: `def pytest_runtest_logreport(report: Any) -> None`
- `scripts/hmaptools/pytest_results.py::pytest_sessionfinish`: `def pytest_sessionfinish(session: Any, exitstatus: int) -> None`

## `scripts/hmaptools/regression.py`

“Regression attribution: run the same test suite on a BASE tree and on the CURRENT tree and classify every test.”

- `scripts/hmaptools/regression.py::RunResult`: `class RunResult`
- `scripts/hmaptools/regression.py::Classified`: `class Classified`
- `scripts/hmaptools/regression.py::copy_tree`: “Copy a source tree without environments/caches/data so tests run in a clean, isolated copy.”
- `scripts/hmaptools/regression.py::export_git_ref`: “Read-only export of a git ref (no checkout, no commit, no change to the repo).”
- `scripts/hmaptools/regression.py::run_pytest`: `def run_pytest(tree: Path, args: list[str], scripts_dir: Path, *, label: str, timeout_s: int=3600) -> RunResult`
- `scripts/hmaptools/regression.py::classify`: `def classify(base: dict[str, str], current: dict[str, str]) -> list[Classified]`
- `scripts/hmaptools/regression.py::confirm_with_reruns`: “Re-run suspicious tests on both trees; any inconsistency => FLAKY (not attributable to the change).”
- `scripts/hmaptools/regression.py::environment`: `def environment() -> dict[str, str]`
- `scripts/hmaptools/regression.py::summarize`: `def summarize(items: list[Classified]) -> dict[str, int]`
- `scripts/hmaptools/regression.py::verdict`: `def verdict(items: list[Classified]) -> tuple[bool, str]`

## `scripts/hmaptools/report.py`

“Markdown + JSON report for a regression check (attach it to the commit / handoff).”

- `scripts/hmaptools/report.py::likely_cause`: “Point at the changed files that most likely broke the tests (heuristic, never a verdict by itself).”
- `scripts/hmaptools/report.py::render`: `def render(*, base_label: str, items: list[Classified], tree_diff: TreeDiff, own: Ownership | None, own_report: OwnershipReport | None, env: dict[str, str], timings: dict[str, float], out_dir: Path) -> tuple[Path, Path]`

## `scripts/hmaptools/secrets.py`

“Secret scan: fail if anything that looks like a real API key / private key is in the project tree.”

- `scripts/hmaptools/secrets.py::Finding`: `class Finding`
- `scripts/hmaptools/secrets.py::scan`: `def scan(root: Path) -> list[Finding]`

## `scripts/hmaptools/tree.py`

“Snapshot a project tree as {relative_path: sha256} so two folders (or a folder and a git ref) can be compared without git.”

- `scripts/hmaptools/tree.py::is_excluded`: `def is_excluded(rel: str) -> bool`
- `scripts/hmaptools/tree.py::sha256_file`: `def sha256_file(path: Path) -> str`
- `scripts/hmaptools/tree.py::manifest`: `def manifest(root: Path) -> dict[str, str]`
- `scripts/hmaptools/tree.py::load_manifest`: “Use MANIFEST.json if the folder is a handoff snapshot, else compute it.”
- `scripts/hmaptools/tree.py::TreeDiff`: `class TreeDiff`
- `scripts/hmaptools/tree.py::TreeDiff.changed`: `def changed(self) -> list[str]`
- `scripts/hmaptools/tree.py::TreeDiff.to_dict`: `def to_dict(self) -> dict[str, list[str]]`
- `scripts/hmaptools/tree.py::diff`: `def diff(base: dict[str, str], current: dict[str, str]) -> TreeDiff`
- `scripts/hmaptools/tree.py::write_manifest`: `def write_manifest(root: Path, extra: dict[str, object] | None=None) -> Path`

## `scripts/llm_check.py`

“LLM gateway smoke test (Sprint 1 DoD: "answers in live and replay modes").”

- `scripts/llm_check.py::Verdict`: `class Verdict(BaseModel)`
- `scripts/llm_check.py::run`: `async def run(settings: Settings, mode: str) -> dict`
- `scripts/llm_check.py::main`: `def main() -> int`

## `scripts/make_handoff.py`

“Make the folder snapshot that goes to the next member (doc 03 §2).”


## `scripts/model_bakeoff.py`

“Model bake-off: score local Ollama models on small samples of hmap's real work.”

- `scripts/model_bakeoff.py::Requirement`: `class Requirement(BaseModel)`
- `scripts/model_bakeoff.py::Constraint`: `class Constraint(BaseModel)`
- `scripts/model_bakeoff.py::Deliverable`: `class Deliverable(BaseModel)`
- `scripts/model_bakeoff.py::Criterion`: `class Criterion(BaseModel)`
- `scripts/model_bakeoff.py::Extraction`: `class Extraction(BaseModel)`
- `scripts/model_bakeoff.py::PlanTask`: `class PlanTask(BaseModel)`
- `scripts/model_bakeoff.py::Plan`: `class Plan(BaseModel)`
- `scripts/model_bakeoff.py::Issue`: `class Issue(BaseModel)`
- `scripts/model_bakeoff.py::Critique`: `class Critique(BaseModel)`
- `scripts/model_bakeoff.py::Verdict`: `class Verdict(BaseModel)`
- `scripts/model_bakeoff.py::code_user`: `def code_user(task_md: str) -> str`
- `scripts/model_bakeoff.py::chat`: `def chat(model: str, system: str, user: str, schema: type[BaseModel] | None, *, temperature: float=0.0, seed: int=42, num_predict: int=2048) -> dict`
- `scripts/model_bakeoff.py::chat_messages`: “Multi-turn chat (fix loop).”
- `scripts/model_bakeoff.py::cmd_coding_loop`: “Coding with test feedback: attempt, run hidden tests, on failure send the pytest output back (<= N rounds).”
- `scripts/model_bakeoff.py::metrics`: `def metrics(resp: dict) -> dict`
- `scripts/model_bakeoff.py::resident_gb`: `def resident_gb(model: str) -> float | None`
- `scripts/model_bakeoff.py::parse`: `def parse(content: str, schema: type[BaseModel])`
- `scripts/model_bakeoff.py::norm`: `def norm(s: str) -> str`
- `scripts/model_bakeoff.py::matches`: `def matches(gold_item: dict, texts: list[str]) -> bool`
- `scripts/model_bakeoff.py::score_extraction`: `def score_extraction(doc: str, gold: dict, ex: Extraction) -> dict`
- `scripts/model_bakeoff.py::ancestors`: `def ancestors(tid: str, deps: dict[str, list[str]]) -> set[str]`
- `scripts/model_bakeoff.py::score_planning`: `def score_planning(item: dict, plan: Plan) -> dict`
- `scripts/model_bakeoff.py::score_critique`: `def score_critique(item: dict, c: Critique) -> dict`
- `scripts/model_bakeoff.py::score_verify`: `def score_verify(item: dict, v: Verdict) -> dict`
- `scripts/model_bakeoff.py::extract_code`: `def extract_code(content: str) -> str`
- `scripts/model_bakeoff.py::run_tests`: `def run_tests(task_dir: Path, code: str, workdir: Path) -> dict`
- `scripts/model_bakeoff.py::load_items`: `def load_items(suite: str) -> list[dict]`
- `scripts/model_bakeoff.py::run_item`: `def run_item(model: str, suite: str, item: dict, mdir: Path) -> dict`
- `scripts/model_bakeoff.py::safe`: `def safe(model: str) -> str`
- `scripts/model_bakeoff.py::cmd_run`: `def cmd_run(args) -> None`
- `scripts/model_bakeoff.py::cmd_speed`: “Clean speed pass (run when nothing else is downloading/heavy): median of 3 runs per model.”
- `scripts/model_bakeoff.py::cmd_rescore`: “Recompute scores of the JSON suites from stored outputs (no model calls) after a scoring fix.”
- `scripts/model_bakeoff.py::cmd_report`: `def cmd_report(args) -> None`
- `scripts/model_bakeoff.py::cmd_gen_data`: “Fine-tune trial data: sample N solutions per TRAIN coding task, keep only those passing the hidden tests.”
- `scripts/model_bakeoff.py::main`: `def main() -> None`

## `scripts/ownership_check.py`

“Check that a change only touches the given member's paths (ownership.toml).”

- `scripts/ownership_check.py::main`: `def main() -> int`

## `scripts/precommit.py`

“Run every check a professional would run before committing / handing off, and print one summary table.”

- `scripts/precommit.py::port_open`: `def port_open(port: int) -> bool`
- `scripts/precommit.py::run`: `def run(name: str, cmd: list[str], cwd: Path, results: list[tuple[str, str, float, str]]) -> bool`
- `scripts/precommit.py::main`: `def main() -> int`

## `scripts/regression_check.py`

“Prove whether YOUR change broke a test: run the backend test suite on a base tree and on your tree and compare.”

- `scripts/regression_check.py::main`: `def main() -> int`

## `scripts/secret_scan.py`

“Fail (exit 1) if a real-looking secret is anywhere in the project tree (excluding .env).”


## `scripts/security_check.py`

“Security checks (Sprint 6, Member 6).”

- `scripts/security_check.py::fp`: `def fp(s: str) -> str`
- `scripts/security_check.py::env_secrets`: `def env_secrets() -> list[str]`
- `scripts/security_check.py::leak_scan`: `def leak_scan() -> tuple[bool, str]`
- `scripts/security_check.py::run`: `def run(cmd: list[str], cwd: Path) -> tuple[int, str]`
- `scripts/security_check.py::pip_audit`: `def pip_audit() -> tuple[str, str]`
- `scripts/security_check.py::npm_audit`: `def npm_audit() -> tuple[str, str]`
- `scripts/security_check.py::listeners`: `def listeners() -> tuple[bool, str]`
- `scripts/security_check.py::main`: `def main() -> int`

## `scripts/seed.py`

“Seed a running platform for a live demo: sign in (creating the account the first time), create a project, upload the sample assignment and stop at the human approval gate, so the presenter approves the plan in the dashboard and the audience”

- `scripts/seed.py::main`: `def main() -> None`
