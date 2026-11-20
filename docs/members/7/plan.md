# Sprint 7 plan of action — Member 7: Autonomous coding

Spec: [`docs/sprints/sprint-07-member7-autonomous-coding.md`](../../sprints/sprint-07-member7-autonomous-coding.md)
(items 7.1–7.15). Research: [`research.md`](research.md). Prototypes: [`samples/coding/`](../../../samples/coding/README.md).
Written 2026-10-24 against the code as handed over after Sprint 6 (`check_sprint.sh 6` PASS, 2026-10-24).

**Status (2026-10-24): approved.** Member 1 accepted the defaults for Q1–Q6 (§1): Q1 per-project workspace head,
Q2 `make coding-venv`, Q3 best-effort macOS `sandbox-exec`, Q4 `code.revise` as a normal task with no automatic
test→revise loop, Q5 Member 7 switches on Member 6's injection test, Q6 `[cross_cutting] 7` rows in `ownership.toml`
(added).

**Status (2026-10-25): built.** See [README](README.md), [design](design.md), [eval](eval.md),
[testing](testing.md). Differences from this plan, found while building (details: design §9):
- Reflexion notes are rule-made (Member 4's `ReflectionMemory` needs critique objects the loop does not have);
  Member 4's stop policies and `Refiner` are used as planned.
- The locator fuses BM25 and embeddings with **weights** (1.0 / 0.35): equal weights let weak embeddings outvote a
  correct BM25 hit.
- An edit whose REPLACE equals its SEARCH is refused, and `success` needs a change (or the model's explicit "no
  change needed"): the first demo run showed both kinds of hollow "success".
- Command output also loses Python temp-file names (a pytest traceback printed a new `tmpXXXX.txt` each run and the
  replay missed).
- `make coding-venv` pins the backend's own package versions (the Homebrew Python had a broken starlette/httpx pair).

The sprint in one line: a real `code.implement` + `code.revise` agent that starts from a workspace, finds the files
to change, edits them with SEARCH/REPLACE blocks, runs local checks in a jailed runner, debugs a bounded number of
rounds and returns a `CodeChangeSet` (+ workspace tarball, patch and a tool-call trace), with a UI tab that shows the
tool log and the diff.

---

## 0. What already exists (checked in the code)

| Thing | Where | State |
|---|---|---|
| `CodeChangeSet`, `CommandRun` | `core/contracts/domain.py:348-361` | done (Sprint 1). Matches spec §7 |
| `TestReport` / `TestFailure` (what M8 will send back) | `domain.py:364-393` | done. Categories SYNTAX…ENV, file/line/hint |
| `RevisionPlan` (M10) / `RevisionRequest` message | `domain.py:440`, `core/contracts/messages.py:65` | contracts only — see trap T1 |
| Capabilities `code.implement`, `code.revise` | `core/contracts/capabilities.py:16-17` | names exist; `code.implement` → `code-change-set` in `CAPABILITY_OUTPUTS`; `code.revise` has no output entry |
| `code.completed` event | `core/contracts/events.py:57` | defined, nobody emits it |
| `CodeImplementStub` (priority 0) | `agents/stubs/agents.py:129` | yields once a real plug-in exists. **No stub for `code.revise`** |
| Plans that create code tasks | `agents/planning/templates.py` (Member 3) | software plans: `research → verify → design (code.implement: "set up the project skeleton") → implement per part (code.implement, in parallel, each depends on design) → test per part (test.run) → document → review` |
| Upstream artifacts handed to a task | `manager.py:1202` `_dependency_artifacts` | direct dependencies' result refs only (the implement task gets the design task's artifacts) |
| `ManagerHandle.create_task` / hooks / `ManagerDep` in routers | `core/plugins.py`, `api/routers/projects.py` | how Member 6 creates follow-up tasks from a hook and from an API button — same pattern for `code.revise` |
| `TaskResult.outcome` = `success` / `partial` / `failure` | `messages.py:50` | Manager treats `partial` as completed (downstream continues), `failure` → retry/DLQ |
| Gateway | `core/llm/base.py:49` `generate(role, messages, schema=, max_tokens=, temperature=, seed=)`, `embed`, `classify` | **no native tool calling** → the loop asks for JSON actions (schema) or SEARCH/REPLACE text |
| Local context window | `config.py:149` `ollama_num_ctx = 8192` | the local `coder` (`qwen3.5:9b`) sees ≤ 8k tokens: budget ≈ 5.5k prompt + 1k answer |
| `coder` cloud routes | `config.py:33` `DEFAULT_CLOUD_ROLE_MAP` | groq gpt-oss-120b → gemini flash, then local |
| M4 refine library | `agents/refine/` (`Refiner`, `ProgrammaticCritic`, `LLMRubricCritic`, `ReflectionMemory`, `StopPolicy`: `MaxIters`, `TestsPass`, `Plateau`, `Budget`, `any_of`) + `docs/members/4/integration.md` | ready to use for 7.7 / 7.11 |
| M5 helpers | `agents/research/sanitize.py` (`wrap`, `looks_injected`, `clean_text`), `agents/research/index.py` `HybridIndex` | reusable for F3 + embeddings |
| M6 security | `core/policy.py` (signed envelopes, policy table), `scripts/security_check.sh` (runs inside `check_sprint.sh` from Sprint 6 on) | nothing to add for a new capability; injection suite waits for Member 7 (trap T3) |
| Prep package | `samples/coding/`: 12 verified-fair tasks (`task.json`, `starter/`, `hidden_tests/`, `gold.edits`), `workspace.py` (jail + allow-listed runner, 32/32 checks), `edits.py` (SEARCH/REPLACE applicator), `locate.py` (BM25, top-1 7/7), `check_benchmark.py` | stdlib prototypes, **not** importable from `hmap` → port into `agents/coding/` |
| Optional extra `coding = ["langgraph>=0.2"]` | `backend/pyproject.toml:42` | available, not required (D7) |
| Demo input | `samples/demo/tcp_chat_assignment.pdf` (+ `.txt`) | the mid-eval storyline project; Sprint 7 demo reuses it |
| Ownership | `ownership.toml` `[members.7]` | `agents/coding/**`, `tests/coding/**`, `features/coding/**`, `docs/members/7/**`, `samples/coding/**`, `samples/llm_cache/coding/**`, `alembic/versions/007_*`. **No `[cross_cutting] 7` row** (Q6) |

### Traps found while reading the code (each one is handled by a decision below)
| # | Trap | Handled by |
|---|---|---|
| T1 | Nobody delivers a `revision.request` message: the Manager never sends one and the agent runtime has no handler for it. A `code.revise` that waits for that message would never run | D14: `code.revise` is an ordinary **task** created with `ManagerHandle.create_task` (API button now, M8/M10 later) |
| T2 | The `test.run` **stub returns `passed=false`** (its canned example has a failing unit stage). A hook "on failed test → revise" would start a revision in every project | D15: no test-result hook in Sprint 7; Member 8 owns the loop (8.9) |
| T3 | `tests/verify/security/test_injection.py::test_repository_entry_points_are_switched_on_when_real` **fails on purpose** as soon as `code.implement` is real, until Member 7 runs `samples/verify/injection/repo/` through the coding reader (HANDOFF Sprint 6, finding F3) | D22 + Q5 |
| T4 | Every older demo / e2e test (`demo_sprint_3…6`, `make demo`, `tests/e2e/test_full_stack.py`) will now run the **real** coding agent: in `replay` its calls are not recorded → `ReplayMissError`; in `fake` it gets canned answers | D18 (degrade, never crash) + record the storyline (step 27) |
| T5 | Model-written code that the runner executes is **not** jailed by `workspace.py` (only the agent's tools are): `open("../../../.env")` or `import hmap` (which reads `<repo>/.env`) would leak team keys | D4 (workspaces outside the repo) + D6 (separate interpreter, scrubbed env, macOS sandbox) + security tests |
| T6 | Replay keys hash the whole prompt: temp paths, durations ("Ran 3 tests in 0.002s"), execution ids or unsorted listings in a prompt → a miss on every run | D19 |
| T7 | Wall-clock budgets make replay nondeterministic (Sprint 5 trap) | D11: decisions use steps/tokens; wall clock is only a safety abort |
| T8 | Parallel implement parts all start from the design workspace → the project's code ends up spread over N workspaces; docs/review need one tree | D2 + Q1 |
| T9 | The team `.gitignore` ignores `samples/llm_cache/` and every `CONTRIBUTING.md` (Sprint 6 trap) | recordings + the injection repo need `git add -f` (commit notes) |
| T10 | Agents must honour `stub_fail` / `stub_delay_s` (Member 4's and the chaos tests inject failures by capability) | D20 |

---

## 1. Decisions (please confirm or change)

| # | Decision | Why |
|---|---|---|
| D1 | **Where a task's workspace starts**, first match wins: (a) `inputs.workspace_ref` (benchmark, demo, API); (b) the project's workspace head (D2); (c) the newest `workspace` artifact among `artifact_refs` (upstream changeset); (d) empty → a template (D8) | every plan step and the benchmark use one path |
| D2 | **Project workspace head** `wsh-<project_id>` (versioned artifact). A code task starts from the current head and, when done, writes its result as the new head. If the head moved while it ran (a second coding agent in split mode), its patch is re-applied on the new head; on conflict it redoes the edit once on the new head, else `partial` with the conflict in `notes`. `CodeChangeSet.workspace_ref` = the full tree after this task; `patch_ref` = **only this task's diff** | parallel parts end in one tree that M8/M9/M10 can use; no contract change (see Q1) |
| D3 | **Artifacts** (first one = the contract output, as `CAPABILITY_OUTPUTS` requires): `code-change-set` `ccs-<task_id>`; `workspace` `ws-<task_id>` (`application/gzip` tar, ≤ 5 MB, ≤ 500 files, no `__pycache__`/`.git`/`.env`); `code-patch` `patch-<task_id>` (`text/x-diff`, unified diff from `difflib`, no git needed); `coding-trace` `ct-<task_id>` (steps, tool calls, edits applied/rejected + reason, commands + exit codes, tokens, stop reason, base used) | same pattern as M5/M6 report + trace |
| D4 | Workspaces live **outside the project folder**: `HMAP_CODING_WORK_DIR` (default `$TMPDIR/hmap-coding/<project>/<task>/<execution>`), deleted after packaging (kept with `HMAP_CODING_KEEP_WORK=1` for debugging). Never under `data/` or anywhere a relative `..` reaches `.env` | trap T5 |
| D5 | **Runner** = port of `samples/coding/workspace.py`: argv only (no shell); allow-list `python -I -m py_compile`, `python -I -m unittest`, `python -I -m pytest` (if the interpreter has it), `ruff check --select E9,F` (the backend's ruff binary: it reads code, never runs it), `python -I <script inside the workspace>`; scrubbed env (no `HMAP_*`, no `*_API_KEY*`, `HOME`=workspace, minimal `PATH`); 20 s per command (60 s max), output capped at 10 KB for the model and 64 KB in the trace; every denial is audited in the trace and logged as `coding.denied` | 7.1, 7.4 |
| D6 | **Interpreter for model-written code** = `HMAP_CODING_PYTHON` (default: the base Python 3.11 under the venv, i.e. no `hmap`, no backend packages). Optional `make coding-venv` builds `data/coding/venv` with pinned `pytest`, `fastapi`, `httpx` for the templates (Q2). On macOS the command is wrapped in `sandbox-exec` (deny network, deny reading the project folder and `~`) when `HMAP_CODING_SANDBOX=auto` (default) — best effort until Member 8's Docker runner (Q3) | trap T5; generated code must never import `hmap` or read `.env` |
| D7 | **Loop without LangGraph**: a plain async state machine in `loop.py` — understand → locate → plan → edit → check → debug → package. Fewer dependencies, easy to replay and test with `FakeLLM`; LangGraph stays an optional extra nobody needs | doc 01 §3 makes it optional; Agentless shape (research §1) |
| D8 | **Templates** (7.10): `python_package`, `fastapi_service`, `tcp_server_client`, `cli` as plain folders in `agents/coding/templates/<name>/` + `template.json` (keywords, description, entry points). Chosen by keyword rules on objective + criteria, `classify` only if no rule matches. Each template ships its own smoke tests, and a unit test proves every template passes them | greenfield design step bootstraps without the model |
| D9 | **Locator** (7.3): BM25 (prototype) + embeddings (`ctx.llm.embed`, cached by file sha256) fused with RRF; LLM rerank (role `fast`, JSON list of paths) of the top 6 only when the repo has > 8 files. Repo map (7.2) = `ast` symbols (classes, functions, signatures, first docstring line) per file, incremental by file hash | research §2; tree-sitter not needed for Python-only |
| D10 | **Context budget** (7.8): prompt ≤ `HMAP_CODING_PROMPT_TOKENS` (default 5,500; answer 1,024) for every route, so local and cloud prompts are identical (replay) and fit the 8k local window. Token estimate = chars / 3 (conservative). Priority: task + criteria → latest failure output → target file slices (whole file if ≤ 150 lines, else ±30 lines around located symbols) → repo map → other summaries; lower priorities are cut first. Asserted on every call | 7.8 "never exceeds limit" |
| D11 | **Debug loop** (7.7): parse traceback / unittest / pytest / ruff output with rules → (file, line, exception) → show that slice → model gives one hypothesis + SEARCH/REPLACE edit → re-run. Reflexion note (M4 `ReflectionMemory`) carried between rounds. Stop = M4 `any_of(TestsPass, MaxIters(4), Plateau, Budget(tokens))` + hard caps (12 model steps per task, 300 s wall clock as a safety abort only) | research §4; trap T7 |
| D12 | **What the agent checks itself**: `py_compile` of changed files, `ruff --select E9,F`, existing tests in the workspace, an import smoke test of changed modules. It does **not** write test suites (Member 8, item 8.7) unless the acceptance criteria ask for tests or the template brings them. Never sees `hidden_tests/` | keeps M7/M8 split clean; benchmark stays fair |
| D13 | **Edits**: model answers in SEARCH/REPLACE text (not JSON: escaping code in JSON hurts small models); planning / next-action turns use a schema (JSON). `temperature=0`, fixed `seed`. Rejected edits go back with the applicator's message (max 2 rejections in a row per file, then that step ends) | 7.5, research §3 |
| D14 | **`code.revise`** (7.9) = a task served by the same `CodingAgent`: `inputs={"revision_of": <ccs ref>, "required_changes": [...], "round": n}` + `artifact_refs` with the `TestReport` / `ReviewReport`. Created by (a) `POST /api/coding/runs/{project}/{task}/revise` ("Request changes" in the UI), (b) Member 8 / 10 later through `ManagerHandle.create_task` with `parent_task_id` = the original task. Helper `revision_inputs(...)` builds the inputs from a `TestReport`, `RevisionPlan` or `RevisionRequest`. At most `HMAP_CODING_MAX_REVISIONS` (default 3) per original task. `code.revise` added to the agent's output map in the plug-in (`code-change-set`) | trap T1; same shape as M6's follow-up |
| D15 | **No hook on `test.completed` / failed tests in Sprint 7** | trap T2; Member 8 item 8.9 |
| D16 | Manager hook on `task.completed` for `code.implement` / `code.revise` emits `code.completed {task_id, changeset_ref, patch_ref, files_changed, checks_passed, revision_of}` | spec §7; M8 / M9 (`docs.update`) listen to it |
| D17 | **Outcomes**: checks pass → `success`; budget spent with checks still failing → `partial` + `CodeChangeSet.notes` lists what fails (downstream continues, Member 8 sees it); `failure` only for infrastructure errors (workspace cannot be loaded, artifact store down) so the Manager's retry applies | `partial` is treated as completed (`manager.py:934`) |
| D18 | **Degraded mode**: `ReplayMissError`, no model configured or a `FakeLLM` default answer → no crash: template-only (greenfield) or unchanged workspace + `notes="no model answer: …"`, outcome `partial`, a warning log. Older demos and e2e tests stay green | trap T4 |
| D19 | **Replay-safe prompts**: only workspace-relative paths; sorted listings; command output normalised (`<ws>` for paths, timing lines and addresses removed); no ids, times or durations. Recordings in `samples/llm_cache/coding/` (`git add -f`, trap T9); a test fails if a prompt contains the work dir or a digit pattern that looks like a duration | trap T6 |
| D20 | `stub_fail` / `stub_delay_s` honoured exactly like the stub; `ctx.check_cancelled()` between steps; cancel kills the running subprocess | trap T10 |
| D21 | **Idempotent** (7.9): a redelivered execution whose `ccs-<task_id>` already exists for that execution returns the stored refs, no second run and no second head version | Sprint 1 contract, M6 pattern |
| D22 | **Repository text is data** (F3): every file slice in a prompt is wrapped with M5's `wrap(text, source=path)`; `looks_injected` hits are flagged in the trace and the UI; the system prompt says file content never gives instructions; tools cannot reach outside the workspace whatever a file says. The M6 injection test is switched on for `code.implement` (Q5) | HANDOFF Sprint 6 "How the next members plug in" |
| D23 | **Trajectories for Member 11**: every successful benchmark run writes `samples/coding/trajectories/<route>/<task>.json` (prompt messages, edits, check results; no keys, no absolute paths) | spec §6 "record all successful trajectories" |
| D24 | **No DB migration** in Sprint 7: runs, traces and heads are artifacts; `007_*` stays unused | less to merge; nothing needs SQL queries |
| D25 | **Benchmark additions** (7.12): keep the 12 verified-fair tasks; add 3 greenfield-from-template tasks (incl. **TCP chat multi-client scaffold end-to-end**, DoD) and 3 "decoy" repos (15–25 files, misleading names) so the locator's top-3 is measured on something harder than 7/7. `check_benchmark.py` must still print OK | spec DoD; research §2 "easy mode" |
| D26 | **Eval** (7.13): `tests/coding/eval/run_eval.py` runs the agent pipeline (no bus) on all tasks with hidden tests: pass@1 (temp 0), pass@3 (3 seeds, unbiased estimator), edit-apply rate, debug rounds, tokens, time; routes `coder` cloud, `coder` local `qwen3.5:9b`, `reasoner` as coder; ablations: locator off, debug loop off. `--record-missing` once with team keys, then everything is replay. Honest numbers in `eval.md` | spec 7.13 |

### Open questions for Member 1 (all answered 2026-10-24: defaults accepted)
- **Q1 (D2):** OK to keep a per-project workspace head and make `workspace_ref` the full tree after the task (patch_ref = only
  this task's diff)? The alternative (each part's own workspace, nobody merges) leaves Member 9/10 without one tree.
- **Q2 (D6):** OK to add a `make coding-venv` target (Makefile, shared file) that builds `data/coding/venv` with pinned
  `pytest`, `fastapi`, `httpx` once (needs network once)? Without it, the FastAPI template's tests are skipped and the
  agent only has `unittest`.
- **Q3 (D6):** OK to wrap commands in macOS `sandbox-exec` (deprecated by Apple but still working) as best-effort
  isolation until Member 8's Docker runner? Off on Linux / CI.
- **Q4 (D14, D15):** OK that `code.revise` is a normal task (API button now, Member 8/10 later), not the
  `revision.request` message, and that Sprint 7 adds no automatic test→revise loop?
- **Q5 (D22):** OK for Member 7 to edit Member 6's `backend/tests/verify/security/test_injection.py` to run
  `samples/verify/injection/repo/` through the coding reader (the HANDOFF asks for exactly this)? Alternative: move the
  check to `tests/coding/test_injection_repo.py` and turn M6's placeholder into a pointer to it (still a one-line edit).
- **Q6:** OK to add `[cross_cutting] 7` rows in `ownership.toml` for the shared files in §5, so the ownership check
  shows "needs sign-off" instead of "shared"/"foreign"?

---

## 2. Step-by-step build (order of work)

Tick each box as it is done. "Done when" is the check that proves it.

### Phase 0 — Set-up (½ day)
- [ ] **1. Fresh copy + baseline.** Work in the Sprint 6 handoff copy. Run `scripts/check_sprint.sh 6` once and keep the
  `reports/regression-*.md` baseline (expected PASS). Run `python3 samples/coding/check_benchmark.py` and
  `check_tools.py` (expected OK, 32/32).
- [ ] **2. Member folders.** `docs/members/7/{README,design,eval,testing,core-requests}.md` from `_template/`
  (`research.md` exists). Write `core-requests.md` rows for every §5 path once Member 1 answers Q1–Q6.
- [ ] **3. Settings.** `HMAP_CODING_*` fields in `core/config.py` + `.env.example` (shared, §5): `work_dir`,
  `keep_work`, `python`, `sandbox`, `prompt_tokens`, `max_steps`, `max_debug_rounds`, `max_revisions`,
  `cmd_timeout_s`. **Done when** settings tests green.

### Phase 1 — Safe tools, no model (Day 1–2)
| Step | Item | Files (all in `backend/src/hmap/agents/coding/`) | Done when |
|---|---|---|---|
| 4 | 7.1 workspace | `workspace.py` (port: jail, snapshot, tar.gz pack/unpack with caps, `difflib` unified diff, head read/write D2) | ports all 32 prototype checks as pytest; `../`, absolute, symlink file + folder, NUL, tar-slip (`../` and symlinks inside an uploaded tarball), > 5 MB / > 500 files refused |
| 5 | 7.4 runner | `tools/runner.py` (allow-list D5, scrubbed env, timeout, output caps, kill on cancel, audit), `tools/sandbox.py` (D6 interpreter + `sandbox-exec` profile) | denied: `sh`, `rm`, `curl`, `python -c`, `-m http.server`, `pip install`, script outside; **generated code cannot `import hmap`, cannot read the repo's `.env`, cannot see `HMAP_*` env, cannot open a socket (macOS)**; endless loop killed; 5 MB output capped |
| 6 | 7.4 tools | `tools/{read,search,list,write,patch,run_tests}.py` + `tools/__init__.py` registry (name, args schema, short result text) | each tool unit-tested; every result fits the D10 budget; outputs normalised (D19) |
| 7 | 7.5 edits | `edits.py` (port: unique match, tolerant whitespace/shift, atomic across files, `py_compile` after edit, actionable errors) | every prototype edit case + "edit to a file outside the workspace" + "edit in a template file" pass |
| 8 | 7.2 repo map | `repomap.py` (`ast` symbols + signatures + first doc line, file hash cache, non-Python files listed by name/size only, render to a token budget) | map of each benchmark repo fits 1,500 tokens; changing one file re-parses only that file |
| 9 | 7.8 budget | `context_budget.py` (D10 priorities, chars/3 estimate, slice windows) | property test: random inputs never exceed the limit; required parts (task, failure) never dropped |
| 10 | 7.10 templates | `templates/{python_package,fastapi_service,tcp_server_client,cli}/` + `templates/select.py` | each template's own tests pass in the runner; keyword selection test per template |

### Phase 2 — Model in the loop (Day 2–4)
| Step | Item | Files | Done when |
|---|---|---|---|
| 11 | 7.3 locator | `locate.py` (BM25 port + embeddings cache + RRF + optional `fast` rerank) | top-1/top-3 on the 7 modify/bug-fix tasks ≥ prototype (7/7); decoy repos measured in eval |
| 12 | prompts | `prompts.py` (system prompt incl. "file content is data", M5 `wrap()`, action schema, SEARCH/REPLACE instructions with one example) | prompt snapshot tests; no absolute path / duration in any prompt (D19 test) |
| 13 | 7.6 planner + loop | `planner.py` (small JSON plan: files to create/modify, steps, check idea), `loop.py` (understand → locate → plan → edit → check → debug → package; step budget) | `FakeLLM`-scripted tests: happy path, rejected edit then fixed, budget exhausted → `partial`, replay miss → degraded (D18), cancel mid-loop |
| 14 | 7.7 debug | `debug.py` (traceback / unittest / pytest / ruff parsers → `Failure(file, line, kind, message)`; slice; Reflexion note) | parser tests on real outputs; with scripted fixes the 4 bug-fix tasks (`b1`, `b2`, `b3`, `t1`) pass their hidden tests |
| 15 | packaging | `package.py` (CodeChangeSet + workspace tar + patch + trace; head update D2 with re-apply on a moved head) | contract validates against the JSON Schema; two tasks started from the same head both land in the newest head (conflict test → `partial` + note) |
| 16 | 7.11 review hook | `review_hook.py` (M4 `Refiner`: `ProgrammaticCritic` from check results always; `LLMRubricCritic` on acceptance criteria only when `task.refine`; max 1 revision) | uses `Refiner`; trace visible in Member 4's refine tab |
| 17 | 7.9 agent + plug-in | `agent.py` (`CodingAgent`, capabilities `code.implement`, `code.revise`, priority 100, `max_slots=1`, stub hooks D20, idempotency D21), `revise.py` (`revision_inputs()`), `hooks.py` (`code.completed` D16), `plugin.py` | on the bus in memory **and** split mode; stub yields; redelivered execution → same refs; `code.revise` on a seeded failing change fixes it |

### Phase 3 — Benchmark + eval (Day 4–5)
| Step | Item | Files | Done when |
|---|---|---|---|
| 18 | 7.12 benchmark | `samples/coding/tasks/` (+3 greenfield-from-template incl. TCP chat multi-client scaffold, +3 decoy repos), `check_benchmark.py` updated | `check_benchmark.py` OK for all tasks (starter fails, gold passes) |
| 19 | 7.13 eval runner | `backend/tests/coding/eval/run_eval.py` (`--record-missing`, `--local-only`, `--route`, `--seeds 3`, `--ablation`) | runs fully in replay with 0 misses after one recorded run |
| 20 | record | run once with team keys (`--record-missing`), once local `qwen3.5:9b` (start Ollama with `OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama`, **stop it after**) | recordings in `samples/llm_cache/coding/`; no key in any file (`scripts/secret_scan.sh`) |
| 21 | eval.md | `docs/members/7/eval.md` | pass@1 / pass@3 per kind and route, edit-apply %, debug rounds, tokens, time, locator top-3 (easy + decoy), ablations, local vs cloud, honest limits |
| 22 | trajectories | `samples/coding/trajectories/` (D23) | one file per successful run; no absolute paths / keys |

### Phase 4 — API + UI (Day 5–6)
| Step | Item | Files | Done when |
|---|---|---|---|
| 23 | 7.14 API | `agents/coding/router.py` (auto-mounted `/api/coding`): `GET runs/{project_id}`, `GET runs/{project_id}/{task_id}` (changeset + trace), `GET …/diff`, `GET …/files?path=` (read-only, jailed, from the tarball), `GET …/workspace.zip`, `GET heads/{project_id}`, `POST …/revise` (D14) — all behind `owned_project` (M6 authZ pattern) | API tests incl. other user's project → 404, path traversal in `?path=` → 400, revise limit → 409 |
| 24 | 7.14 UI | `frontend/src/features/coding/` (auto-registered tab): run list, live tool-call log (polls the trace while running), unified diff viewer (no new npm dependency), command output, flagged-injection badge, "Request changes" form, download zip | vitest + `npm run build` green |

### Phase 5 — Integration, security, demo (Day 6–7)
| Step | Item | Files | Done when |
|---|---|---|---|
| 25 | 7.15 tests | `backend/tests/coding/` (unit per module, `FakeLLM` loop, replay integration, `@pytest.mark.integration` RabbitMQ + Postgres: plan task → `code.implement` → changeset → `code.completed`) | green; whole suite still green (Sprint 6 baseline + new tests) |
| 26 | F3 injection | `samples/verify/injection/repo/` through the coding reader (Q5) + `tests/coding/test_injection_repo.py` | the injected README / comment never changes a tool call or leaves the workspace; M6's placeholder test passes |
| 27 | older demos | run `demo_sprint_3…6.sh` and `make demo` / `make stop` | all still pass (degraded mode D18 or recorded storyline calls); 0 replay misses in the storyline if recorded |
| 28 | demo 7 | `scripts/demo_sprint_7.{sh,py}` (shared, §5): upload `tcp_chat_assignment.pdf` → plan → approve → research/verify (replay) → design step scaffolds `tcp_server_client` → implement parts → changesets + head → seeded failing change → `code.revise` → checks pass → print the UI URL of the diff. Memory + split mode | `scripts/check_sprint.sh 7` runs it in both modes |
| 29 | docs | `docs/members/7/{README,design,eval,testing}.md` (design: I/O, D1–D26, failure modes, security boundary + residual risk until Docker) | team review |
| 30 | hand-off | `HANDOFF.md` Sprint 7 section (template in doc 03 §2), `scripts/precommit.sh --member 7 --base <Sprint 6 handoff folder>` (only own / cross_cutting / shared rows from §5), `scripts/check_sprint.sh 7` **PASS** | then stop everything: API, agents, Ollama, Colima/Docker if started; tell Member 1 the sprint is done |

### Suggested week
| Day | Steps |
|---|---|
| 1 | 1–6 (set-up, workspace, runner, sandbox, tools) |
| 2 | 7–10 (edits, repo map, budget, templates) + start 11 |
| 3 | 11–14 (locator, prompts, loop, debug) |
| 4 | 15–18 (packaging + head, review hook, agent on the bus, benchmark additions) |
| 5 | 19–22 (eval runner, recording, eval.md, trajectories) + start 23 |
| 6 | 23–27 (API, UI, integration + injection tests, older demos) |
| 7 | 28–30 (demo 7, docs, hand-off, check_sprint PASS) — buffer for slips |

If the week slips, cut in this order (each goes to the HANDOFF backlog, named): LLM rerank in the locator → pass@3
(keep pass@1) → `reasoner`-as-coder comparison → decoy repos → `sandbox-exec`. Never cut: jail + allow-list tests,
`code.revise`, degraded mode, the demo, check_sprint PASS.

---

## 3. Tests (7.15)
- **Unit:** workspace jail (all prototype attacks + tar-slip), runner allow-list + env scrub + `.env`/`import hmap`
  leak tests, each tool, edits (every rejection message), repo map, budget (property test), locator, parsers, template
  smoke tests, `revision_inputs`.
- **Loop (FakeLLM scripted):** happy path, rejected edit → fixed, failing test → debug → pass, budget → `partial`,
  replay miss → degraded, cancel, `stub_fail`, idempotent redelivery.
- **Contract:** `CodeChangeSet` validates against the schema; `code.completed` payload; trace schema.
- **Integration:** one RabbitMQ + Postgres test (`@pytest.mark.integration`); demo in split mode.
- **Replay:** eval in `replay`, 0 misses; D19 prompt-hygiene test.
- **Security:** M6 injection suite on (Q5); `scripts/security_check.sh` clean (no secrets in recordings, traces,
  trajectories).
- **Regression:** the full Sprint 6 suite stays green; older demos pass.

## 4. Metrics in `eval.md`
pass@1 and pass@3 per task kind (greenfield / modify / bug-fix / template) and per route (`coder` cloud, `coder`
local, `reasoner`); edit-apply success % (first try, after feedback); debug rounds used; locator top-1/top-3 (easy +
decoy); tokens and time per task; ablations (no locator, no debug loop); `code.revise` success on seeded failures;
the TCP-chat scaffold task end-to-end (DoD). Local-only numbers reported as they are.

---

## 5. Paths outside Member 7's folders (need Member 1 sign-off)

Own folders (`[members.7]`): `agents/coding/**`, `tests/coding/**`, `frontend/src/features/coding/**`,
`docs/members/7/**`, `samples/coding/**`, `samples/llm_cache/coding/**` (`backend/alembic/versions/007_*` unused, D24).

| Path | Change | Item |
|---|---|---|
| `backend/src/hmap/core/config.py`, `.env.example` | `HMAP_CODING_*` settings | 3 |
| `Makefile` | `coding-venv` target (only if Q2 = yes) | D6 |
| `scripts/demo_sprint_7.{sh,py}` | new | 28 |
| `backend/tests/verify/security/test_injection.py` (Member 6) | switch the repository entry point on for `code.implement` (Q5) | 26 |
| `ownership.toml` | `[cross_cutting] 7` rows (Q6) | — |
| `HANDOFF.md` | Sprint 7 section (every sprint does this) | 30 |
| `README.md` | "real vs stub" table: `code.implement` real | 30 |

No Manager, runtime or contract change is planned (`code.revise` output mapping lives in the plug-in, D14). No new
Python or npm dependency (LangGraph not used, `ast` instead of tree-sitter, `difflib` instead of git). If one becomes
necessary, ask Member 1 first.

## 6. What Member 7 will NOT do (other members' work)

| Member | Their area | How Sprint 7 stays out of it |
|---|---|---|
| **M1** core / Manager / runtime | `core/**`, `manager/**` | no `revision.request` handler, no contract change; if one is needed it goes to `core-requests.md` |
| **M3** planning | `agents/planning/**` | uses the design / implement steps as they are; no template change |
| **M4** refine + Ops | `agents/refine/**`, `obs/**` | only uses `Refiner`, critics, `StopPolicy`, `ReflectionMemory` |
| **M5** research | `agents/research/**` | only imports `sanitize.wrap` / `looks_injected` (and `HybridIndex` if it fits) |
| **M6** verify + security | `agents/verify/**`, `core/policy.py` | only the one injection-test switch (Q5) |
| **M8** testing | `agents/testing/**`, Docker sandbox, test generation, test→revise loop | Sprint 7 runner is local + best-effort; no Docker, no generated test suites, no automatic loop (D12, D15) |
| **M9** docs + demo packaging | `agents/docgen/**`, reset/seed | `code.completed` + the head are their inputs; nothing more |
| **M10** review + e2e | `agents/review/**`, `tests/e2e/**` | `revision_inputs()` is offered; recovery planning is theirs |
| **M11** models + routing | router, model tiers | no route change; trajectories + `run_eval.py --local-only` are handed to them |

## 7. Definition of Done (sprint file §8 + doc 03 §3)
- [ ] `research.md`, `design.md`, `eval.md`, `testing.md`, `README.md` in `docs/members/7/`
- [ ] `CodingAgent` registered through `plugin.py`; stub yields; works over RabbitMQ; idempotent
- [ ] Gateway roles only; works in `fake` and `replay`
- [ ] Benchmark pass rate reported; **TCP-chat scaffold task succeeds end-to-end**
- [ ] Path jail + command allow-list security tests pass (incl. `.env` / `import hmap` / network leak tests)
- [ ] `code.revise` works on a seeded failing change
- [ ] API + UI: tool-call log, diff viewer, run output
- [ ] `demo_sprint_7.sh`: plan task → code agent writes working code → diff visible in the UI (memory + split)
- [ ] Previous sprints' tests and demos still green; `security_check.sh` clean
- [ ] `HANDOFF.md` updated; `precommit.sh --member 7` shows no `foreign` files; `check_sprint.sh 7` PASS
- [ ] Every background process stopped; Member 1 told the sprint is done (no git commit or push)

## 8. Risks
| Risk | Plan |
|---|---|
| Local 9B weak on multi-file edits | small tasks (planner depth cap), templates, one file slice at a time, SEARCH/REPLACE, debug rounds; cloud first by policy; local numbers reported honestly |
| Model-written code leaks keys or touches the laptop | D4 + D6 + scrubbed env + leak tests; hard boundary is Member 8's Docker (documented residual risk) |
| Runaway loops | step / token budgets via M4 `StopPolicy`, hard caps, wall-clock abort |
| Replay misses break older demos / CI | D18 degraded mode + D19 prompt hygiene + recorded storyline |
| Parallel parts conflict in the head | D2 re-apply → redo once → `partial` with the conflict named |
| Edit format errors (model misquotes SEARCH) | tolerant matcher for whitespace/shift only, actionable error back to the model, 2 tries per file |
| Prompt injection through repository files | D22: wrapped as data, flagged, tools jailed regardless |
| Sprint too big | cut order in §2; Must items first |
