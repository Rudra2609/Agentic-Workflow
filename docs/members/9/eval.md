# Evaluation — Member 9: Technical documentation

Reproduce (`cd backend`): `uv run python -m tests.docgen.eval.run_eval --generate --free` (replay: the recorded
answers in `samples/llm_cache/docgen/`; rules only without `--generate`). Results:
`samples/docgen/eval_results/cloud.json` (cloud models via the team keys, recorded 2026-10-31 / 11-01),
`rules.json`, `local.json` (§3.6). The generated documents: `samples/docgen/dogfood/<repo>/`.

## 1. Gold sets
| Set | Where | Size | Used for |
|---|---|---|---|
| Seen repos | `samples/docgen/repos/` (prototype) | 3 repos with hand-written READMEs | the rules were written next to them |
| Unseen repos | Member 7's 4 project templates, the Sprint 7 starter `b2_broadcast_crash`, the Sprint 8 seeded-suite module `chatproto`, **the platform itself** (backend + infra + scripts + Makefile; routes from its OpenAPI) | 7 | rules never tuned on them (until §5) |
| Seeded false claims (seen) | `samples/docgen/seeded.json` | 31 rule-type + 3 behaviour sentences | detection per type |
| Seeded false claims (unseen) | `samples/docgen/unseen/seeded.json`, written after the rules | 25 rule-type + 2 behaviour sentences | detection per type |
| Hand-written READMEs | each repo's README, and the platform's root `README.md` | 9 documents, 130 claims | false alarms |
| Model-written READMEs | `samples/docgen/model_written/`: the model writes a README from the code alone, no facts, no checker | 9 documents, 216 claims | natural hallucinations; hand labels in `labels.json` |

## 2. Metrics
| Metric | Definition | Target (plan §3) |
|---|---|---|
| Faithfulness | grounded / (grounded + ungrounded + removed) checkable claims, before nothing is hidden | ≥ 95 %; 0 ungrounded shipped |
| Seeded detection | seeded false sentences flagged, per claim type | ≥ 90 % per type |
| False alarms | flagged claims in correct hand-written documents | 0 |
| Natural errors | precision / recall of the flags on model-written READMEs | reported |
| Endpoints | documented endpoints = code endpoints | equal on every repo |
| Coverage | public functions / classes described (docstring or model) | ≥ 80 % (summary limit permitting) |
| Examples | documented snippets run in the sandbox / failed | reported; failures fixed or removed |

## 3. Results

