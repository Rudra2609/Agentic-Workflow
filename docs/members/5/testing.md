# Testing — autonomous research (Member 5)

Everything runs offline: a scripted `FakeLLM` (with 8-dimension fake embeddings), mock HTTP transports, a temporary
page store, the in-memory index, or replay of `samples/llm_cache/research/`. No key, no network and no Ollama are
needed. The integration test needs `make infra-up` (RabbitMQ + Postgres with pgvector) and is skipped without it.

```bash
cd backend
uv run pytest tests/research -q
uv run pytest -q                          # everything (Sprint 1–4 suites included)
cd ../frontend && npm test                # incl. features/research
```

## Backend (`backend/tests/research/`, 57 tests)

| File | Tests | What it proves |
|---|---|---|
| `test_quotes_sanitize.py` | 5 | verbatim match ignores only typography (spaces, dashes, curly quotes, ellipsis) and returns the original span; paraphrase, different case, too-short and too-long quotes refused; hidden HTML (`display:none`, `hidden`, `aria-hidden`, scripts) removed; AI-directed lines removed and counted; `wrap()` cannot be closed from inside; the page hash is over the cleaned text |
| `test_fetch_providers.py` | 20 | **SSRF guard**: 12 local / private / odd URLs refused, a public name resolving to 127.0.0.1 refused, a redirect to 127.0.0.1 refused before any request; fetch → clean → store; robots.txt disallow; **a re-run in `cached` mode makes 0 network calls**; size limit, type limit, 503 retries, per-host spacing; inline text needs no fetch; search cache obeys the mode (online fills it, cached never calls); the local provider finds the project's own documents; registry order / `local` mode; Wikipedia and arXiv API parsing |
| `test_index_select.py` | 5 | sentence-aligned overlapping chunks pointing into the text; hybrid search, re-indexing the same text is a no-op, URL filter, project isolation, delete; **keyword-only fallback when embeddings fail**; authority / recency; selection keeps a breakdown, drops near-duplicates |
| `test_plan_evidence_stop.py` | 8 | planner: model sub-questions with cleaned queries, out-of-range dropped, **every brief question covered** (rule fallback), rules without a model; **a lying model's invented quote never survives** (dropped and counted); rule extraction is verbatim; coverage formula (one site alone never "answers"); stop reasons mapped; **hypothesis: every research loop stops within its rounds** (150 examples); synthesis keeps only properly cited claims, markdown with numbered sources, citation critic |
| `test_pipeline_agent.py` | 7 | **an injected page changes nothing** (same queries, claims, quotes; injection lines counted); the report is cited, quotes are in their pages with matching hashes, sources = cited pages with breakdowns, trace recorded; nothing found → honest `no_sources`; follow-up keeps earlier evidence and ids; cancellation propagates; **on the bus via the API**: ad-hoc research → report / trace / brief / pages, run list + detail, page spans highlight the quote, `research.completed` + `task.progress`, ownership 404, CSRF 403, 422; **a plan's research step completes and the verify step waits for it** |
| `test_corpus_agent_extras.py` | 5 | every committed corpus page has a permissive licence (= the curation table) and its hash; LICENSES.md lists them; gold-set shape; **a redelivered task returns the stored result**; `task.refine` adds a refinement trace (Member 4's refinement); the failure-injection hooks (`stub_fail`) work on the real agent |
| `test_adversarial_pages.py` | 6 | each of the 4 poisoned pages: no instruction text after cleaning, the facts survive; every sample listed; **cleaning is deterministic whatever was read before** (the trafilatura de-duplication trap) |
| `test_integration_real.py` | 1 | **over RabbitMQ + Postgres**: ad-hoc research on the real stack, chunks + embeddings in `research_chunks` (pgvector), `research.completed` in Postgres, deleting the project removes its index rows |

Changed in Member 1's tests:
- `tests/db/test_migrations.py`: the expected revision is the newest head, not `001b`; members' tables
  (`MEMBER_TABLES`) are expected, and ignored when comparing with the models.
- `tests/core/llm/test_gateway.py` (+1): replay with `HMAP_LLM_RECORD_MISSING` fills missing **embeddings**, others
  stay strict, recorded vectors replay without a model call.

## Frontend (`frontend/src/features/research/`, 8 tests)

| File | Tests | What |
|---|---|---|
| `logic.test.ts` | 5 | grouping by question, claims per sub-question, source numbering, plain words, only http(s) links, excerpt around the quote, event key, question parsing |
| `ResearchPanel.test.tsx` | 3 | sub-questions with status and coverage, findings with citations, sources with score parts, the quote highlighted in the saved page with its licence; developer mode (cost, refused findings, pages not read, refused quotes); asking a new question |

## Evaluation harness (not run by `pytest`; numbers in [eval](eval.md))
`tests/research/eval/run_eval.py`: offline evaluation on the 10 gold questions (+ the demo brief), ablations
(retrieval hybrid / dense / keyword, synthesis with / without refinement), fact recall@k, `--harvest` / `--curate`
to rebuild the corpus, `--local-only`.

## Checked by hand
The Research tab at desktop and 375 px phone width, light and dark (screenshots in the final report); the demo
`scripts/demo_sprint_5.sh` in memory and on RabbitMQ + Postgres with agents in a separate process.
