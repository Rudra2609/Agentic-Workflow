# Design — autonomous research (Member 5)

Decisions D1–D22 are in [plan.md](plan.md) §1. This page shows how the built code fits together.

## 1. Modules (`backend/src/hmap/agents/research/`)

```
model.py        Hit, Page (cleaned text + sha256), Chunk, Scored, EvidenceDraft, RoundTrace, ResearchTrace (artifact)
providers/      SearchProvider protocol, SearchCache, CachedProvider (obeys the mode), get_providers() (public):
                Wikipedia (API + TextExtracts), arXiv (Atom API, abstracts), DuckDuckGo (ddgs), local (BM25 corpus)
corpus.py       PageStore: committed corpus (samples/research/corpus) + local cache (data/research_cache/pages), BM25
fetch.py        Fetcher: inline text -> page store -> network (online only): SSRF guard, robots.txt, rate limit,
                retries, size / type limits; FetchResult says why a page was not read
clean.py        HTML -> sanitize.strip_hidden_html -> trafilatura main text; PDF -> Member 2's load_pdf; page_from_text
sanitize.py     hidden HTML removal, invisible characters, AI-directed lines removed (counted), wrap() for prompts
index.py        chunk_page (sentence-aligned ~800 chars, 120 overlap); HybridIndex = RRF(dense cosine, keyword);
                MemoryBackend (numpy-free cosine + BM25Plus), PgBackend (research_chunks, pgvector + tsvector);
                falls back to keyword-only when embeddings fail
select.py       score = relevance x authority x recency x (0.5 + 0.5 novelty), same-page penalty, near-dup drop
planner.py      brief -> sub-questions (2-4 per question, 2-3 queries each, success criteria); rule fallback
evidence.py     triage (fast) -> extraction (reasoner, <= 4 chunks / 6 000 chars per call) -> quotes.locate check
quotes.py       verbatim match ignoring only typography; returns the span in the original text
stop.py         coverage per sub-question; AllCovered + LowNovelty + Member 4's Budget / MaxIters; reason mapping
synthesize.py   claims per sub-question citing evidence ids; citation check (always); summary_markdown;
                refine_setup() for Member 4's refinement (task.refine)
pipeline.py     run_research(): the rounds; build_report()
agent.py        ResearchAgent (research.run): brief from the task, artifacts, progress, idempotency, refinement,
                failure-injection hooks (stub_fail / stub_delay_s, for chaos tests and the mid-eval demo)
router.py       /api/research/{runs, runs/{pid}/{task}, pages/{pid}/{artifact}, providers}
plugin.py       PLUGIN (priority 100): agent, router, hooks research.completed + project.deleted
backend/alembic/versions/005_sprint_5_research.py   research_chunks (+ CREATE EXTENSION vector)
frontend/src/features/research/                      the Research tab
```

## 2. Data flow: one research step

```
Manager assigns research.run (inputs.research_questions from Member 3's plan; dependency artifacts attached)
  agent: failure_injection(task)  ->  build_brief: questions (<= 5), scope (objective + latest requirement-set),
         constraints (acceptance criteria), budget (inputs.budget), follow_up_of            -> research-brief
  run_research:
    plan            reasoner: sub-questions S{q}.{n}, queries, success criteria  (rules without a model)
    round r = 1..:  for each open sub-question: its r-th query -> every provider (cached / online)
                    new hits -> Fetcher (inline | store | network) -> Page -> HybridIndex.add (chunks + embeddings)
                    per open sub-question: HybridIndex.search(sub + query, only this run's pages) -> select (top 3)
                    triage (fast) -> extract (reasoner) -> quotes.locate on the page text -> EvidenceDraft
                    coverage update -> Member 4's LoopState -> policy: all_covered | low_novelty | budget | max_rounds
                    progress(trace) -> task.progress (research-trace ref)
    synthesise      reasoner claims citing evidence ids -> citation check -> report (+ summary_markdown)
  store             research-page per cited page (content-addressed rp-<sha>), research-report, research-trace
  task.refine       Member 4's refine_result(report): citation critic + rubric judge + TargetedReviser (claims only)
hook task.completed(research.run) -> research.completed {task_id, report_ref, stop_reason, counts, coverage}
```

