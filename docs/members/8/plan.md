# Sprint 8 plan of action — Member 8: Automated testing & execution

Spec: [`docs/sprints/sprint-08-member8-testing-execution.md`](../../sprints/sprint-08-member8-testing-execution.md)
(items 8.1–8.15). Research: [`research.md`](research.md). Prototypes: [`samples/testing/`](../../../samples/testing/README.md).
Written 2026-10-30 against the code as handed over after Sprint 7 (`check_sprint.sh 7` PASS, 2026-10-25).

**Status (2026-10-30): defaults taken for Q1–Q6 (§1) so the build can start; Member 1 can still change any of them.**

**Status (2026-10-30): built.** See [README](README.md), [design](design.md), [eval](eval.md), [testing](testing.md).
Differences from this plan, found while building (details: design §9): supplied acceptance tests (`inputs.tests`); the
loop's plateau rule became "no progress" (same failures and no higher pass ratio); model hints are an ordered list.

**Status (2026-10-31): stretch items built** (Member 1: "do everything, even optional"): flaky-test quarantine, mutation
testing, fuzzing, JS/TS + a Node image, dependency audit (OSV), gVisor switch + gVisor/Firecracker write-up, threat
model; local-model eval on 4 variants. Only installing gVisor in Colima waits for Member 1's OK ([gvisor.md](gvisor.md)).

The sprint in one line: a real `test.run` agent that takes a coding step's workspace, runs static → build → unit →
integration → security (→ execution) in a locked-down Docker container (or the Sprint 7 jailed runner when Docker
is not running), explains every failure with category + file/line + hint, returns a `TestReport`, and drives a
bounded test → `code.revise` → test loop with Member 7.

---

## 0. What already exists (checked in the code)

| Thing | Where | State |
|---|---|---|
| `TestReport`, `TestFailure`, `StageResult`, `StageName` | `core/contracts/domain.py:360-393` | done (Sprint 1). Stages `static, build, unit, integration, security, execution`; categories `SYNTAX … ENV`; `coverage`, `exec_log_ref` |
| `test.run` capability, output `test-report` | `core/contracts/capabilities.py` | names exist; `TestRunStub` (priority 0) yields once a real plug-in exists |
| `test.completed` event | `core/contracts/events.py:58` | defined, nobody emits it |
| Plans with test steps | `agents/planning/templates.py` (Member 3) | software plans: `implement per part → test per part (test.run, depends on that part)`; the test task gets the part's `code-change-set` / `workspace` / `code-patch` refs (`manager._dependency_artifacts`) |
| `code.revise` + `revision_inputs(...)` | `agents/coding/revise.py` (Member 7) | ready: a revision is a normal task, `artifact_refs` may carry a `test-report`; its failures become the coding agent's starting point |
| `code.completed` event | `agents/coding/hooks.py` | emitted for every coding step (Member 7 left the failed-test hook to Member 8, his D15) |
| Workspace tar / jail / runner | `agents/coding/workspace.py`, `tools/runner.py`, `tools/sandbox.py` | `files_from_tar`, allow-listed runner with macOS `sandbox-exec` and `make coding-venv` → reused as the **local** backend (D2) |
| M4 stop policies | `agents/refine/stop.py` | `MaxIters`, `Plateau`, `TestsPass`, `Budget`, `any_of` — "Members 7 and 8 drive their own code <-> test loops with them" |
| Gateway | `core/llm/base.py` | `generate(role, …, schema=)`, `classify(...)`; roles `coder` (test generation), `reasoner` (failure hints), `classify` |
| Prep package | `samples/testing/` | Docker sandbox prototype (8/8 abuse cases contained), seeded-failure suite (good + 15 variants, 16/16 by rules) — stdlib only, **not** importable from `hmap` → port |
| Docker | Colima on this laptop | not running by default; the image needs the internet once (D3) |
| Ownership | `ownership.toml` `[members.8]` | `agents/testing/**`, `tests/testing/**`, `features/testing/**`, `docs/members/8/**`, `samples/testing/**`, `samples/llm_cache/testing/**`, `alembic/versions/008_*`; no `[cross_cutting] 8` row (Q6) |