### 3.1 Rules (no model)
| Set | Result |
|---|---|
| Seeded, seen repos | **31/31**: TECH 8/8, COMMAND 5/5, ENDPOINT 4/4, ENV 3/3, PATH 3/3, PORT 3/3, SYMBOL 3/3, VERSION 2/2 |
| Seeded, unseen repos | **25/25**: TECH 6/6, COMMAND 5/5, PORT 4/4, SYMBOL 3/3, ENDPOINT 2/2, ENV 2/2, PATH 2/2, VERSION 1/1 |
| Behaviour sentences (seen 3, unseen 2) | 0/5 by rules (expected: they need the model layer) |
| False alarms on hand-written READMEs | **0 / 130 claims** (9 documents, incl. the platform's root README: 0/48) |

### 3.2 Generated documents (the agent, cloud models, recorded)
| Repo | Claims | Grounded | Removed | Coverage | Examples run / failed | Endpoints doc = code | Model calls |
|---|---|---|---|---|---|---|---|
| tcp_chat (seen) | 60 | 100 % | 0 | 100 % | 2 / 0 | – | 4 |
| todo_api (seen) | 85 | 100 % | 0 | 100 % | 2 / 0 | 5 = 5 | 4 |
| csv_report (seen) | 69 | 100 % | 0 | 85.7 % | 2 / 0 | 1 = 1 | 4 |
| tpl_cli | 24 | 100 % | 0 | 100 % | 4 / 0 | – | 4 |
| tpl_fastapi_service | 47 | 97.9 % | 1 | 100 % | 2 / 0 | 3 = 3 | 5 |
| tpl_python_package | 23 | 100 % | 0 | 100 % | 2 / 0 | – | 2 |
| tpl_tcp_server_client | 50 | 100 % | 0 | 100 % | 2 / 0 | – | 6 |
| b2_broadcast_crash | 52 | 96.2 % | 2 | 69.2 % | 0 / 0 | – | 7 |
| chatproto | 23 | 100 % | 0 | 100 % | 2 / 0 | – | 4 |
| **platform** (hmap itself) | **3267** | **100 %** | 0 | 30.7 % | 0 / 0 (18 checked, not run) | **84 = 84** | 7 |

- **Nothing ungrounded is shipped** (0 on every repo); faithfulness ≥ 96 % before the gate on every repo.
- The 3 removals are real model errors, caught by the behaviour layer: "a simple in-memory **CRUD** resource" for a
  service without update / delete (code shown: `@app.get("/health")` …), and a sentence with broken citations
  (`path::client.main`) saying the server "echoes lines".
- Coverage: small repos 69–100 %; the platform 30.7 % because only 60 undocumented symbols per run go to the model
  (`HMAP_DOCGEN_SUMMARY_LIMIT`, 1 500+ public symbols); everything with a docstring counts.
- Examples: every runnable snippet ran (Python snippets, `pytest`, `--help`); servers, installs and modules that
  need the project installed are checked against the facts and not run. Replay time per repo 0.3–9 s.

### 3.3 Demo (`scripts/demo_sprint_9.sh`)
code → 5 documents, 56/56 claims grounded, `pytest` from the README ran in the sandbox → injected "Redis", "port
6000", `python server.py --tls` all flagged with the reason, the true `/nick` sentence not → `docs.update` after a new
`--max-clients` option rewrote only the README (61/61 grounded) and documented the option. Replay: 0 misses.

### 3.4 Model-written READMEs (natural errors)
A model given the code but no facts writes plausible READMEs with concrete errors: `pip install -e .` without a
`pyproject.toml`, `requirements.txt` that does not exist, tests that do not exist (`tests/test_framing.py` ×4),
environment variables the code never reads (`CHAT_HOST`, `CHAT_PORT`), command-line options the server does not
have, a `LICENSE` file that is not there (all 9), unstated Python versions ("3.9+" for code using `X | Y` types).

| Labelling round | Flags | Real errors | False alarms | Precision | Real errors missed |
|---|---|---|---|---|---|
| 1st (rules as of §3.1) | 60 | 24 | 36 | 0.40 | 11 |
| 2nd (after the rule fixes of §5) | 38 | 33 | 5 | **0.87** | 0 found |

The second round is **optimistic**: the rules were fixed while reading these READMEs. The 5 remaining false alarms
are a valid `docker run` with a quoted multi-line argument, "a Dockerfile can be added later", "add a `settings.py`",
`httpx` (needed by the tests, found through `importlib.util.find_spec`, not an import) and `../variants/` (outside
the repository the checker saw). Labels and reasons: `samples/docgen/model_written/labels.json`.

### 3.5 Facts-first vs free writing (ablation)
Same model, same code: free READMEs had 33 real concrete errors in 9 documents (3.7 per document); the agent's
facts-first documents for the same repos shipped 0 (3 caught and removed before shipping). The facts-first design
is what makes the documents correct; the checker is the safety net.

### 3.6 Local model (`qwen3.5:9b`, no cloud)
Partial run (stopped when the session's usage limit was reached): tcp_chat 100 % grounded, 0 removed, 110 s; todo_api 100 % grounded, 0 removed, 177 s (~11–40 s per call). tpl_cli was not finished. Re-run: `uv run python -m tests.docgen.eval.run_eval --generate --local-only --mode live --repos tcp_chat todo_api tpl_cli --name local`.

## 4. Human rubric (5 documents, 1–5)
Scored by the assistant that built Sprint 9 while reviewing them (2026-11-01). **Member 9 should re-score.**

| Document | Correct | Complete | Readable | Useful | Note |
|---|---|---|---|---|---|
| tcp_chat README | 5 | 4 | 4 | 4 | run commands, options, env table, diagram all right; no protocol section |
| todo_api API reference | 5 | 4 | 4 | 4 | every endpoint with handler, parameters, body; no response examples |
| platform README | 5 | 3 | 3 | 4 | correct; long (86 settings, capped at 25 rows); the "Code" list of 40 modules is dense |
| platform architecture | 5 | 4 | 4 | 5 | overview + one diagram per package; every arrow an import |
| b2_broadcast_crash README | 4 | 3 | 4 | 3 | the opening paragraph calls the server an "echo server" (the code's class name); thin "Run" |

## 5. What the evaluation changed (honest list)
Found by the unseen set, the platform's own README, the browser check and the labelling, then fixed:
- false alarms: generic protocol words (TCP) as technologies; facts quoted from the code's own docstrings (now shown
  as quotations, not checked); placeholders (`<plugin>`); git-ignored paths (`.env`, `data/`); `docker-compose.obs.yml`
  not read; built-ins (`ValueError`, `str.isalnum()`); imported library names (`FastAPI()`); constants mistaken for
  env vars; `/todos/1` vs `/todos/{todo_id}`; `pip install .` with a `pyproject.toml`; dev tools (`pip install
  pytest`); the folder a clone creates (`cd todo-api`); "feature requests" vs the `requests` library; requirement
  quotes in the report;
- misses: indented code blocks; `python -m mod --flag` options; conventional files (`LICENSE`); unknown dotted module
  names; quoted continuation lines (`\`);
- generator bugs: `python cli.py` for a CLI that needs a subcommand (the example verifier caught it: now `--help`);
  internal `python -m` modules listed before `make demo`; loose scripts flooding the platform's diagram.

## 6. Honest limitations
- 31/31 and 25/25 are on sentences written for this; the model-written set (§3.4) is the realistic one.
- Behaviour claims depend on the model layer; when the code does not clearly show it, the claim is "not verified"
  (listed, not counted). The behaviour layer was never measured against a labelled set.
- The platform's coverage (30.7 %) is limited by the per-run summary budget, not by the method.
- The human rubric is the assistant's, not a person's.
