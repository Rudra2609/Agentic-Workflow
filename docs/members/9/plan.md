# Sprint 9 plan of action — Member 9: Technical documentation (+ one-command laptop demo)

Spec: [`docs/sprints/sprint-09-member9-technical-documentation.md`](../../sprints/sprint-09-member9-technical-documentation.md)
(items 9.1–9.14, platform work 9.15–9.20). Research: [`research.md`](research.md). Prototype:
[`samples/docgen/`](../../../samples/docgen/README.md). Written 2026-10-31 against the code as handed over after
Sprint 8 (`check_sprint.sh 8` PASS, 2026-10-31).

**Status (2026-10-31): defaults taken for Q1–Q8 (§1); built, stretch items included.**
See [README](README.md), [design](design.md) (§9: differences from this plan), [eval](eval.md),
[platform docs](platform/README.md).

The sprint in one line: a real `docs.generate` (+ `docs.update`) agent that reads the project's actual code (or, for
a report project, its research), writes README / API docs / architecture / summaries / report sections **from
extracted facts**, checks every technical claim against those facts (and runs the safe examples in Member 8's
sandbox), and returns a `DocBundle` with an accuracy report; plus the full one-command laptop demo (`make demo`,
`make demo-replay`, `make reset-demo`, pre-flight), the generated platform docs and `make report`.

Spec numbering skips 9.18 (it was the deployment item, removed when doc 02 §3 dropped deployment). Nothing to do.

---

## 0. What already exists (checked in the code)

