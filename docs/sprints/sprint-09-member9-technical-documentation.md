# Sprint 9 — Member 9: Technical Documentation

**Owner:** Member 9 · **Needs:** Sprint 8 accepted · **Unblocks:** Sprint 10 (review checks docs deliverables)
**Replaces stub:** `docs.generate` → `agents/docgen/`

## 1. Goal
Generate **accurate** technical documentation (README, API docs, architecture, code summaries, report sections) from the *actual* repository, and **mechanically verify** that documentation claims are grounded in the code (“if there’s no Redis, never say Redis”).

## 2. Provided
`CodeChangeSet`/workspace, `TestReport` (can confirm commands work), M7 RepoMap (reuse), M8 sandbox (verify code examples run), M4 Refiner, gateway (`reasoner`, `fast`), `RequirementSet`/deliverables list (which docs are required), UI shell.

## 3. Research deliverable
Code summarization (hierarchical/map-reduce, docstring vs LLM), architecture extraction (import/call graphs, module clustering, C4 model, Mermaid generation), API doc generation (OpenAPI export, Sphinx/mkdocs/pdoc), README best practices, **documentation accuracy / grounding / hallucination detection**, doc-code drift, evaluation metrics (faithfulness, coverage).

## 4. Design

```text
repo/workspace
 → [Inspector] AST walk → facts DB: modules, classes, functions, routes (FastAPI/Flask), CLI args, env vars, dependencies (pyproject/requirements), entrypoints, ports, tests present
 → [Architecture] import graph → clusters → Mermaid component diagram; data-flow where detectable
 → [Summarizer] function → file → module → repo (map-reduce; each summary cites symbols)
 → [Generators] README (template + facts), API docs (from routes + OpenAPI + docstrings), architecture doc, setup/run, report sections (from RequirementSet deliverables)
 → [Grounding checker] extract technical claims from generated docs (tech names, endpoints, commands, versions, file paths, env vars) → verify against facts DB; ungrounded ⇒ issue
 → [Example verifier] run documented commands/snippets in M8 sandbox where safe
 → M4 Refiner loop (critic = grounding checker + LLM completeness) → DocBundle {readme, api, architecture, summaries, accuracy_report}
```

## 5. Work items

### MUST
| # | Item | Files (`agents/docgen/`) | Acceptance |
|---|---|---|---|
| 9.1 | Facts extractor (AST + manifests + routes + env + ports) → `facts.json` | `inspect/` | complete on sample repos |
| 9.2 | Architecture extractor + Mermaid generator | `architecture.py` | valid Mermaid; matches import graph |
| 9.3 | Hierarchical summarizer with symbol citations | `summarize.py` | summaries cite real symbols |
| 9.4 | README generator (templated sections filled from facts; LLM only for prose) | `readme.py` | |
| 9.5 | API documentation generator (routes, params, models; OpenAPI → markdown) | `api_docs.py` | endpoints = code endpoints |
| 9.6 | **Grounding checker**: claim extraction + fact-DB matching (tech stack, endpoints, commands, paths, versions) | `grounding.py` | detects injected false claims (Redis example) |
| 9.7 | Code-example/command verifier via M8 sandbox | `examples.py` | broken snippet flagged |
| 9.8 | Report-section generator mapped to required deliverables (from `RequirementSet`) | `report.py` | |
| 9.9 | M4 integration; accuracy score in `accuracy_report` | `refine_hook.py` | |
| 9.10 | `DocAgent` capability `docs.generate` (+ `docs.update` for drift after revisions) | `agent.py` | on bus; idempotent |
| 9.11 | **Dogfood**: generate docs for the platform’s own repo and for ≥3 sample generated projects | `samples/docgen/` | compare to hand-written |
| 9.12 | Eval: faithfulness (grounded claim %), coverage (public symbols documented), seeded-false-claim detection, human rubric on 5 docs | `tests/docgen/eval/` | `eval.md` |
| 9.13 | API + UI: doc preview (markdown render), grounding report with highlights of ungrounded claims, regenerate | `agents/docgen/router.py` (auto-mounted), `frontend/src/features/docgen/` (auto-registered) | |
| 9.14 | Tests (unit/contract/integration/replay) | `tests/docgen/` | green |

### STRETCH
Multi-language (JS) inspector; diagram export to PNG/SVG; docs-as-site (mkdocs build); changelog from diffs; docstring write-back PR-style patch.

## 5b. Platform-wide responsibility: One-Command Laptop Demo & Platform Documentation (also owned by Member 9)

Why here: the documentation owner must document how the platform **really** runs. There is **no deployment** — the demo runs natively on Member 1's laptop (doc 02 §3) — so this is about making that run one command and reproducible.

| # | Item | Acceptance |
|---|---|---|
| 9.15 | `make demo`: Docker infra up → wait healthy → migrations → seed → API + single agent host + Next.js production build (`next build && next start`), all natively, logs to `./logs/`; `make stop` tears it down; `make demo-replay` = same with `HMAP_LLM_MODE=replay` | one command from a clean copy → dashboard open |
| 9.16 | Pre-flight check in `make demo`: Ollama running, default model pulled, free RAM ≥ threshold, ports free; prints a clear fix for each failure | catches a stopped Ollama / busy port |
| 9.17 | Migrations-on-start, `seed.sh`, **reset-to-demo-state** (DB + `./data/artifacts`), `.env.example` + full config reference | clean copy → running demo |
| 9.19 | **Platform docs generated by this sprint's agent (dogfood) then human-reviewed**: README, architecture, API reference, runbook, troubleshooting | grounding report clean |
| 9.20 | **Final-report compiler**: `make report` assembles every `docs/members/*/{research,design,eval}.md` into one report skeleton | runs on current docs |

Definition of Done addition: `make demo` works on a clean copy on Member 1's laptop, and `make demo-replay` works with Ollama stopped.

## 6. Local-LLM notes
Facts-first generation — LLM writes prose around **provided facts**, not from memory; summaries per small unit fit any context; `fast` for per-function summaries, `reasoner` for architecture narrative.

## 7. Interface handed to Member 10
```text
Artifact: DocBundle {readme_ref, api_docs_ref, architecture_ref, summaries_ref, report_sections_ref, accuracy_report{grounded_pct, ungrounded_claims[]}}
Event: docs.completed {task_id, bundle_ref}
Review uses: presence of required doc deliverables, accuracy_report, example-verification results.
```

## 8. Definition of Done (additions)
- [ ] Grounded-claim rate ≥ target on sample repos; seeded false claims detected
- [ ] No documented endpoint/command/dependency absent from code on sample repos
- [ ] Demo `demo_sprint_9.sh`: code → docs → grounding report; inject false claim → flagged

## 9. Risks
Hallucinated tech in prose → grounding gate; stale docs after revisions → `docs.update` triggered by `code.completed`; large repos exceed context → hierarchical summaries.
