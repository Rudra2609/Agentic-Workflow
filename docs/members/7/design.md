# Design — Member 7: Autonomous coding (Sprint 7)

Plan and decisions: [plan.md](plan.md) (D1–D26, approved 2026-10-24). Research: [research.md](research.md).
Numbers: [eval.md](eval.md). Tests: [testing.md](testing.md).

## 1. What it does

`code.implement` (a plan's *design* and *implementation* steps) and `code.revise` (a revision of an earlier coding
step). One agent, `CodingAgent` (`backend/src/hmap/agents/coding/agent.py`), serves both.

```text
TaskAssign{objective, acceptance_criteria, inputs, artifact_refs}
 → workspace: inputs.workspace_ref | project head wsh-<project> | upstream workspace | empty   (package.load_base)
 → loop (loop.CodingLoop, no LangGraph):
     understand  empty → template (templates/); repo map (ast); flag AI-directed lines; baseline checks
     locate      BM25 + embeddings (weighted RRF) + LLM rerank when > 8 files            (locate.py)
     plan        coder, JSON CodePlan {summary, files_to_modify, files_to_create, steps}  (prompts.py)
     edit        coder, SEARCH/REPLACE text → edits.apply (unique match, tolerant, atomic, compile, no-op refused)
     check       compile · ruff E9,F · import smoke · the workspace's own tests            (tools/checks.py)
     debug       while checks fail: parsed failures + slices + Reflexion note → one fix → check
                 stop = Member 4's any_of(TestsPass, MaxIters, Plateau, Budget); regression guard keeps the best round
     review      Member 4's Refiner: ProgrammaticCritic always; + LLMRubricCritic and one fix round if task.refine
 → package: head moves (three-way rebase if it moved meanwhile), ws-, patch-, ct-, ccs- artifacts      (package.py)
 → code.completed event (hooks.py)
```

## 2. Inputs and outputs

| | |
|---|---|
| Inputs | `objective`, `acceptance_criteria`; the project's latest `requirement-set` (the step's `requirement_ids`, + technology/format constraints) as context; optional `inputs.workspace_ref`; `task.refine`. `code.revise`: `inputs.revision_of` (a `code-change-set`), `required_changes`, `revision_round`, `original_task_id`, and `test-report` / `review-report` refs in `artifact_refs` |
| Output (first) | `code-change-set` `ccs-<task_id>` = `CodeChangeSet{task_id, workspace_ref, patch_ref, files_changed, commands_run, notes}` (contract unchanged) |
| Other artifacts | `workspace` `ws-<task_id>` (deterministic `.tar.gz` of the full tree after the step), `code-patch` `patch-<task_id>` (unified diff of **this step only**), `coding-trace` `ct-<task_id>` (every model call, edit, command, check, flag, note; written at each stage so the UI shows it live), project head `workspace-head` `wsh-<project_id>` |
| Event | `code.completed {task_id, changeset_ref, patch_ref, workspace_ref, files_changed, checks_passed, outcome, capability, revision_of}` |
| Outcome | `success`: checks pass **and** something changed (or the model judged that nothing needs to change). `partial`: checks still fail after the budget, no model answered, or nothing was changed (the Manager treats `partial` as completed, so the plan continues and the notes say what is not done). `failure`: only when the workspace itself cannot be loaded or stored (the Manager retries) |

`CodeChangeSet.notes` always says what is not done (`NOT DONE: tests: …`), the template used, the plan, the checks
and the stop reason — the text Member 8 and Member 10 read first.

## 3. The project head (plan D2)

A software plan runs `design → implement part 1..n` (parts in parallel, each depending on design). Every coding step
starts from the project's head and writes its result as the next head version, so the parts end up in **one tree**
(what Member 9's docs and Member 10's review need). `workspace_ref` is the full tree after the step; `patch_ref` is
only that step's change. If the head moved while a step ran (two coding agents in split mode), the step's change is
re-applied on the newer head with a line-based three-way merge (`workspace.rebase`); on a conflict the step is redone
once on the newer head, and a second conflict ends in `partial` with the files named.

## 4. Edits, checks, debugging

- **Edit format** (D13): SEARCH/REPLACE text, not JSON (escaping code in JSON hurts small models); planning uses a
  schema. Temperature 0, seed 7. The applicator (ported from the prep package) needs a unique match, tolerates
  trailing whitespace or a shifted block (also unique), refuses edits that would not compile, refuses edits that
  change nothing, refuses `.env` / caches / `.git` / anything outside the workspace, and applies all blocks or none.
  Every refusal is written for the model ("SEARCH matches 2 places; add the surrounding lines") and fed back; three
  refusals in a row end the step.