| Thing | Where | State |
|---|---|---|
| `DocBundle`, `AccuracyReport` | `core/contracts/domain.py:398-412` | done (Sprint 1): `readme_ref, api_docs_ref, architecture_ref, summaries_ref, report_sections_ref` (all optional), `accuracy_report{grounded_pct, ungrounded_claims[], examples_verified, examples_failed}`. **No contract change needed** |
| `docs.generate` → `doc-bundle` | `core/contracts/capabilities.py:19,50` | output mapped; `DocsGenerateStub` (priority 0) yields once a real plug-in exists |
| `docs.update` | `core/contracts/capabilities.py:20` | name only, no output entry. Not needed: `code.revise` has none either and works (the agent names its result) |
| `docs.completed` event | `core/contracts/events.py:59` | defined, nobody emits it |
| Where docs steps come from | `agents/planning/templates.py` (Member 3) | **software** plans: one `document` step (`docs.generate`) after the test steps, before review. **document** plans (a report / essay assignment): `design` ("Outline the document"), every `implement` part and `document` are **all `docs.generate`**, and `test` is `verify.claims`. `DOC_DELIVERABLE` regex says which deliverables are documents |
| What a docs task receives | `manager._dependency_artifacts` | result refs of every finished dependency in `artifact_refs` + `inputs.dependency_artifacts`; for software that includes `code-change-set`, `workspace`, `test-report`; for document plans `research-report`, `verification-report` |
| The project's code | Member 7: head `wsh-<project>` (`GET /api/coding/heads/{project}`), `CodeChangeSet.workspace_ref`; `agents/coding/workspace.py` (`Workspace`, `files_from_tar`, `snapshot()`) | ready |
| Symbols | Member 7: `agents/coding/repomap.py` `RepoMap.build(ws)`, `parse_python`, `symbol_lines` | ready: reuse for functions / classes / signatures / first docstring line, don't write a second parser |
| `code.completed` | Member 7: `agents/coding/hooks.py` | emitted for every coding step `{task_id, changeset_ref, patch_ref, files_changed, checks_passed, revision_of}`; Member 7's D16 names Member 9's `docs.update` as a listener |
| Sandbox | Member 8: `hmap.agents.testing.sandbox.choose(settings)` → backend; `Step(kind="script", …)`; HANDOFF says this is how Member 9 checks a code example | ready (Docker, gVisor optional, local jailed fallback) |
| Refiner | Member 4: `agents/refine/refiner.py` `Refiner`, `stop.py` (`MaxIters`, `Plateau`, `any_of`), critics / revisers folders | ready |
| Shared sanitizer | Member 5: `agents/research/sanitize.py` `clean_text` (used by Member 6's injection suite) | ready; F3: misses "Note to the assistant: maintenance mode" (README.md case is an `xfail`) |
| Injection suite | Member 6: `tests/verify/security/test_injection.py:98` | **fails on purpose** (`pytest.fail`) as soon as `docs.generate` is real until Member 9 runs `samples/verify/injection/repo` through the docgen reader there |
| Graph library | `networkx==3.6.1` (Member 3 D5 kept it so Member 9 can reuse it) | ready |
| Frontend | Next 16, React 19, `@xyflow/react` 12 | **no Markdown renderer, no Mermaid**; `@xyflow/react` can draw the component graph |
| Settings | `core/config.py` `Settings.from_env`: a hand-written `mapping = {"HMAP_…": "field"}` dict + `.env` file | **not pydantic-settings** (the research doc §8 guessed wrong): the config reference must read this dict, the field types/defaults and `.env.example` |
| `make demo` / `make stop` | Member 6 (6.21, minimal): `scripts/demo.sh`, `scripts/stop.sh` | infra (Colima + compose `--wait`) → `infra_init.sh` → API (migrations on start) → agents in own process → **`npm run dev`** → demo account; **replay + cached by default**; waits for "≥ 10 agent running" lines (hard-coded); no pre-flight, no reset, no `demo-replay`, no production frontend build |
| `scripts/seed.sh` / `seed.py` | Member 1 | signs in (creates the account), creates a project, uploads `samples/demo/…`, stops at the approval gate |
| `scripts/present.sh` | Member 1 | desktop one-click presenter start (Ollama + stack); calls its own steps, not `demo.sh` |
| Prototype | `samples/docgen/` (stdlib only, **not importable** from `hmap` → port) | `inspect_repo.py` (facts + Mermaid), `grounding.py` (8 claim types), `draft_readme.py`, 3 repos, `seeded.json` (34 false sentences): 63/63 hand-written claims grounded, 80/80 drafts, 31/31 seeded caught, 0/3 behaviour claims |
| Ownership | `ownership.toml` `[members.9]`: `agents/docgen/**`, `tests/docgen/**`, `features/docgen/**`, `docs/members/9/**`, `samples/docgen/**`, `samples/llm_cache/docgen/**`, `alembic/versions/009_*`; `[cross_cutting] 9`: `Makefile`, `scripts/demo*`, `scripts/seed.sh`, `scripts/reset*`, `docs/README.md` | the row misses files this sprint must touch (Q8) |
| Git-ignored | `.gitignore`: `data/`, `logs/`, `reports/`, `samples/llm_cache/` | recordings need `git add -f samples/llm_cache/docgen` |

### Traps found while reading the code
| # | Trap | Handled by |
|---|---|---|
| T1 | `test_injection.py` calls `pytest.fail("docs.generate is real now …")` the moment the plug-in exists: `check_sprint 9` would fail | switch the docgen branch on in that test (Member 6's file → Q8 row), D15 |
| T2 | Every older demo (`demo_sprint_1…8`), `make demo` and the e2e tests now get the **real** `docs.generate` under replay, with no recordings → replay misses | degraded mode (D14): no model → facts-only docs, rules-only grounding, outcome `success` with a note; nothing waits on a model |
| T3 | Document-kind projects send the outline, every section and the final document to `docs.generate`, with research/verification refs and **no workspace**; "nothing to document" would fail every report project | two modes (D1) chosen from the inputs |
| T4 | Getting OpenAPI = importing the generated app = **running untrusted code** on the host | AST routes always; OpenAPI only inside Member 8's sandbox (D6); only the platform's own app (dogfood) is imported directly |
| T5 | Documented commands (`pip install …`, `curl …`, `rm -rf`) are untrusted; the sandbox has no network | classify each snippet: run / check-only / skip with reason (D8) |
| T6 | Prompts with unsorted facts, absolute paths, times → replay misses (Member 8's T5 again) | deterministic prompts: sorted facts, repo-relative paths, no timestamps, normalised outputs |
| T7 | A relative `HMAP_LLM_CACHE_DIR` resolves from the repo root, not `backend/`; `samples/llm_cache/` is git-ignored | demo uses `$root/samples/llm_cache/docgen/demo`; commit guide says `git add -f` |
| T8 | `docs.update` on every `code.completed` would run twice with Member 10's recovery, which re-runs test → docs → review itself (10.7) | the hook only acts when no docs task of the project is still pending and `HMAP_DOCGEN_AUTO_UPDATE` is on (D12); note for Member 10 |
| T9 | `make demo` defaults to **replay** today (Sprint 6). The spec wants `make demo` = live with pre-flight and `make demo-replay` = replay | `make demo-replay` keeps today's behaviour exactly; mid-eval notes updated (P1, T9 note to Member 1) |
| T10 | `demo.sh` waits for "≥ 10 agent running" lines: the count changes whenever an agent turns real | wait for `GET /agents/capabilities` to list every discovered capability instead |
| T11 | `next build` takes 1–2 min and ~1 GB RAM; `.next` is excluded from handoffs, so the clean copy builds once | build only when the frontend changed (hash of `frontend/src` + lockfile in `data/demo/web.hash`); log to `logs/demo/web-build.log` |
| T12 | The prototype's rules were written next to its seeds: 31/31 is an upper bound | unseen eval with model-written docs for repos the rules never saw (D19) |
| T13 | Repository files can carry prompt injections (Member 6 F3) | files are data in every prompt, sanitised, AI-directed lines flagged and never copied into docs (D15) |
| T14 | The platform's own backend: 190 modules, 59 routes; summarising everything = hundreds of model calls | summary budget (`HMAP_DOCGEN_SUMMARY_LIMIT`), docstring first, cache by file hash (D5) |
| T15 | Rendering model-written Markdown in the browser = XSS risk | own small renderer, text nodes only, no `dangerouslySetInnerHTML`, links `http(s)` only (D18) |
| T16 | `reset-demo` deletes data | path guards (`${VAR:?}`, must be inside the repo's `data/`), confirmation unless `--yes`, never touches `.env`, `samples/`, Ollama models (P3) |

---

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Two modes**, picked from the inputs. **software**: a workspace exists (see D2) → README, API docs, architecture, summaries, report sections. **document**: no workspace, but research / verification / requirement refs → the outline (`design` step), the section(s) its part asks for (`implement`), or the whole assembled document (`document` step); grounded on the research report's **verified** claims and their sources. Neither → `partial` with a note | T3; Member 3's spine |
| D2 | **What is documented** (software): the newest `workspace` among `artifact_refs` → `CodeChangeSet.workspace_ref` → `inputs.workspace_ref` → the project head `wsh-<project>` → none. Read through Member 7's `Workspace` (`snapshot()`, never `.tmp/`) | same order as Member 8 D8 |
| D3 | **Facts extractor** (9.1) `inspect/`, ported from the prototype, no model, no code run: files, modules, classes, functions (via `RepoMap`), imports, dependencies (`requirements*.txt`, `pyproject.toml` incl. extras, `package.json`), routes (FastAPI `@app.*` / `APIRouter` with `prefix`, Flask), CLI (argparse flags + choices, `click`, `typer`), env vars (`os.environ[...]`, `getenv`, `environ.get`, **the platform's `mapping` dict style** and pydantic `BaseSettings` `env_prefix`), ports (literals passed to `run`/`bind`/`listen`, `--port` defaults), entry points (`__main__`, `[project.scripts]`), tests (pytest files, counts), Docker / compose services, Makefile targets. Output `facts.json` (schema'd `Facts` model, sorted) | 9.1, T6 |
| D4 | **Architecture** (9.2) `architecture.py`: import graph (networkx) → clusters by top-level package (plus Member 3-style connected components when flat) → Mermaid `flowchart` at C4 component level (+ containers from compose / Makefile facts: API, agents, Postgres, RabbitMQ). **Every edge is checked against the import graph** in tests; nodes capped at 40 (smaller clusters folded). The model writes only the 1–2 paragraph narrative (`reasoner`), citing nodes | 9.2 |
| D5 | **Summaries** (9.3) `summarize.py`, map-reduce: function (docstring first; else `fast`, one call per file, JSON `[{symbol, summary}]`) → file → module (`fast`) → repo (`reasoner`). Every summary cites symbols as `` `path::name` ``; a citation that is not in the facts is removed and counted. Limit `HMAP_DOCGEN_SUMMARY_LIMIT=60` public symbols (most-imported first); cached by file content hash so `docs.update` reuses unchanged ones | 9.3, T14 |
| D6 | **README** (9.4) `readme.py`: fixed sections What / Run / Configuration / Endpoints / Code / Tests (+ Architecture link), all filled from facts (prototype `draft_readme.py`); the model writes only the "What" paragraph and short section intros from the facts it is given. **API docs** (9.5) `api_docs.py`: routes from the AST (method, path with prefix, params, body / response model names, docstring); OpenAPI → Markdown tables when the app can be imported **inside the sandbox** (`Step(kind="script")` printing `app.openapi()`), never on the host (T4) | 9.4, 9.5 |
| D7 | **Grounding checker** (9.6) `grounding.py`, two layers. (1) **Rules** (prototype, 8 types): TECH, COMMAND, ENDPOINT, ENV, PATH, PORT, SYMBOL, VERSION against the facts; negation-aware ("does not need Docker"). (2) **Model** for behaviour claims the rules cannot read: claim → evidence (top 3 code snippets by symbol / keyword search in the workspace) → `reasoner` JSON verdict `SUPPORTED / CONTRADICTED / NO_EVIDENCE` + quoted evidence; the quote must exist in the code or the verdict becomes `NO_EVIDENCE`. `grounded_pct` = grounded / checkable claims; CONTRADICTED and rule failures → `ungrounded_claims` ("sentence — reason"); NO_EVIDENCE is listed as *unverified*, not counted as wrong. No model → layer 2 skipped and said so | 9.6, research §5 |
| D8 | **Example verifier** (9.7) `examples.py`: every fenced `bash` / `sh` / `python` block and inline run command. **run** in the sandbox (Member 8 `choose(settings)`, `Step(kind="script")`): Python snippets, `python x.py --help`, `python -m pytest …`, scripts with documented sample input. **check only** (against facts, never run): `pip install`, `uv sync`, `npm ci`, `docker …`, `curl` to `localhost` routes (must match an ENDPOINT fact). **skip with reason**: anything else (network, `rm`, `sudo`). Result per snippet in the accuracy report; a failed run → `examples_failed` + an issue for the Refiner. Report says which sandbox backend ran | 9.7, T5 |
| D9 | **Refine loop** (9.9) `refine_hook.py`: Member 4's `Refiner` with critics = grounding (programmatic, wins) + LLM completeness (`reasoner`: required sections present, every doc deliverable covered); reviser = regenerate the offending section from facts, or delete the ungrounded sentence. Stop `any_of(MaxIters(HMAP_DOCGEN_MAX_ROUNDS=2), Plateau)`. **Final gate**: sentences still ungrounded after the loop are removed from the shipped doc and kept in the accuracy report. Trace = Member 4's `RefinementTrace` | 9.9 |
| D10 | **Report sections** (9.8) `report.py`: from `RequirementSet.deliverables` matching Member 3's `DOC_DELIVERABLE` (imported, not copied) → one section set per document deliverable, each requirement mapped to the section that answers it (coverage table in the trace, used by Member 10). software mode: design / implementation / testing sections from facts + `TestReport` (commands that passed, coverage). document mode: text built only from the research report's claims with Member 6 verdict SUPPORTED, cited by source id; unsupported / refuted claims are not used. **Member 9 does not re-verify research** (Member 6's `verify.claims` is the document plan's test step) | 9.8, T3 |
| D11 | **Artifacts** (idempotent by task id): `doc-bundle` `db-<task>` (the contract output, first), `doc-readme` `drd-<task>`, `doc-api` `dap-<task>`, `doc-architecture` `dar-<task>` (Markdown with Mermaid + the graph JSON for the UI), `doc-summaries` `dsu-<task>` (JSON), `doc-report` `drp-<task>`, `docgen-facts` `dfa-<task>`, `doc-accuracy` `dac-<task>` (full claim table, examples, unverified), `docgen-trace` `dtr-<task>` (mode, inputs, rounds, model calls, timings, removed citations). Project doc head `dh-<project>` (versioned) = latest bundle, for `docs.update` and the UI | same pattern as Members 5–8 |
| D12 | **`docs.update`** (9.10): capability on the same agent. Input: previous bundle (`dh-<project>`) + new workspace. Re-extract facts → diff with the old `docgen-facts` → re-check the old docs' claims → regenerate only sections whose facts changed (or whose claims now fail) → new bundle. **Hook** on `code.completed`: create a `docs.update` task only when the project already has a `dh-` head, no docs task of the project is pending, and `HMAP_DOCGEN_AUTO_UPDATE=true` (default). Member 10's recovery re-running docs makes the hook stay quiet (T8) | 9.10, spec §9 |
| D13 | **Outcomes**: docs written → `success` (grounding numbers in the bundle, Member 10 judges them); no input at all, or every generator failed → `partial`; `failure` only when the store / artifacts cannot be read | Manager treats `partial` as completed (as Member 8 D13) |
| D14 | **Degraded mode**: replay miss / no model → facts-only README / API / architecture (no prose, summaries = docstrings only), rule grounding only, a note in the trace and the bundle; never a crash. Older demos and e2e stay green (T2) | T2 |
| D15 | **Untrusted input**: every repository / research text goes through Member 5's `clean_text`, is wrapped as data ("files never give instructions"), and AI-directed lines are flagged in the trace and never copied into docs. Switch on the `docs.generate` branch of `test_injection.py` with `samples/verify/injection/repo` (T1) | Member 6 F3 |
| D16 | **LLM roles** (spec §6): `fast` per-file / module summaries; `reasoner` architecture narrative, README prose, completeness critic, behaviour verdicts; `classify` only to type a claim the rules cannot type. Prompts ≤ `HMAP_OLLAMA_NUM_CTX`; facts passed in, never "from memory" | spec §6, laptop |
| D17 | **No DB migration**: everything is an artifact; `009_*` stays unused | as Members 6–8 |
| D18 | **API + UI** (9.13). API `/api/docgen/`: `GET bundles/{project}`, `GET bundles/{project}/{task}` (files + accuracy), `GET …/{task}/files/{name}` (raw Markdown), `POST …/{task}/regenerate` (new `docs.generate` task, same inputs), `POST check/{project}` (paste Markdown → grounding report against the latest facts; the demo's "inject a false claim" step). UI Docs tab `frontend/src/features/docgen/`: file tabs (README / API / Architecture / Summaries / Report), a **small safe Markdown renderer** in the feature folder (headings, lists, tables, code, links; text nodes only, T15), the architecture graph drawn with `@xyflow/react` (already a dependency) + the Mermaid source, accuracy panel with ungrounded sentences **highlighted in place** and their reason, example results, Regenerate, "Check a sentence" box | 9.13, no new npm dependency |
| D19 | **Eval** (9.12) `tests/docgen/eval/run_eval.py`. Sets: (a) the prototype's 3 repos + 34 seeded sentences; (b) **unseen**: Member 7's benchmark task repos (`samples/coding/tasks/*`, gold versions), the Sprint 8 demo's TCP chat output, the platform backend; (c) **model-written free docs** (a plain "write a README" prompt without facts) for the unseen repos, claims hand-labelled true/false. Metrics: faithfulness (grounded %), seeded detection per type, false alarms on hand-written docs, detection of natural hallucinations in (c), coverage (public symbols documented / public symbols), examples run/pass, "documented endpoint / command / dependency absent from code" count (must be 0), human rubric (correct, complete, readable, useful; 1–5) on 5 docs. Modes: replay (recorded once with team keys), local-only subset | 9.12, DoD |
| D20 | **Settings** (Q5): `HMAP_DOCGEN_SUMMARY_LIMIT` (60), `HMAP_DOCGEN_MAX_ROUNDS` (2), `HMAP_DOCGEN_RUN_EXAMPLES` (true), `HMAP_DOCGEN_AUTO_UPDATE` (true), `HMAP_DEMO_MIN_FREE_GB` (live 4, replay 1.5) | |

### Platform work (5b, items 9.15–9.20)

| # | Decision | Item |
|---|---|---|
| P1 | **`make demo`** = `scripts/demo.sh` rewritten: pre-flight (P2) → toolchain (uv sync / npm ci on a clean copy) → Colima if needed → compose `up --wait` (healthchecks exist) → `infra_init.sh` → **migrations as their own step** (`hmap.db.migrate`, the same code `system.py` runs on API start; fails early with its log) → API → agents (own process, kept for `demo_chaos.sh`) → **frontend `next build` (only if changed, T11) + `next start`** → wait until `/agents/capabilities` lists every capability (T10) → seed (P4) → open the dashboard. Mode: **live** (cloud keys if present, else local Ollama). **`make demo-replay`** = the same with `HMAP_LLM_MODE=replay` + `HMAP_RESEARCH_MODE=cached` and no Ollama check = exactly today's `make demo` (T9). All logs in `logs/demo/`, state in `data/demo/`. `make stop` stops everything it started (and Ollama only if it started it) | 9.15 |
| P2 | **Pre-flight** `scripts/demo_preflight.py` (stdlib only, `--mode live|replay`, `--json` for tests): uv, npm, Docker / Colima; ports 8000, 3000, 5433, 5672, 15672 free (or ours); free RAM ≥ `HMAP_DEMO_MIN_FREE_GB` (`vm_stat` on macOS, `/proc/meminfo` on Linux); disk ≥ 2 GB; live only: Ollama answering on `OLLAMA_BASE_URL` and the default model pulled (`/api/tags`), or cloud keys present (count + fingerprint only, never the key); sandbox images present (warning only); `.env` present (warning). Each failure prints **what is wrong and the exact command that fixes it** (e.g. `OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama ollama serve`, `make stop`, `lsof -i :3000`, `make sandbox-image`) | 9.16 |
| P3 | **`make reset-demo`** = `scripts/reset_demo.sh`: `make stop` → drop + recreate the database schema → migrations (`hmap.db.migrate`) → wipe `data/artifacts` and `data/demo` caches (guards, T16; `--yes` to skip the prompt) → seed (P4). Leaves `.env`, `samples/`, Ollama models, Docker images alone | 9.17 |
| P4 | **Seed** (`scripts/seed.sh`, extended): demo account (as now) + the TCP chat project waiting at plan approval + (replay only) one finished project so every tab has something to show; idempotent (skips what exists) | 9.17 |
| P5 | **Config reference** `docs/members/9/platform/configuration.md`, **generated** by `hmap.agents.docgen.config_reference` from `Settings.from_env`'s mapping + field types / defaults + the comments in `.env.example`; a test fails when a setting has no `.env.example` line or no description (drift check). The same facts feed ENV grounding for the platform docs | 9.17 |
| P6 | **Platform docs** (9.19), generated by this agent on the platform repo, then reviewed by Member 9 by hand: README, architecture (packages, plug-ins, bus / Manager / store, laptop layout from doc 02 §3.1), API reference (from `create_app().openapi()`, trusted: it is our code), runbook (start / stop / reset / demo-replay; what to do if Ollama is down, a port is busy, Colima is stopped, a replay misses, every key is cooling down, the sandbox image is missing), troubleshooting. Output `docs/members/9/platform/`; the accuracy report must be clean (0 ungrounded). Copying into the root `README.md` / `docs/` is Member 1's call (Q6) | 9.19 |
| P7 | **`make report`** (9.20): `hmap.agents.docgen.compile_report` gathers `docs/members/*/{research,design,eval}.md` in member order → `reports/final-report.md` (git-ignored, regenerated): title, contents, one chapter per member (research → design → eval), relative links rewritten, a "missing" list (Members 10 / 11 have no design / eval yet). Runs on the current docs | 9.20 |

### Open questions for Member 1 (defaults taken when the build starts)
- **Q1 (D1):** `docs.generate` also writes the outline / sections / final document of **document** projects (Member 3 routes them there). *Default: yes.*
- **Q2 (D6, D8):** generated apps are imported (OpenAPI) and examples run **only in Member 8's sandbox**; with no Docker the local jailed runner is used, marked weaker. *Default: yes.*
- **Q3 (D12):** automatic `docs.update` after `code.completed`, only when docs exist and none are pending. *Default: on.*
- **Q4 (P1):** `make demo` becomes **live** (cloud keys / Ollama) with pre-flight; today's offline behaviour moves to `make demo-replay`. *Default: yes* (spec 9.15, doc 02 §3.3).
- **Q5 (D20):** `HMAP_DOCGEN_*` and `HMAP_DEMO_MIN_FREE_GB` in `core/config.py` + `.env.example`. *Default: yes.*
- **Q6 (P6):** generated platform docs live in `docs/members/9/platform/`; Member 1 decides whether they replace the root `README.md` sections. *Default: own folder + a link from `docs/README.md`.*
- **Q7 (D18):** no new npm dependency (own Markdown renderer, graph via `@xyflow/react`), so `frontend/package.json` is untouched. *Default: yes.*
- **Q8:** add to `[cross_cutting] 9` in `ownership.toml`: `backend/src/hmap/core/config.py`, `.env.example`, `scripts/stop.sh`, `scripts/check_sprint.sh` (only if the demo smoke needs it), `backend/tests/verify/security/test_injection.py` (T1), `README.md` (real-vs-stub row, demo commands), `HANDOFF.md`, `frontend/src/features/_registry.generated.ts`, `docs/sprints/mid-evaluation.md` (the `make demo` → `make demo-replay` rename). *Default: yes* (as for Members 7 and 8).

---

## 2. Step-by-step build

| Step | Item | Files (`backend/src/hmap/agents/docgen/` unless said) | Done when |
|---|---|---|---|
| 1 | set-up | `docs/members/9/{README,design,eval,core-requests}.md`; settings (Q5); `plugin.py` skeleton | settings tests green |
| 2 | 9.1 facts | `inspect/{__init__,python,manifests,routes,cli,env,ports,infra}.py`, `model.py` (`Facts`) | prototype repos give the same facts as `samples/docgen/out/*/facts.json`; the platform backend: 59+ routes, **all** `HMAP_*` settings found; < 2 s |
| 3 | 9.2 architecture | `architecture.py` | Mermaid parses (tested with a small grammar check); every edge in the import graph; ≤ 40 nodes |
| 4 | 9.6 grounding (rules) | `grounding/{claims,rules}.py` | prototype numbers reproduced (63/63, 31/31, 0 false alarms) as unit tests |
| 5 | 9.3 summaries | `summarize.py`, `prompts.py` | FakeLLM: docstrings kept, citations checked, fake symbol removed, cache by hash |
| 6 | 9.4 / 9.5 generators | `readme.py`, `api_docs.py` | facts-first drafts 100 % grounded; endpoints = code endpoints on all sample repos |
| 7 | 9.6 grounding (model) | `grounding/behaviour.py` | FakeLLM: quote not in code → `NO_EVIDENCE`; the prototype's 3 behaviour claims recorded live once |
| 8 | 9.7 examples | `examples.py` (calls `hmap.agents.testing.sandbox`) | broken snippet flagged; `pip install` checked, not run; `rm -rf` skipped; works on docker and local backends |
| 9 | 9.8 report | `report.py` | software + document modes; every doc deliverable has sections; only SUPPORTED claims used in document mode |
| 10 | 9.9 refine | `refine_hook.py` | seeded false sentence removed or rewritten within 2 rounds; trace has rounds |
| 11 | 9.10 agent | `agent.py`, `hooks.py` (`docs.completed`, `docs.update` hook), `plugin.py` | on the bus; idempotent; degraded mode; the stub yields; `docs.update` regenerates only changed sections |
| 12 | security | `tests/docgen/test_injection_repo.py` + the docgen branch in `test_injection.py` (Q8) | poisoned repo files never reach the docs; suite green |
| 13 | 9.13 API + UI | `router.py`; `frontend/src/features/docgen/{index.ts,DocsPanel.tsx,Markdown.tsx,ArchitectureGraph.tsx,client.ts,types.ts,logic.ts}` + tests | API tests; vitest; browser check (preview, highlights, regenerate, check box) |
| 14 | 9.11 dogfood | `samples/docgen/dogfood/{platform,tcp_chat,todo_api,csv_report,…}/` | docs for the platform + ≥ 3 sample projects; compared with the hand-written READMEs (table in eval.md) |
| 15 | 9.12 eval | `tests/docgen/eval/run_eval.py`, `samples/docgen/{unseen,model_written,eval_results}/`, `samples/llm_cache/docgen/` | numbers in `eval.md` (§3 targets) |
| 16 | P2 pre-flight | `scripts/demo_preflight.py`, `tests/docgen/test_preflight.py` | stopped Ollama and a busy port are caught with a fix line |
| 17 | P1 make demo | `scripts/demo.sh`, `scripts/stop.sh`, `Makefile` (`demo`, `demo-replay`, `reset-demo`, `report`) | `make demo-replay` from a **clean copy** (`make_handoff.sh`) with Ollama stopped → dashboard; `make demo` live; `make stop` leaves nothing running; `demo_chaos.sh` still works |
| 18 | P3 / P4 reset + seed | `scripts/reset_demo.sh`, `scripts/seed.sh` / `seed.py` | reset → seeded state twice in a row; guards tested with a fake root |
| 19 | P5 config reference | `config_reference.py`, `docs/members/9/platform/configuration.md` | drift test green; every `HMAP_*` setting documented |
| 20 | P6 platform docs | `docs/members/9/platform/{README,architecture,api,runbook,troubleshooting}.md` | generated, hand-reviewed, accuracy report clean |
| 21 | P7 make report | `compile_report.py` | `make report` writes `reports/final-report.md` from the current docs |
| 22 | demo | `scripts/demo_sprint_9.{sh,py}` | TCP chat code → docs → grounding report 100 %; inject "uses Redis" + a wrong port → both flagged; replay with 0 misses |
| 23 | 9.14 + acceptance | `backend/tests/docgen/**`, `HANDOFF.md`, `README.md` | `scripts/check_sprint.sh 9` PASS; then the Member 9 commit folder + guide (as for Member 8) |

### Stretch (after the MUST items are green; Member 1: "do everything, even optional")
| Item | How |
|---|---|
| JS / TS inspector | `package.json`, ES `import` graph, Express / Fastify routes, `process.env.X`; uses Member 8's Node image for examples |
| Diagram export PNG / SVG | own SVG writer from the graph layout (no headless browser); PNG skipped unless a converter is present |
| Docs-as-site | `mkdocs build` in the sandbox Python image when mkdocs is added there (Member 8's image → ask) or a plain static HTML export |
| Changelog from diffs | `docs.update` writes a "Changes" section from the patch refs and the facts diff |
| Docstring write-back | a patch artifact adding missing docstrings (never applied by itself; offered in the UI) |

## 3. Targets (Definition of Done)
| Metric | Target |
|---|---|
| Faithfulness on generated docs (sample + unseen repos) | ≥ 95 % grounded; 0 ungrounded after the final gate |
| Seeded false claims | ≥ 90 % caught per claim type; 0 false alarms on the hand-written READMEs |
| Natural hallucinations in model-written free docs | reported honestly (no target; the point of the facts-first design) |
| Documented endpoint / command / dependency absent from code | 0 on every sample repo |
| Coverage of public symbols | ≥ 80 % (summary limit permitting; reported) |
| `make demo` from a clean copy | dashboard up; `make demo-replay` works with Ollama stopped and Wi-Fi off |
| Demo `demo_sprint_9.sh` | code → docs → grounding report; injected false claim flagged |

## 4. Paths outside Member 9's folders (need Member 1 sign-off, Q8)
`Makefile`, `scripts/demo.sh`, `scripts/demo_preflight.py`, `scripts/demo_sprint_9.{sh,py}`, `scripts/stop.sh`,
`scripts/seed.sh` / `seed.py`, `scripts/reset_demo.sh`, `backend/src/hmap/core/config.py`, `.env.example`,
`backend/tests/verify/security/test_injection.py`, `README.md`, `HANDOFF.md`, `docs/README.md`,
`docs/sprints/mid-evaluation.md`, `frontend/src/features/_registry.generated.ts`, `ownership.toml`.

## 5. Not Member 9's work
| Work | Owner |
|---|---|
| Checking that the required docs are present and judging them in the final review; the `DOC_MISMATCH` failure class; re-running docs during recovery | Member 10 (reads `DocBundle.accuracy_report`) |
| Golden end-to-end scenarios, `scripts/demo_final.sh`, the cross-agent contract suite (incl. M9 → M10), "no silent stubs" | Member 10 |
| Model tiers, `scripts/pull_models.sh`, warm-up, choosing the demo tier with `make demo` (11.17), the release gate and clean-copy sign-off, the final slides (11.23 uses `make report`'s output) | Member 11 |
| The sandbox itself, its images and limits | Member 8 (Member 9 only calls `choose()` / `Step`) |
| The coding agent, the workspace head, `RepoMap` | Member 7 (reused, not changed) |
| Verifying research claims for document projects | Member 6 (`verify.claims`) |
| The shared sanitizer and its F3 gap | Members 5 / 6 |
| Which plan steps call `docs.generate` | Member 3 |
| Observability, Grafana, the ops runbook for traces | Member 4 (the platform runbook links to it) |
