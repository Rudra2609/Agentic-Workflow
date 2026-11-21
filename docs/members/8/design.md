# Design — automated testing & execution (Sprint 8)

Decisions D1–D18 are in the [plan](plan.md) §1; this page is how the built code works.

## 1. One test run
```text
test.run task (artifact_refs = the coding step's workspace + change set)
 → find the tree to test (workspace → inputs.workspace_ref → project head)         agent.find_workspace
 → + acceptance tests supplied with the step (inputs.tests, tests/acceptance/*.py)  agent.acceptance_tests
 → no tests at all? write them from the criteria, keep only those that FAIL on a     testgen.generate / gate
   known-bad stub of the code
 → ONE sandbox run: static → build → unit → integration → security → execution      pipeline.run_pipeline
 → failed tests re-run once in a fresh run: pass-then-fail = flaky                  pipeline.recheck_flaky
 → classify (rules; classify model only for failures with no exception type)        analyze
 → hints for the top 5 failures (one reasoner call, rule hints without a model)     analyze.model_hints
 → TestReport + full log + trace (+ generated tests)                                agent._finish
hook on task.completed: test.completed event; decide → code.revise + test.run       hooks / refine_loop
```

## 2. Sandbox (`sandbox/`)
The pipeline is a list of `Step`s (stage, name, kind, args, timeout, needs). A backend runs the whole list for one
workspace and returns one `StepResult` per step; a step whose `needs` failed is skipped (no tests after a file that
does not compile or import).

**Docker** (`sandbox/docker.py`, image `hmap-sandbox-py:1` from `sandbox/Dockerfile`, pinned pytest / coverage /
ruff / mypy / bandit): `docker run -i --network none --read-only --tmpfs /work (64 MB) --tmpfs /tmp (32 MB)
--user 10001 --cap-drop ALL --security-opt no-new-privileges --memory 256m --memory-swap 256m --cpus 1
--pids-limit 64`, label `hmap.sandbox=1`. The workspace goes in as a tar on stdin (nothing on the host is mounted;
Colima cannot mount the external drive anyway). Inside, `stages.py` (standard library only) extracts it and runs each
step in its own process group with its own time limit, keeping the first and last 8 KB of output (a 200 MB flood
never fills the container's memory), and prints one `HMAP_RESULTS` line with exit codes and the small report files
(JUnit XML, coverage JSON, bandit JSON). The host keeps at most 2 MB of the container's output, kills the container
at the sum of the step limits + 20 s, reads `OOMKilled`, removes it, and kills it on cancel.

**Docker-socket trade-off** (spec §4): option (a). The agent runs on the host, inside the backend or `hmap-agents`
process, and calls the `docker` CLI. No container is ever given `/var/run/docker.sock` (root on the host). (b) a
socket proxy and (c) rootless/sysbox add moving parts for no gain on a single laptop.

**Local** (`sandbox/local.py`): Member 7's runner: allow-list (python -m pytest / py_compile, a script inside the
workspace, ruff errors only), environment rebuilt from nothing, the coding venv, macOS `sandbox-exec`. No mypy or
bandit there (mypy can load plug-ins from the workspace config, i.e. run code); the built-in security rules still
run. Chosen by `HMAP_TESTING_SANDBOX=auto` when Docker does not answer or the image is missing; the report and the UI
say "weaker isolation".

**Governor** (`governor.py`): one sandbox run at a time per process (`HMAP_TESTING_CONCURRENCY=1`); leftover
containers (exited, or running longer than any run may) are removed when the agent starts; Docker readiness is
cached for a minute; the image is never built during a task.