- **Checks** (D12): `python -m py_compile`, `ruff check --select E9,F` (errors, not style), an import smoke test
  of the changed modules (a helper script under `.tmp/`, never packed), and the workspace's own tests (pytest if the
  interpreter has it, else `unittest discover`). Results are reused for an identical workspace (same files, same
  request): parallel parts that start from an unchanged head, and every step in offline / fake mode, do not start
  pytest again (other members' pipeline tests with short timeouts stay fast). The agent does not write test suites (Member 8, item 8.7) and never
  sees the benchmark's hidden tests.
- **Debug** (D11): failures are parsed by rules (innermost workspace frame of a traceback, unittest blocks, pytest
  `file:line`, ruff codes, timeouts); the prompt shows the failing slices (±25 lines), the check output and the last
  Reflexion notes (rule-made: "the edit to server.py did not fix [TIMEOUT] …, try a different fix"). Each round is
  scored (compile .25, imports .15, lint .1, tests .5 by passed fraction) and Member 4's `LoopState` / stop policies
  decide. A round that makes things worse is rolled back at the end (regression guard).
- **Self-review** (7.11): Member 4's `Refiner` with a `ProgrammaticCritic` over the check results; with
  `task.refine` also an `LLMRubricCritic` (role `judge`: does the diff meet every criterion? obvious bugs?) and one
  more fix round through the loop. The result is a note in the coding trace (Member 4's Refinement tab expects its
  own run record, so no `refinement-trace` artifact is written).

## 5. Context budget and replay (D10, D19)

Every prompt is assembled from prioritised parts and cut to `HMAP_CODING_PROMPT_TOKENS` (5,500; characters / 3) so
the same prompt fits the local 8k window and the cloud routes (identical prompts = one recording for both). Required
parts (task, failures, format) are never dropped; file slices and the repo map are cut first. A property test checks
the budget is never exceeded. Prompts contain only workspace-relative paths, sorted listings and normalised command
output: the workspace path becomes `<ws>`, interpreter paths `<python>`, timings, ports, addresses and Python temp
file names are removed — found the hard way: pytest printed `argv = ['count', 'tmpris_eh4i.txt']`, a new temp name
every run, and the replay missed.

## 6. Security boundary

The agent runs code a model wrote. Sprint 7's boundary (hard isolation is Member 8's Docker runner):

| Threat | Control |
|---|---|
| Path tricks in tool calls (`../`, absolute, symlinks, NUL) | `Workspace.path()` resolves and refuses anything outside; every refusal audited (`coding.denied` log + trace) |
| Tar-slip in a stored workspace | `unpack()` accepts regular files only, no absolute names or `..`, size/count caps |
| Commands | argv only, no shell; allow-list: unittest, pytest, py_compile, a script in the workspace, `ruff check`; no `-c`, no other modules, no pip |
| Keys reaching generated code | environment rebuilt from nothing (no `HMAP_*`, no `*_API_KEY*`); interpreter = `data/coding/venv` or the base Python (never the backend venv: `import hmap` would read `.env`); workspaces live in the temp folder, never inside the project |
| Generated code reading files / network | macOS `sandbox-exec` (`HMAP_CODING_SANDBOX=auto`): no file contents under the project folder or home (incl. `.env`), writes only in the workspace, outbound network only to localhost (the TCP tests need it). Best effort (deprecated by Apple); off on Linux |
| Runaway code | time limit per command (20 s, max 60), process group killed, output capped (64 KB kept, 10 KB shown, killed at 2 MB) |
| Prompt injection in repository files (F3) | every file shown as `<<<FILE path=…` / `FILE>>>` data (delimiters cannot be forged), the system prompt says files never give instructions, AI-directed lines flagged in the trace and the UI; a model that obeys anyway is stopped by the controls above (`tests/coding/test_injection_repo.py`, Member 6's suite switched on) |

Residual risk until Sprint 8: on Linux there is no file-read or network sandbox around generated code; no memory or
process-count limit anywhere.

## 7. API and UI

`/api/coding` (router.py): `GET runs/{project}`, `GET runs/{project}/{task}` (trace, changeset, diff, revisions),
`GET …/diff`, `GET …/files[?path=]` (from the stored tarball, path-checked), `GET …/workspace.zip`,
`GET heads/{project}`, `POST …/revise` ("Request changes", bounded by `HMAP_CODING_MAX_REVISIONS`). Ownership checked
on every route (404 for another user's project). UI: `frontend/src/features/coding/` — the **Coding** tab: step cards
(outcome, files, checks, suspicious lines), the live tool-call log (model calls, edits incl. refusals, commands with
output), a unified-diff viewer, a download link, and the "Request changes" box.

## 8. Failure modes

| Situation | Behaviour |
|---|---|
| No model answer (fake mode, replay miss, no route) | loop stops, whatever exists is checked and packaged, `partial`, note `no model answer` — older demos and e2e tests keep working |
| Model edits never apply | three refusals → step ends; `partial` if nothing changed |
| Edits make tests hang | timeout → debug rounds → plateau → best round kept (rolled back) → `partial`, "no change was made" |
| Budget | `HMAP_CODING_MAX_STEPS` model calls, debug rounds, 60k debug tokens; 15-minute safety abort (`time_limit`) |
| Parallel parts run in another order (replay) | a part's prompt includes what earlier parts wrote to the head, so a new order is a replay miss → that step is `partial`; the demo's memory and RabbitMQ orders are both recorded |
| Redelivered execution | the stored result is returned (trace `done` for the same execution id) |
| Revision limit | API 409; agent returns the head unchanged with `revision_limit` |
| `stub_fail` / `stub_delay_s` | honoured like the stub (chaos and Member 4 tests) |

## 9. Differences from the plan

- **Reflexion notes are rule-made** (no extra model call); Member 4's `ReflectionMemory` needs critique objects
  that this loop does not produce. Member 4's stop policies and `Refiner` are used as planned.
- **Locator fusion is weighted** (BM25 1.0, embeddings 0.35): with equal weights, weak (fake) embeddings outvoted a
  correct BM25 top-1; zero-score BM25 files get no lexical credit.
- **Head conflicts**: redone once on the newer head as planned; a second conflict is `partial` (no third try).
- **No-op edits are refused** and **"success" needs a change** (or the model's explicit "no change needed"): the
  first demo run showed a step "succeeding" with an edit whose REPLACE equalled its SEARCH, and another whose edits
  were rolled back.
- `make coding-venv` pins pytest 9.1.1, fastapi 0.143, httpx 0.28.1, starlette 1.7, pydantic 2.14 (the backend's
  versions, so `uv` installs from its cache): the Homebrew base Python had an incompatible starlette/httpx pair.