### Traps found while reading the code
| # | Trap | Handled by |
|---|---|---|
| T1 | The `test.run` stub always reports a failure; any hook "failed test → revise" written against it would loop in every project | the loop hook belongs to the testing plug-in and only reacts to reports with a `testing-trace` (D12) |
| T2 | Older demos / e2e tests now get the real `test.run`: replay has no testing recordings, the loop would create `code.revise` tasks nobody recorded | degraded mode (D14): no model → rules only, no generated tests; loop only for actionable, non-generated failures; `HMAP_TESTING_AUTO_REVISE` |
| T3 | Colima cannot mount the external drive; a bind-mounted workspace would be empty | code goes in as a tar on stdin (prototype), never a mount |
| T4 | A mounted `/var/run/docker.sock` inside a container is root on the host | the agent runs on the host and calls the `docker` CLI (D1) |
| T5 | Test output has temp names, timings, ports, container ids → replay misses in the hint prompts | normalise every output before it reaches a prompt (Member 7's `normalise` + container ids) |
| T6 | `mypy` honours plug-ins from the workspace's config (code execution) | mypy only inside the container (D4) |
| T7 | Generated tests that "assert the bug" | sanity gate (D9): must fail on an auto-made known-bad stub, labelled `generated`, never trigger a revision on their own |
| T8 | Parallel test steps share the laptop (16 GB) with Ollama and the stack | governor: one sandbox at a time, 256 MB each (D11) |

---

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Docker-socket trade-off: option (a)**: the testing agent runs **on the host** (inside the backend / `hmap-agents` process) and calls the `docker` CLI with asyncio subprocesses. No container ever gets the socket. Not the Docker SDK: no new dependency, identical flags to the proven prototype, easy to log | spec §4, research §4, T4 |
| D2 | **Two sandbox backends**, `HMAP_TESTING_SANDBOX=auto|docker|local` (default `auto`): `docker` when `docker info` answers and the image exists, else `local` = Member 7's jailed runner (scrubbed env, allow-list, macOS `sandbox-exec`, coding venv). The report says which backend ran; `local` is marked "weaker isolation" in the trace and the UI. Unit tests and CI use `local` | platform must keep working without Docker (like without keys) |
| D3 | **Image `hmap-sandbox-py:1`** from `agents/testing/sandbox/Dockerfile`: `python:3.11.17-slim` + pinned `pytest`, `coverage`, `ruff`, `mypy`, `bandit` + the in-container runner `stages.py`. Built **only** by `make sandbox-image` (needs the internet once); a task never builds it | runs stay offline; no surprise 2-minute pulls during a demo |
| D4 | **Every container**: `--network none` (loopback stays: the TCP server + clients test works, ports are private to the run), `--read-only`, tmpfs `/work` 64 MB + `/tmp` 16 MB, `--user 10001`, `--cap-drop ALL`, `no-new-privileges`, `--memory 256m --memory-swap 256m`, `--cpus 1`, `--pids-limit 64`, a hard timeout (container killed), 64 KB output kept, `--rm` + a reaper for leftovers (label `hmap.sandbox=1`) | 8.1, prototype 8/8 |
| D5 | **Stages** (8.2), cheapest first, later stages skipped after a SYNTAX/IMPORT failure: `static` (ruff explicit rules E4,E7,E9,F + mypy only when the workspace configures it, docker only) → `build` (py_compile + import of every module) → `unit` (pytest, JUnit XML → per-test results, coverage % with `coverage` in docker) → `integration` (tests in `tests/integration/`, `test_integration*.py` or marked `integration`; own time limit) → `security` (bandit in docker + built-in AST rules + secret regex everywhere) → `execution` (only when `inputs.entrypoint` is given: run it with sample stdin, short timeout). Each stage: status, duration, output artifact | 8.2–8.6 |
| D6 | **Failures** (8.8): rules first (stage, exit, timeout, exception type, pytest/ruff/bandit/traceback parsing → category, file, line, test name); `ctx.llm.classify` only for failures the rules cannot place; hints = rule text, plus one `reasoner` call for the top 5 failures (JSON, ≤ 200 chars each). No model → rule hints only | spec §6: most of the pipeline LLM-free |
| D7 | **Flaky check**: a failed unit/integration test is re-run once in a fresh run; pass-then-fail → `FLAKY` note in the trace, reported as ASSERTION with hint "flaky", never sent to Member 7 | research §5 |
| D8 | **What is tested**: the newest `workspace` artifact among `artifact_refs` (the coding step's full tree); else `inputs.workspace_ref`; else the project head `wsh-<project>`; else nothing → report `passed=false`, one ENV failure, outcome `partial` | plan steps hand over the part's refs |
| D9 | **Test generation** (8.7) when the workspace has **no tests** or `inputs.generate_tests` is true: `coder` writes pytest tests from the acceptance criteria + the module signatures (repo map). Sanity gate: compiles, ruff-clean, collected, and **fails on a known-bad stub** (the same modules with every function body replaced by `raise NotImplementedError`, made with `ast`); tests that pass on the stub test nothing and are dropped. Kept tests live in `tests/generated/` of the test run only (artifact `generated-tests`), never in the project head. Failures from them are labelled `generated` | research §2, T7 |
| D10 | **Loop with Member 7** (8.9): on `task.completed` of `test.run` with `passed=false`, actionable failures (not only LINT, not only generated, not ENV) and `HMAP_TESTING_AUTO_REVISE=true` (default): create `code.revise` (`revision_inputs(changeset_ref, required_changes from failures, round)`, `artifact_refs=[test-report]`, `parent_task_id` = the coding task) and a new `test.run` that depends on it. Bounded by M4 `any_of(TestsPass, MaxIters(HMAP_TESTING_MAX_ROUNDS=2), Plateau(on pass ratio))`; the round and history ride in `inputs.loop` | spec §7 "test.failed → code.revise (≤N) → test.run" |
| D11 | **Governor** (8.11): one sandbox run at a time per process (asyncio semaphore, `HMAP_TESTING_CONCURRENCY=1`), reaper of old containers on start, image presence checked once and cached; the agent's `max_slots = 1` | 16 GB laptop |
| D12 | **Artifacts**: `test-report` `tr-<task_id>` (first, the contract output), `test-log` `tl-<task_id>` (all stage outputs, normalised, `exec_log_ref`), `testing-trace` `tt-<task_id>` (backend, stages, commands, failures, flaky, generated tests, loop round, model calls), `generated-tests` `gt-<task_id>` when any | same pattern as M5/M6/M7 |
| D13 | **Outcomes**: pipeline ran → `success` whatever the tests say (`TestReport.passed` carries the verdict; the loop and Member 10 act on it); nothing to test or no sandbox at all → `partial`; `failure` only when the store / artifacts cannot be read | Manager treats `partial` as completed |
| D14 | **Degraded mode**: replay miss / no model → no generated tests, rule hints only, no crash. Older demos and e2e stay green | T2 |
| D15 | **Events**: hook on `task.completed` of `test.run` emits `test.completed {task_id, report_ref, passed, failures, changeset_ref, loop_round}`; the loop (D10) runs in the same hook | spec §7 |
| D16 | **API + UI** (8.14): `/api/testing/*` (runs per project, one run with stages + logs + failures + loop history, re-run button = a new `test.run` task with the same inputs); Testing tab (stage timeline, log viewer, failure list with hints, loop iterations) | same shape as the Coding tab |
| D17 | **No DB migration**: reports, traces and logs are artifacts; `008_*` stays unused | as Members 6, 7 |
| D18 | **Eval** (8.13): seeded suite (good + 15) + an **unseen** set (Member 7's bug-fix benchmark starters with their hidden tests, b1–b3, d1–d3, plus their gold-fixed versions): detection rate, false-pass rate on known-good, classification accuracy, sandbox overhead (docker vs local), loop fix rate (seeded variants through the real coding agent, recorded once with team keys then replay) | spec DoD ≥ 90 % detection, 0 false-pass |

### Open questions for Member 1 (defaults taken 2026-10-30)
- **Q1 (D1):** host-run agent calling the `docker` CLI (no SDK, no socket in a container). *Default: yes.*
- **Q2 (D2):** fall back to Member 7's jailed runner when Docker is not running, clearly marked. *Default: yes.*
- **Q3 (D3):** `make sandbox-image` target in the shared `Makefile`. *Default: yes.*
- **Q4 (D10):** automatic test → `code.revise` → test loop on by default, at most 2 rounds. *Default: yes.*
- **Q5:** `HMAP_TESTING_*` settings in `core/config.py` + `.env.example`. *Default: yes.*
- **Q6:** `[cross_cutting] 8` rows in `ownership.toml` for the shared files of §5. *Default: yes.*

---

## 2. Step-by-step build

| Step | Item | Files (`backend/src/hmap/agents/testing/` unless said) | Done when |
|---|---|---|---|
| 1 | set-up | `docs/members/8/{README,design,eval,testing,core-requests}.md`; settings `HMAP_TESTING_*` | settings tests green |
| 2 | 8.1 sandbox | `sandbox/{Dockerfile,stages.py}`, `sandbox/docker.py` (run, limits, reaper), `sandbox/local.py` (Member 7 runner), `sandbox/__init__.py` (choose backend) | abuse tests (docker, `integration` marker): network, write outside, not root, fork bomb, endless loop, memory, big output, ok — all contained |
| 3 | 8.11 governor | `governor.py` | one run at a time; leftovers reaped |
| 4 | 8.2–8.6 stages | `pipeline.py`, `stages/{static,build,unit,integration,security,execution}.py` | each stage unit-tested on small workspaces (local backend); seeded suite through docker |
| 5 | 8.8 analyzer | `analyze.py` | seeded 16/16 by rules; file/line/hint on each; classify fallback tested with FakeLLM |
| 6 | 8.7 testgen | `testgen.py` | FakeLLM: good tests kept, a test that passes on the stub dropped, broken file dropped |
| 7 | 8.10 agent | `agent.py`, `model.py`, `plugin.py` | on the bus; idempotent; cancel kills the container |
| 8 | 8.9 loop | `refine_loop.py`, `hooks.py` | hook test: failed report → `code.revise` + `test.run`; stops at max rounds / pass / plateau; nothing for stub reports, LINT-only, generated-only |
| 9 | 8.12 seeded | `samples/testing/seeded_failures/` (kept) + `samples/testing/unseen/` (from Member 7's benchmark) | labels checked |
| 10 | 8.13 eval | `tests/testing/eval/run_eval.py`, `docs/members/8/eval.md`, `samples/testing/eval_results/` | numbers recorded |
| 11 | 8.14 API + UI | `router.py`, `frontend/src/features/testing/` | API tests; vitest; browser check |
| 12 | demo | `scripts/demo_sprint_8.{sh,py}` | TCP chat: coding output fails the multi-client test → revise → pass |
| 13 | 8.15 + acceptance | `backend/tests/testing/**` | `scripts/check_sprint.sh 8` PASS |

## 3. Paths outside Member 8's folders (need Member 1 sign-off)
`backend/src/hmap/core/config.py`, `.env.example` (settings), `Makefile` (`sandbox-image`), `scripts/demo_sprint_8.{sh,py}`,
`README.md` (real vs stub), `ownership.toml` (`[cross_cutting] 8`), `frontend/src/features/_registry.generated.ts`
(regenerated), `HANDOFF.md`.

## 4. Not Member 8's work
The coding agent itself (Member 7), docs checks of code examples (Member 9 can call the sandbox later), the final
review and recovery (Member 10), routing (Member 11).