## 3. Stages (`stages/`)
| Stage | Steps | Status / failures |
|---|---|---|
| static | ruff `E4,E7,E9,F` (local: `E9,F`); mypy when the workspace configures it (Docker) | LINT (E9 = SYNTAX); never stops later stages |
| build | `py_compile` of every file; import of every module of the code under test (needs compile) | SYNTAX / IMPORT / CRASH; tests are skipped after it fails |
| unit | pytest on test files outside `integration`, JUnit XML; coverage of the code (Docker) | per test: ASSERTION / CRASH / SYNTAX / IMPORT; TIMEOUT when killed |
| integration | pytest on `tests/integration/`, `*integration*` files or `pytest.mark.integration`; 2× the time limit | same; loopback only, ports private to the run |
| security | bandit (Docker; skips B101 assert, B104 bind-all, B311 random) + built-in `ast` rules + secret patterns | SECURITY (eval/exec, shell commands, pickle, yaml.load, mktemp, verify=False, hard-coded secrets / keys) |
| execution | `inputs.entrypoint` with `inputs.sample_input` on stdin, 10 s | exit 0 passes; a server (`long_running`) still running passes |

`TestReport.passed` = no failure other than LINT or flaky. `pass_ratio` = passed tests / tests (unit + integration).

## 4. Failure analysis (`analyze.py`)
Rules first: JUnit `failure` / `error` elements → exception type (last `Error:` line or `E   ` lines) → category;
file and line = the deepest traceback frame in the code under test (for ASSERTION the test's own line); generated
tests (`tests/generated/`) are labelled. Parsers for ruff (incl. `invalid-syntax`), mypy, bandit JSON and plain
tracebacks. Rule hints per category (ConnectionRefused → "nothing listens where the test connects…", import → the
missing module, ruff codes, security constructs). A failure with no exception type at all is marked `needs_model`
and `ctx.llm.classify` picks its category. One `reasoner` call (`{"hints": [...]}` in order) writes hints for the
top 5 failures; for a failure inside a test file the whole test file (≤ 200 lines) is shown, so the hint can say how
the test starts and talks to the program. No model → the rule hints stay.

## 5. Test generation (`testgen.py`)
Only when the workspace has no tests (or `inputs.generate_tests`) and there are acceptance criteria. The `coder`
writes one pytest file from the criteria and the code (whole files ≤ 150 lines, else the outline), wrapped as data.
Gate: it must parse, and each test must **fail** on a stub of the code where every function body is
`raise NotImplementedError` (`ast`). Tests that pass on the stub check nothing and are deselected; if none is left
the file is dropped. Kept tests live in `tests/generated/` of the test run only.

## 6. The loop with Member 7 (`refine_loop.py`, `hooks.py`)
On `task.completed` of `test.run` (only runs with a `testing-trace`: never the stub): emit `test.completed`, then
`decide`: revise when auto-revise is on, the report failed, the tested code came from a coding step, and some failure
is actionable (not LINT, ENV, flaky or generated). Stop rules: Member 4's `TestsPass` and
`MaxIters(HMAP_TESTING_MAX_ROUNDS=2)`, plus **no progress** = the pass ratio did not rise **and** the failing tests
are the same as last round. (A plain `Plateau` on the ratio stopped the demo after a fix that turned "connection
refused" into "wrong reply", which is progress at the same ratio.) A revision = `code.revise` (Member 7's
`revision_inputs`; required changes = each failure's category, test, place, expected-vs-actual and hint; the report in
`artifact_refs`; parent = the coding step) + a new `test.run` that depends on it, carrying `inputs.loop`
(round, origin, pass-ratio history, last failure signatures) and the supplied acceptance tests.

## 7. Artifacts and idempotency
`tr-` (TestReport, first), `tl-` (text log, normalised: no `/work/`, temp names, timings, ports), `tt-` (trace),
`gt-` (generated tests). A redelivered execution whose trace is `done` returns the stored refs. Outcome `success`
when the pipeline ran, `partial` when there was nothing to test or the sandbox failed, `failure` only when artifacts
cannot be read or stored.

## 8. API and UI
`GET /api/testing/runs/{project}` (summaries), `GET …/{task}` (trace, report, generated tests, the loop's rounds),
`GET …/{task}/log` (text), `POST …/{task}/rerun` (a new `test.run` with the same inputs and artifacts, without the
loop state). Ownership checked on every route (404), CSRF on POST. Testing tab (order 45): run cards, the stage
timeline with tests and coverage, the loop rounds, failures with hints (counted first, lint/flaky after), generated
tests, the command log, "Re-run the tests".

## 9. Stretch items (all built)
| Item | Module | How it works | Proof |
|---|---|---|---|
| Flaky-test quarantine | `quarantine.py` | a test that failed and passed on the re-run is stored in `tq-<project>`; later failures of it are marked flaky (shown, not counted, never sent for a fix); released after 3 clean passes or by a person (`POST /api/testing/quarantine/{project}/release`); Testing tab lists them | `test_quarantine.py` |
| Mutation testing | `mutation.py` | after green unit tests (`inputs.mutation` / `HMAP_TESTING_MUTATION`): up to 20 `ast` mutants (comparisons, arithmetic, and/or, not, int and bool constants, return None; none in `__main__` blocks, annotations, decorators), each run with `pytest -x` by a helper script inside the same sandbox; mutation score + surviving mutants in the trace and the tab | `test_extras.py`, Docker test, eval extras (seeded tests: 21/30 caught) |
| Fuzzing | `fuzz.py` | (`inputs.fuzz` / `HMAP_TESTING_FUZZ`, Docker: Hypothesis is in the image) simple-typed public functions without side-effect names, 150 derandomized examples each, 2 s alarm per call; the module's own exceptions, `ValueError`, `TypeError` = correct rejection; anything else = a `fuzz` finding with the smallest failing input (shown, not counted, never sent alone) | `test_extras.py`, Docker test, eval extras (3/3, 0 false) |
| JS / TS projects + per-language images | `stages/node.py`, `sandbox/Dockerfile.node`, `eslint.config.mjs` | no Python files + `package.json` / JS / TS files → the Node image (Node 22, ESLint 9 recommended, TypeScript): ESLint (JSON report) → static; `node --check` / `tsc` syntax → build; `tsc` type errors → static; `node --test` (JUnit) → unit; built-in rules (eval, new Function, exec with built commands, innerHTML, document.write, secrets) → security. Local runner: ENV ("needs the Docker sandbox") | Docker tests (7 cases), eval extras 7/7 |
| Dependency audit | `deps.py` | host side (the sandbox has no network): pinned versions from `requirements*.txt`, `pyproject.toml`, `package.json` → OSV `querybatch` (the pip-audit / npm audit database), cached in `data/testing/osv_cache.json`; network only in live mode (`fake` / `replay` read the cache: tests and demos stay offline); one SECURITY failure per vulnerable pin with the highest fixed version as the hint | `test_extras.py` (fake OSV + cache), checked once against the real OSV (requests 2.19.0, lodash 4.17.15) |
| gVisor / Firecracker evaluation | `sandbox/docker.py`, `sandbox/stages.py`, [gvisor.md](gvisor.md) | `HMAP_TESTING_RUNTIME=runsc` adds `--runtime runsc`; under gVisor the cgroup limits bound gVisor's own kernel, so the runner sets per-process limits (`setrlimit`: 100 processes, 768 MB address space with `MALLOC_ARENA_MAX=2`) and the cgroup gets headroom (1280 MB, 512 pids); installed in Colima and measured (+~30 %); Firecracker impossible here (no `/dev/kvm`) | the whole Docker suite under `runsc` (36/36), `test_extras.py` (limits per runtime) |
| Threat model | [threat-model.md](threat-model.md) | assets, attacker, 16 threats with the protection and its test, residual risks | — |

## 10. Differences from the plan, found while building
- The hint answer is an ordered list, not `{id, hint}` objects: the cloud model kept putting the test name in `id`.
- Supplied acceptance tests (`inputs.tests`) were added: without them the coding agent's revision could not see how
  a teacher's black-box test starts the program; with the whole test file in the hint prompt it can.
- The loop's plateau became "no progress" (above).
- Output inside the container is drained by a thread keeping head and tail only; the prototype's `communicate()`
  would have held a 200 MB flood in memory.
- The in-container runner extracts the tar by hand (regular files, relative paths only): the Node image's Debian
  Python 3.11.2 has no `extractall(filter="data")`.
- ESLint 9 removed the plain-text formatters; the JSON report is parsed instead. Node's JUnit reporter gives no file,
  so JS test ids are the test names; the exception sits on an indented `cause:` line.
