# Sprint 7 — Member 7: Autonomous Coding

**Owner:** Member 7 · **Needs:** Sprint 6 accepted · **Unblocks:** Sprint 8 (testing consumes its output)
**Replaces stub:** `code.implement` → `agents/coding/`

## 1. Goal
A coding agent that takes a plan task, **understands a repository, locates relevant files, plans a change, edits code with tools, runs checks, debugs, and returns a `CodeChangeSet`** — using a local coder model. Also handles `revision.request` (fix what review/tests reported).

## 2. Provided
Bus/runtime, gateway (`coder`, `reasoner`, `embed`), artifact store, `TaskGraph` tasks (+ acceptance criteria), M4 Refiner, M5/M2 helpers (embeddings, loaders), UI shell. (M8 testing is *not* available yet → Sprint 7 uses lightweight local checks: syntax, `ruff`, quick `pytest` run inside a path-jailed subprocess; Sprint 8 upgrades to Docker.)

## 3. Research deliverable
Coding agents (SWE-agent ACI, Aider repo-map, OpenHands, AutoCodeRover, Agentless), repository understanding (AST, tree-sitter, repo maps, embedding+BM25 retrieval, call graphs), tool-use design (read/search/edit/run, edit formats: diff vs whole-file), debugging loops, benchmarks (HumanEval, SWE-bench-lite — realistic expectations for a 7B model), safety (path jail, command allow-list).

## 4. Design

```text
TaskAssign{objective, acceptance_criteria, repo/workspace ref, context}
 → [Workspace] copy/clone to per-task sandbox dir (local `git init` inside the *workspace* for diffs — unrelated to our project repo)
 → [RepoMap] tree-sitter/ast symbols + file summaries + embeddings index (cached by file hash)
 → [Locator] BM25+embedding+LLM rerank → relevant files/symbols (budgeted to context)
 → [Planner] small plan: files to create/modify, steps, test idea
 → [Editor] tool loop (LangGraph optional): read_file | search | write/patch (search-replace blocks validated) | run_cmd(allow-list) | run_tests
 → [Debugger] on failure: parse traceback → hypothesis → fix; bounded iterations (M4 StopPolicy)
 → [Packager] unified diff + files + commands_run + notes → CodeChangeSet artifact
```
Edit format: **search/replace blocks or unified diff** (more reliable than whole-file for small models); applied by code with validation, rejected edits fed back to the model.

## 5. Work items

### MUST
| # | Item | Files (`agents/coding/`) | Acceptance |
|---|---|---|---|
| 7.1 | Workspace manager (create from artifact/template, snapshot, diff) with **path jail** | `workspace.py` | no escape from workspace (tests incl. `../`, symlinks) |
| 7.2 | RepoMap: file tree + symbol index (tree-sitter or `ast` for Python), summaries, embedding index | `repomap.py` | map fits budget; incremental update |
| 7.3 | Locator: hybrid retrieval + rerank | `locate.py` | top-3 hit rate on mini-benchmark |
| 7.4 | Tool layer: read/search/list/patch/write/run_cmd/run_tests with allow-lists, timeouts, output truncation | `tools/` | each tool unit-tested; denied commands audited |
| 7.5 | Edit applicator: search/replace + diff apply with fuzzy-match guard, syntax check after edit | `edits.py` | bad edit rejected with actionable error |
| 7.6 | Planner + agent loop (LangGraph recommended, optional extra — doc 01 §3) (understand→plan→edit→check→debug) | `loop.py` | terminates with budget |
| 7.7 | Debug loop: traceback parsing, minimal repro, retry w/ Reflexion note (M4) | `debug.py` | fixes seeded bugs |
| 7.8 | Context budgeter: choose file slices/summaries to fit 7B’s window | `context_budget.py` | never exceeds limit |
| 7.9 | `CodingAgent` capability `code.implement` (+ `code.revise` handling `revision.request` w/ feedback from M8/M10) | `agent.py` | on bus; idempotent |
| 7.10 | Scaffolding templates (python package, FastAPI service, TCP server/client, CLI) for common assignment types | `templates/` | greenfield tasks bootstrap quickly |
| 7.11 | M4 integration: self-review critic (lint/syntax/test programmatic + LLM) before returning | `review_hook.py` | uses `Refiner` |
| 7.12 | **Mini benchmark**: 10–15 tasks (greenfield + modify-existing + bugfix, incl. “TCP chat with multi-client”) with hidden tests | `samples/coding/` | |
| 7.13 | Eval: pass@1 / pass@k with hidden tests, edit-apply success %, tokens, time; model comparison (`coder` vs `reasoner`) | `tests/coding/eval/` | `eval.md` honest numbers |
| 7.14 | API + UI: task view with live tool-call log, file diff viewer, run output | `agents/coding/router.py` (auto-mounted), `frontend/src/features/coding/` (auto-registered) | |
| 7.15 | Tests: jail, edits, repomap, loop (FakeLLM scripted), integration in `replay` | `tests/coding/` | green |

### STRETCH
Multi-file refactors; JS/TS support; dependency installation in workspace (offline wheel cache); parallel sub-task coding; conversation-memory across revisions.

## 6. Local-LLM notes
`coder` — runs on the team's cloud key pool first when keys are set (doc 02 §2.5), and on local `qwen3.5:9b`
when no key is free, none is configured, or the project is kept on this computer (`task.cloud_ok` false). Design
for the local model: keep prompts short; one file slice at a time; deterministic temperature; model likely solves small tasks, not large repos → tasks must be small (planner’s depth cap, Sprint 3). Record all successful trajectories (fine-tune data for Sprint 11).

## 7. Interface handed to Member 8
```text
Artifact: CodeChangeSet {task_id, workspace_ref (tar/dir artifact), patch_ref, files_changed[], commands_run[], notes}
Event: code.completed {task_id, changeset_ref}
Input M8 also needs: the task’s acceptance_criteria + any tests present in the workspace.
Feedback in: revision.request{required_changes[], context_refs[TestReport|Review]} → code.revise
```

## 8. Definition of Done (additions)
- [ ] Benchmark pass-rate reported; at least the TCP-chat scaffold task succeeds end-to-end
- [ ] Path jail & command allow-list security tests pass
- [ ] Revision loop (`code.revise`) works on a seeded failing change
- [ ] Demo `demo_sprint_7.sh`: plan task → code agent produces working code → diff visible in UI

## 9. Risks
7B model too weak for multi-file edits → small tasks, templates, search/replace edits, retries; runaway tool loops → step/time budgets; unsafe commands → allow-list + workspace jail (hard security boundary arrives with M8’s Docker).