Only the planner's sub-questions produce queries, and links in pages are never followed. Page text can only become
evidence, and only after the verbatim check.

## 3. Modes, cache and recordings

| Mode | Search | Pages | Network |
|---|---|---|---|
| `online` | cached result, else live (then cached in `data/research_cache/search`) | inline / store / live (then stored) | yes |
| `cached` (default) | cached results only (committed `samples/research/search_cache` + local cache); a miss = no hits | inline / store only; a miss = "not in cache" | **never** |
| `local` | only the `local` provider (corpus + the project's own documents) | store only | never |

Recorded model answers and embeddings live in `samples/llm_cache/research/` (replay). The research mode and the LLM
mode are independent: the demo and the tests run `cached` + `replay`, so they need no network, no keys and no Ollama.
The embedding model is local only. Recording embeddings needs Ollama, and `HMAP_LLM_RECORD_MISSING` now fills
missing embeddings too (a gateway change). Embeddings are stored rounded to 6 decimals to keep the files small.

The research budget is in **tokens** by default (60 000), plus `max_rounds`. Wall-clock time differs between a
recording and its replay, so a default time cut would make the replay take another path and miss its recordings. A
time limit applies only when a brief sets `max_seconds`.

## 4. Storage and events

| What | Where |
|---|---|
| Brief | artifact `research-brief` (`rb-<task_id>`) |
| Trace | artifact `research-trace` (`rt-<task_id>`), a version per round (progress) + the final one |
| Report | artifact `research-report` (contract `ResearchReport`; a refined report is its next version) |
| Pages | artifact `research-page` (`rp-<sha256[:32]>`), the cleaned text the quotes are checked against |
| Index | table `research_chunks` (Postgres) or the in-process memory backend; deleted on `project.deleted` |
| Events | `task.progress` per round (trace ref), `research.completed` |

Contract additions (D2, additive): `SubQuestion`, `ResearchReport.sub_questions`, `Source.{provider, kind,
retrieved_at, content_sha256, page_artifact}`, `ResearchBrief.follow_up_of`.

## 5. Prompts (version 1)

| Step | Role | Output schema | Notes |
|---|---|---|---|
| Plan | `reasoner` | `PlanAnswer{sub_questions[{question, text, queries, success_criteria}]}` | queries cleaned of URLs / operators |
| Triage | `fast` | `TriageAnswer{relevant[]}` | 500 characters per passage, wrapped as untrusted |
| Extract | `reasoner` | `ExtractAnswer{evidence[{passage, sub_question, quote, why}]}` | "copy EXACTLY"; checked in code |
| Synthesise | `reasoner` | `SynthesisAnswer{claims[{sub_question, text, evidence_ids}]}` | no outside knowledge; checked in code |
| Refine (optional) | `judge` | Member 4's rubric R1 completeness, R2 support | reviser may change `/claims` and `/summary_markdown` only |

## 6. Failure modes

| Failure | Behaviour |
|---|---|
| A provider fails / rate-limits | counted in the round (`search:<provider>`), the other providers continue |
| A page is blocked / robots / too big / wrong type / not in cache | counted per reason in the round; not read |
| No embeddings (no Ollama, missing recording) | keyword-only search; noted in the trace |
| A model call fails (or no recording) | planner, triage, extraction and synthesis fall back to rules |
| A quote is not on the page | dropped and counted |
| Nothing found | `stop_reason = no_sources`, an honest empty report ("No sourced answer found") |
| Cancelled | propagates between steps; the Manager handles it as usual |
| Redelivered task | the stored result is returned (same artifacts) |

## 7. Security and privacy
- **SSRF:** only http(s) on ports 80/443. Names are resolved, and loopback, private, link-local, multicast and
  reserved addresses are refused, again after every redirect. `localhost`, `.local`, `.internal` and `.test` are
  refused outright. Tested.
- **Prompt injection:** see `sanitize.py` and §2. An injected page leaves the queries, claims and quotes unchanged
  (tested).
- **Privacy:** `cached` is the default, so a private assignment's questions never reach a search engine unless
  someone switches to `online`. Spans carry the provider, host and counts, never the query text or page text.
- **Licences:** only permissively licensed pages are committed (`samples/research/LICENSES.md`, checked by a test).
