# Sprint 5 plan of action — Member 5: Autonomous research

Spec: [`docs/sprints/sprint-05-member5-autonomous-research.md`](../../sprints/sprint-05-member5-autonomous-research.md).
Goal: a real `research.run` agent that turns a plan step's research questions into a **cited `ResearchReport`**. It
plans sub-questions, searches, fetches, indexes, selects sources, extracts quotes that are checked word for word,
tracks coverage, stops on a clear rule, and synthesises claims that each cite evidence. It runs on local models and
has an **offline (cached) mode**, so the mid-evaluation demo never needs the internet. Member 6 also finishes before the
**mid-evaluation**, so Member 6 owns the readiness gate; Member 5 delivers the research part of the demo (§1 D20).
Written 2026-10-14 against the code as handed over after Sprint 4.

Items marked **(M1)** touch paths Member 1 owns (`ownership.toml`). As in Sprints 3 and 4, Member 5 makes these
changes itself and lists them in the commit message (no `core-requests.md`). The folders of Members 2, 3 and 4 are
**not edited**: their code is only called through public functions.

**Status (2026-10-14): built** following §1 — see [README](README.md), [research](research.md), [design](design.md),
[eval](eval.md), [testing](testing.md). Differences from this plan, found while building:
- The default research budget is in **tokens** (60 000), not 180 s: wall-clock time differs between a recording and
  its replay, so a time cut made replays take another path. A time limit applies only when a brief sets one.
- Coverage needs **two sites**: one site alone tops out at 75 %.
- Triage (`fast`) runs only for more than 8 passages; extraction asks for 1–3 sentences per useful passage. The
  first version extracted too little (fact coverage 0.33 → 0.68).
- The index embeds at most 40 chunks per page.
- `HMAP_LLM_RECORD_MISSING` now also fills missing embeddings, stored as float16 base64 (a gateway change).
- trafilatura's de-duplication is off (it is process-wide, so the same page cleaned differently).
- BM25**Plus** instead of Okapi (Okapi scores nothing on small corpora).
- The agent honours the failure-injection inputs (`stub_fail`, `stub_delay_s`), as the stub did: Member 4's tests
  and the chaos tests inject failures on `research.run`.
- Member 1's migration test now expects the newest head and members' tables.

---

## 0. What already exists (do not rebuild)

| Piece | Where | What it gives Member 5 |
|---|---|---|
| Contracts | `core/contracts/domain.py` | `ResearchBudget{max_rounds 3, max_sources 20, max_tokens, max_seconds}`, `ResearchBrief{task_id, questions, scope, constraints, budget}`, `Evidence{id, url, quote, content_sha256, retrieved_at, sub_question, page_artifact}`, `Claim{id, text, evidence_ids≥1}`, `Source{url, title, score, score_breakdown}`, `ResearchReport{…, coverage, stop_reason, summary_markdown}` (validator: every cited evidence id exists) |
| Capability / event | `capabilities.py`, `events.py` | `research.run` → (`research-report`, `ResearchReport`); `research.completed` declared, nobody emits it yet |
| The stub | `agents/stubs/agents.py` (`stub-research-run`) | stands down automatically when a higher-priority plug-in serves `research.run` |
| Research seeds | Member 3's planner; `Manager.submit_graph` | every plan task's `inputs` hold `research_questions`, `requirement_ids`, `phase`, `plan_task_id`, `graph_version`; dependency results arrive as `artifact_refs` + `inputs.dependency_artifacts` |
| Plan shape | Member 3 | a `research` spine step (no dependencies, 2–5 questions), sometimes more `research.run` steps; `verify` (`verify.claims`, still a stub) depends on research |
| LLM gateway | `ctx.llm` | roles `reasoner`, `fast`, `judge`, `classify`, `embed` (always local `nomic-embed-text`, 768 dims); modes fake / replay / record / live; per-plug-in replay cache `samples/llm_cache/research/`; `HMAP_LLM_RECORD_MISSING=research` |
| Postgres | `infra/docker-compose.yml` uses `pgvector/pgvector:pg16` | the extension is available but **not created**; migrations exist only for `001` / `001b`; `005_*` is Member 5's |
| Document loaders | Member 2: `hmap.agents.doc_intel.loaders` (`load_pdf`, `load_docx`, `load_text`, `detect_kind`) | PDF / DOCX sources and the project's own uploads for the local corpus |
| Refinement | Member 4: `hmap.agents.refine` (`RefinementMixin`, `ProgrammaticCritic`, `LLMRubricCritic`, `TargetedReviser`, `StopPolicy` combinators, `Budget`, `MaxIters`, `best_index`) | synthesis checking (5.9) and the research loop's stop rules (5.8) without writing a second framework |
| Observability | Member 4: `hmap.obs.span(...)`, metrics registry, the Ops page | spans and metrics for search and fetch; failures explained on the Ops page for free |
| Plug-in system | `core/plugins.py` | `Plugin(agents, router, manager_hooks, refiners, …)`; `@hook("task.completed", capability=…)`, `manager.emit(DomainEvent)`, `project.deleted` event; routers auto-mounted, frontend features auto-registered |
| Libraries already installed | `pyproject.toml` | `httpx`, `lxml`, `beautifulsoup4`, `numpy`, `psycopg` |

Downstream users (from their sprint files). The interface must serve them:

| Who | What they need from Member 5 |
|---|---|
| Mid-evaluation | live research step: sub-questions, sources, evidence quotes, coverage, stop reason; **works offline**; same result in `live` and `replay`; the agent can be killed mid-task (failure injection) |
| Member 6 (verify) | `ResearchReport` + cached page artifacts with `content_sha256` (L1 re-check); **search providers through a public interface** (6.4); follow-up research for gaps (6.8); the poisoned-page samples for the injection suite (6.13) |
| Member 7 (coding) | "M5/M2 helpers (embeddings, loaders)": the chunk + embed + hybrid-search index as a reusable module |
| Member 10 (review) | `ResearchReport` as evidence in the review; the M5 → M6 pair in the cross-agent contract suite |
| Member 11 (routing) | the fact-coverage gold set and evaluator for the model benchmark; recorded traces |

---

## 1. Decisions (recommendations; settle before Phase C)

| # | Topic | Recommendation | Why / alternative |
|---|---|---|---|
| D1 | Where the `ResearchBrief` comes from (5.11) | The **agent** builds it from the `TaskAssign`. Questions come from `inputs.research_questions`, or else from the objective. Scope comes from the objective and the project's `requirement-set` (the latest version, looked up by project). Constraints come from the step's acceptance criteria. The budget is `ResearchBudget` defaults, overridable by `inputs.budget`. The brief is stored as a `research-brief` artifact. `hooks.py` holds only the event and cleanup hooks (D14). | The Manager already passes the seeds. A hook that rewrites tasks would duplicate that and needs Manager writes. The spec's acceptance ("no file under `manager/` edited") still holds |
| D2 | Contract additions (**accepted 2026-10-14**) | **(M1, additive only)** `SubQuestion{id, question, text, queries[], success_criteria, coverage, status}`; `ResearchReport.sub_questions: list[SubQuestion] = []`; `Source` gains `provider`, `kind` (web / wiki / arxiv / local), `retrieved_at`, `content_sha256`, `page_artifact`; `ResearchBrief.follow_up_of: ArtifactRef \| None`. Snapshots updated. The per-round details live in a Member-5 artifact `research-trace`, not in the contract | Member 6 and the UI need the sub-question tree and the source hash. Everything else stays private to Member 5 |
| D3 | Modes (5.14) | `HMAP_RESEARCH_MODE` = `online` (live search + fetch; everything written to the cache) · `cached` (cache + corpus only, **never** network; misses are recorded as "not in cache") · `local` (local corpus only: the project's uploads + `samples/research/corpus/`). **Default `cached`.** Tests, CI and demos use `cached` | Privacy: queries come from private assignments and are not sent to a search engine unless someone opts in. Offline by default. Live research is one env var away |
| D4 | Search providers (5.2) | `SearchProvider` protocol `search(query, k) -> list[Hit]` with a **public** registry (`get_providers(names)`), for Member 6. Providers: DuckDuckGo (`ddgs` 9.16, MIT), Wikipedia (REST API over `httpx`), arXiv (Atom API over `httpx` + `lxml`), LocalCorpus (BM25 + embeddings over local files). Chosen by `HMAP_RESEARCH_PROVIDERS` (default `wikipedia,arxiv,ddg,local`). Search results are cached by (provider, query) like pages | No heavy SDKs. Every provider is replaceable. SearXNG is stretch |
| D5 | Fetcher (5.3) and safety | `httpx` with a clear User-Agent, robots.txt via `protego` 0.7 (BSD), 1 request/s per host, 10 s timeout, 2 retries with backoff, 5 MB cap, allowed types HTML / PDF / plain text. **SSRF guard:** http(s) only; resolve DNS and refuse loopback / private / link-local / reserved addresses, before and after redirects (the platform's own API, RabbitMQ and Postgres are on 127.0.0.1). The disk cache is `data/research_cache/` (git-ignored), keyed by sha256(URL) + fetch date, with headers. `content_sha256` is computed over the **cleaned** text that quotes are checked against | Fetched pages are untrusted; a page must never make us call localhost. Re-runs need no network (5.3 acceptance) |
| D6 | Cleaning (5.4) | HTML → `trafilatura` 2.3.1 (Apache-2.0): main text, title, date. Scripts, styles, hidden elements and zero-width characters are removed first (D12). PDF → Member 2's `load_pdf` (no OCR for web PDFs). Each page is stored as a `research-page` artifact (cleaned text + URL + title + date + sha256) | Reuses Member 2's loaders as the spec says. The page artifact is what Member 6 re-checks |
| D7 | Index (5.5) | Sentence-aligned chunks (~800 characters, 100 overlap). Embeddings via `ctx.llm.embed` in batches of 32, recorded in replay. Two backends behind one interface: **memory** (numpy cosine + `rank-bm25` 0.2.2) and **Postgres** (`research_chunks` table, `vector(768)` with an HNSW cosine index, `tsvector` + GIN for keywords; vectors sent as text, so no `pgvector` Python package). Hybrid ranking = reciprocal rank fusion of dense and keyword. Namespaced by project; rows deleted on `project.deleted`. Migration `005_sprint_5_research.py` (`CREATE EXTENSION IF NOT EXISTS vector`, `down_revision = "001b"`) | Same split as the rest of the platform (`HMAP_STORE=memory\|postgres`). Hybrid beats either alone on mixed queries (research §). Reusable by Member 7 |
| D8 | Source scoring (5.6) | `score = relevance × authority × recency × novelty`, each in 0..1 and stored in `Source.score_breakdown`. Relevance = hybrid rank. Authority from a small domain-class table (docs / standards / .edu / .gov / Wikipedia / arXiv high; known content farms low; unknown medium). Recency only when the question asks for current facts. Novelty = 1 − max cosine to already-selected chunks. Duplicates are removed by `content_sha256` and near-duplicate text (shingle Jaccard ≥ 0.9). Top-k per sub-question | Explainable (the UI shows the breakdown); cheap; no reranker model in the must-haves |
| D9 | Evidence extraction (5.7) | Two steps. **Triage** with `fast` (batched yes/no relevance per chunk; only the top chunks go on). **Extraction** with `reasoner` (≤ 4 chunks, ≤ 6 000 characters per call; schema: quote + sub-question + why). Each quote must be an exact substring of the page's cleaned text after normalising whitespace, quotes and dashes; a quote that is not found is **dropped** and counted (`fabricated_quotes_dropped`). Evidence keeps the char span | "0 fabricated quotes" is then guaranteed by code, not hoped for. Batching keeps a local run under ~15 calls |
| D10 | Coverage and stopping (5.8) | Coverage per sub-question = min(1, evidence weight / 2), where evidence from a second independent domain counts double. Stop rules built **with Member 4's `StopPolicy`**: `any_of(AllCovered(≥ 0.99), LowNovelty(< 10 % new evidence in a round), Budget(tokens / seconds from the brief), MaxIters(max_rounds))` under a hard cap. The reported `stop_reason` is one of `all_covered`, `low_novelty`, `budget`, `max_rounds`, `cancelled`, `no_sources`. A round only searches the sub-questions that are not covered yet, using new queries | No second loop framework; the termination proofs come from Member 4's property tests plus our own |
| D11 | Synthesis (5.9) | `reasoner` writes claims per sub-question, each citing evidence ids (schema). The **programmatic critic always runs**: uncited claims are dropped, cited ids must exist and belong to that sub-question, and claims a quote does not support at all (zero word overlap) are flagged. With `task.refine` the agent uses **Member 4's `RefinementMixin`** (programmatic citation critic + `LLMRubricCritic` "completeness vs the sub-questions" + `TargetedReviser`). `summary_markdown` is a short readable report with numbered citations | The spec's "integrate M4 Refiner". Refinement follows the project switch like everywhere else |
| D12 | Prompt-injection hygiene (5.12) | Page text is **data**: stripped of hidden and zero-width content, and wrapped in labelled, delimited blocks ("untrusted page text from <host>") in every prompt, with an instruction never to follow it. **Page text never becomes a query, a URL or a task**: only the planner's sub-questions drive searches, and links are not followed. Model output is schema-limited (quotes are verified; nothing else can act). Adversarial samples live in `samples/research/adversarial/` (instructions in text, hidden divs, "ignore previous…", fake citations). Test: the report and queries are identical with and without the injected lines | Member 6 builds the platform-wide injection suite (6.13) and reuses these samples |
| D13 | Artifacts | `research-report` (contract, first in the result), `research-brief`, `research-trace` (rounds: queries, hits, fetched, selected with scores, triage counts, dropped quotes, novelty, coverage, stop), `research-page` (one per cited page). All project-scoped and deleted with the project | The trace drives the UI and debugging; pages serve Member 6 |
| D14 | Events and hooks (5.10, 5.11) | Per-round `ctx.progress(percent, "round 2: 14 sources, 3/4 sub-questions covered", artifact_refs=[research-trace])`. A plug-in hook on `task.completed` for `research.run` emits `research.completed {task_id, report_ref, stop_reason, claims, evidence, coverage}` (Member 4 used the same pattern for `refine.*`). A hook on `project.deleted` removes the project's index rows | No Manager edits |
| D15 | Follow-up research (Member 6 6.8) | A task with `inputs.follow_up_of` (a previous `research-report` ref) and `research_questions` = the gaps. The agent loads the old evidence, researches only the gaps, and writes a **new** report that keeps the old evidence ids. Idempotency: same brief + mode + cache → the same report (LRU by brief digest, like `RefineAgent`) | Member 6's loop needs this; settling it now avoids a contract change in Sprint 6 |
| D16 | Offline demo corpus (5.14) | `samples/research/corpus/`: about 40–60 cleaned pages with metadata, **only permissively licensed sources** (Python docs — PSF; Wikipedia — CC BY-SA, attribution kept; IETF RFCs; pytest docs — MIT; arXiv metadata / abstracts — CC0). `samples/research/search_cache/` holds the recorded search results, so `cached` mode "searches" too. Plus `samples/llm_cache/research/` (model answers + embeddings) and `samples/research/LICENSES.md`. No news, blog or paywalled pages are committed | The demo runs with Wi-Fi off; nothing copyrighted is redistributed |
| D17 | Evaluation set (5.15) | `samples/research/gold/`: **10 questions** taken from the gold assignments (TCP chat: threads vs asyncio vs select, framing over TCP; lab manual: pytest parametrize, coverage; weather brief: API rate limits / caching; rubric: UML use-case diagrams; …). Each has 3–6 gold facts (keyword or regex sets + an acceptable source) and the relevant corpus pages. Metrics: **fact coverage**, **citation validity** (mechanical quote match must be 100 %; claim support labelled by hand on one run, ~40 claims), source quality (share from high-authority classes), rounds, tokens, time, stop reasons. Ablations: hybrid vs dense vs keyword retrieval (recall@k on 20 query → chunk pairs), and synthesis with vs without refinement | Gives Member 11 a benchmark and the mid-eval a number. Honest if small |
| D18 | UI (5.13) | Project tab **"Research"** (`frontend/src/features/research/`, after Plan). Per research step: the sub-question tree with coverage bars and status; the rounds timeline (queries, sources found, stop reason in plain words); a sources table with the score breakdown and provider; an **evidence viewer** (quote highlighted in the cleaned page, link to the original); claims with citation chips; the readable report. Simple vs Developer mode, light / dark, 375 px phone | Same conventions as Members 2–4 |
| D19 | Observability and privacy | Spans `research.round`, `search <provider>`, `fetch` (host, status, bytes, cached, ms) via `hmap.obs.span`. Metrics: `hmap_research_fetch_total{outcome,cached}`, `hmap_research_rounds_total{stop_reason}`, `hmap_research_quotes_dropped_total`. **No query text, no page text, no URL path** in telemetry (queries come from private documents); the host name only | Member 4's D17 rule; the Ops page explains research failures without extra work |
| D20 | **Mid-evaluation readiness — split with Member 6 (decided 2026-10-14: Member 6 also finishes before the mid-eval)** | **Member 5 delivers the research part of the demo:** `scripts/demo_sprint_5.sh` (upload the TCP chat PDF → requirements → plan approved → research in `cached` mode with the offline corpus → `research.completed` → stubs finish), research identical in `live` and `replay`, and the research agent surviving a kill mid-task (retry as a new execution, checked in a test). **Member 6 owns the readiness gate** (`mid-evaluation.md` §4) because their code is the last before the mid-eval: `make demo` / `make stop`, `scripts/demo_chaos.sh`, the three inputs in `samples/demo/`, the README real-vs-stub table, the clean-copy run and `check_sprint.sh 6` (Sprint 6 items 6.21–6.24). Member 9 later replaces `make demo` with the full packaging | The gate must be checked on the final pre-mid-eval code. The demo story will include verification (Member 6). Member 5 must not leave Member 6 a research step that only works online |
| D21 | Model roles and budgets (§6 local notes) | `reasoner`: planner + extraction + synthesis; `fast`: triage + coverage checks; `embed`: retrieval. The embedding model stays loaded beside the chat model (`OLLAMA_MAX_LOADED_MODELS=2`). Target per research step, local: ≤ 15 chat calls (planner 1, triage ≤ 4 batched, extraction ≤ 6, synthesis 1–2, refine ≤ 2). Default budget: 3 rounds, 20 sources, 180 s on the cloud. The local run is measured, not promised | A 9B model takes 20–60 s per call on the laptop (Sprint 4 measurement) |
| D22 | Recording | Model answers recorded **cloud first** with the team keys (`HMAP_LLM_RECORD_MISSING=research`). **Embeddings are always local**, so recording needs Ollama with `nomic-embed-text`. Search results and pages are recorded by running `online` once (they land in the cache, then the chosen pages are copied into `samples/research/`). Local-only runs are never recorded | Same rules as Sprints 2–4; tests and demos need no network, keys or Ollama |

---

## 2. Changes in Member 1's code (done by Member 5, listed in the commit message)

1. **Dependencies:** `ddgs==9.16.*`, `trafilatura==2.3.*`, `protego==0.7.*`, `rank-bm25==0.2.2` (`backend/pyproject.toml`,
   `uv.lock`).
2. **Contracts (D2, additive):** `SubQuestion`, `ResearchReport.sub_questions`, the new `Source` fields,
   `ResearchBrief.follow_up_of`; JSON-Schema export + snapshot update (`tests/contracts/snapshots/`).
3. **Config:** `research_mode`, `research_providers`, `research_cache_dir` (default `data/research_cache`),
   `research_max_fetch_mb`, `research_rate_per_host` in `core/config.py` (same pattern as `HMAP_PLAN_MAX_PARALLEL`);
   `.env.example` lines.
4. **Demo (D20):** `scripts/demo_sprint_5.{sh,py}` (`scripts/demo*` is shared with Member 9). `make demo`,
   `demo_chaos.sh`, `samples/demo/**` and the README table are Member 6's (readiness gate).
5. Nothing under `manager/`, `core/runtime/` or the bus. Migration `005_*` is already Member 5's path.

---

## 3. Phases

### Phase A — Research and design
`docs/members/5/research.md`, each topic with what it changes in the code:
- Search strategies: query decomposition (Self-Ask, least-to-most), query expansion (HyDE, multi-query),
  iterative / "deep research" loops (IRCoT, ReAct, STORM-style outline-first research).
- Retrieval: BM25 vs dense vs hybrid (RRF), chunking size / overlap, rerankers (stretch), recall@k.
- Source evaluation: authority, recency, relevance, redundancy / near-duplicates; CRAAP-style checks.
- Evidence extraction and attribution: quote-level grounding, attributable-to-identified-sources (AIS), ALCE
  citation metrics.
- Synthesis with citations; coverage tracking; stopping conditions (all answered, marginal novelty, budget).
- Failure modes: SEO spam, stale pages, prompt injection in web pages (indirect injection, Greshake et al.
  2023), SSRF; robots.txt and polite crawling; licences of cached content.

`docs/members/5/design.md`: modules, data flow, modes, the brief, artifacts, prompts with versions, budgets,
failure modes, the index schema (005), the UI. **Done when:** D1–D22 settled and every module and test named.

### Phase B — Gold set, corpus and harness (before the agent)
- `samples/research/gold/questions.jsonl` (10 questions, gold facts, relevant pages) and
  `samples/research/corpus/` + `LICENSES.md` (D16). Pages are fetched once in `online` mode, cleaned, reviewed and
  committed.
- Retrieval mini-benchmark: 20 query → relevant chunk pairs.
- Harness `backend/tests/research/eval/run_eval.py`: modes `cached` (default) / `online` / `local-only`
  (never recorded). It reports fact coverage, citation validity, source quality, rounds, tokens, time and stop
  reasons, and runs the ablations of D17. Results go to `samples/research/eval_results/`.

### Phase C — Search, fetch, clean, index (5.2–5.5, 5.12)
- `providers/` (`base.py`, `ddg.py`, `wikipedia.py`, `arxiv.py`, `local.py`, `cache.py`), public registry (D4).
- `fetch.py` (D5: robots, rate limit, retries, cache, SSRF guard, size / type limits), `clean.py` (D6),
  `sanitize.py` (D12).
- `index.py` (D7: chunking, embedding batches, memory + Postgres backends, hybrid RRF) +
  `backend/alembic/versions/005_sprint_5_research.py`.
- **Done when:** a cached re-run makes 0 network calls (asserted with a transport that fails on use); the SSRF
  tests refuse localhost / private ranges / redirects to them; recall@k measured.

### Phase D — Planner, selection, evidence, stop (5.1, 5.6–5.8)
- `planner.py` (5.1): sub-question tree (2–4 per question), 2–3 queries each, success criteria (`reasoner`, schema);
  every brief question has at least one sub-question (checked in code); a rule fallback without a model.
- `select.py` (D8), `evidence.py` (D9, quote-must-match), `stop.py` (D10 policies on Member 4's `StopPolicy`),
  `coverage` in `stop.py` or `tracker.py`.
- **Done when:** property tests show every loop ends within `max_rounds` with a recorded reason; no invented quote
  survives (a fake-model test that returns invented quotes ends with 0 in the report).

### Phase E — Synthesis, agent, hooks (5.9–5.11)
- `synthesize.py` (D11) with the always-on citation critic, plus `RefinementMixin` behind `task.refine`.
- `agent.py` (5.10): `ResearchAgent`, priority 100 for `research.run`; builds the brief (D1); runs rounds with
  progress and cancellation checks between steps; writes the artifacts (D13); idempotent (D15); follow-up mode.
- `hooks.py` + `plugin.py` (D14): `research.completed`, project cleanup.
- **Done when:** a plan's research step on the bus produces a valid `ResearchReport`, the event fires, and `verify`
  (still the stub) starts with the report in its `artifact_refs`.

### Phase F — API + UI (5.13)
- `router.py` (`/api/research`, owner only, 404 otherwise): reports of a project, one report with its trace,
  a page artifact with highlight spans, `GET /providers` (names + mode), `POST /runs/{project_id}` (ad-hoc research
  on a question, for the demo and for testing).
- `frontend/src/features/research/` (D18), with tests (logic + DOM).
- **Done when:** lint / typecheck / tests / build pass; checked by hand at desktop and 375 px, light and dark,
  with screenshots.

### Phase G — Corpus recording, evaluation, tests, demo (5.14–5.16, D20)
- Record (D22): model answers cloud first, embeddings locally, search results + pages in `online` once; then
  everything replays offline.
- `docs/members/5/eval.md`: the D17 tables plus one **local-only** run (not recorded), honest about weak spots.
- Tests `backend/tests/research/` (5.16): planner (coverage of every question, fallback), each provider against
  recorded responses (`httpx.MockTransport`), fetcher (robots, rate limit, retries, cache hit = 0 network, SSRF,
  size / type limits), cleaning, sanitising + the adversarial pages, index (both backends, hybrid order, project
  isolation, cleanup), selection (score breakdown, dedup), quote-must-match, stop (property tests), synthesis
  critic, agent (idempotency, cancellation mid-round, follow-up), API (ownership 404, CSRF), **integration over
  RabbitMQ + Postgres in replay / cached mode** (plan → research → `research.completed` → verify stub).
- Demo: `scripts/demo_sprint_5.sh` (the research part of the mid-eval storyline, offline, D20); a test that kills
  the research agent mid-round and checks the retry finishes as a new execution.

### Phase H — Hand-over for the mid-evaluation (D20)
- In `HANDOFF.md`: how to run the research step offline in the full storyline, which questions the corpus covers,
  and what Member 6 must keep working for the readiness gate.

---

## 4. Definition of Done (spec §8 + doc 03 §3 + project rules)
- [x] `cached` run reproduces the demo report with Wi-Fi off; an `online` run works with the network
- [x] 0 fabricated quotes on the eval set (checked by code); citation validity reported
- [x] An injected / adversarial page does not change queries, plan or report
- [x] Every research loop terminates with a recorded stop reason (property tests)
- [x] `research.completed` emitted; `ResearchReport` + page artifacts usable by Member 6 (L1 re-check by sha256)
- [x] Research tab works at desktop and phone width, light and dark
- [x] Recorded answers / pages / embeddings in `samples/`; tests and demo need no network, keys or Ollama
- [x] No query text, page text or key in any span, metric or log
- [x] research / design / eval / testing / README docs; `HANDOFF.md` Sprint 5 section for Member 6
- [x] `scripts/check_sprint.sh 5` PASS; the research step runs offline in the full storyline (for Member 6's readiness gate)

## 5. Interface handed on (spec §7)
```text
Artifact research-report (ResearchReport): claims[{id, text, evidence_ids[]}], evidence[{id, url, quote, content_sha256,
  retrieved_at, sub_question, page_artifact}], sources[{url, title, provider, kind, score, score_breakdown, content_sha256,
  page_artifact}], sub_questions[], coverage{}, stop_reason, summary_markdown
Artifacts research-page (cleaned text the quotes come from), research-trace, research-brief
Event research.completed {task_id, report_ref, stop_reason, claims, evidence, coverage}
Guarantee: every evidence quote is a verbatim substring of its research-page text, whose sha256 = content_sha256
Follow-up: create research.run with inputs {follow_up_of: <report ref>, research_questions: [gaps]}
Python: hmap.agents.research.providers.get_providers(...), .index.HybridIndex, .fetch.Fetcher (Members 6, 7)
```

## 6. Order and effort
| Order | Phase | Effort |
|---|---|---|
| 1 | Settle D1–D22 (all accepted 2026-10-14) | small |
| 2 | A research + design | medium |
| 3 | B gold set, corpus, harness | medium |
| 4 | C providers, fetcher, cleaning, index | large |
| 5 | D planner, selection, evidence, stop | large |
| 6 | E synthesis, agent, hooks | medium |
| 7 | F API + UI | medium |
| 8 | G recording, eval, tests, demos | medium–large |
| 9 | H hand-over for Member 6's readiness gate | small |

## 7. Risks
| Risk | Mitigation |
|---|---|
| Search engines block or rate-limit (DuckDuckGo especially) | Several providers; cache everything; `cached` default; Wikipedia / arXiv APIs are stable |
| Invented quotes | Quote-must-match in code; dropped and counted; tested with a lying fake model |
| Prompt injection from pages | D12; page text never drives actions; adversarial samples and tests |
| SSRF / fetching local services | D5 guard tested; redirects re-checked |
| Slow on the laptop (9B model, 20–60 s per call) | Batching, triage before extraction, ≤ 15 calls, cloud first with keys, replay for the demo |
| Licence of cached pages | Only permissive sources committed; attribution file |
| Live and replay diverge in the mid-eval | `cached` mode + replay; the demo checks both |
| Research works only online at the gate | D20: Member 5's demo runs in `cached` mode; Member 6 runs the gate |
| Privacy of queries | `cached` by default; no query text in telemetry |

---

## 8. Verification — is anything missing?
Every requirement in the spec (and every downstream need) mapped to where this plan covers it.

| Spec / need | Covered by | Built |
|---|---|---|
| §1 plan research, search, retrieve, select, quote evidence, cited report, decide when to stop; local LLMs; offline mode | C, D, E; D3, D21 | ✓ |
| §2 uses gateway roles, pgvector, artifacts, M3 seeds, M4 Refiner, UI shell | §0; D1, D7, D11, D18 | ✓ |
| §3 research topics incl. SEO spam, stale pages, prompt injection | A (`research.md`) | ✓ |
| §4 pipeline Planner → Searcher → Fetcher → Indexer → Selector → Extractor → Tracker → Stopper → Synthesizer → report | C, D, E | ✓ |
| §4 untrusted-content rule | D12, D5 | ✓ |
| 5.1 planner covers all brief questions | D (`planner.py`) + test | ✓ |
| 5.2 provider interface + DDG, Wikipedia, arXiv, LocalCorpus; swap by config; offline | D4, C | ✓ |
| 5.3 fetcher: robots, rate limit, timeouts, retries, disk cache by URL + date, content hash; cached = 0 network | D5, C + test | ✓ |
| 5.4 cleaning (trafilatura), PDFs via M2 loaders | D6 | ✓ |
| 5.5 chunk + embed + pgvector (005) + hybrid; recall@k | D7, B benchmark | ✓ |
| 5.6 scoring / selection / dedup with stored breakdown | D8 | ✓ |
| 5.7 quote-must-match, 0 fabricated | D9 + tests + eval | ✓ |
| 5.8 coverage, stopping, budgets; stop reason | D10 (on M4's `StopPolicy`) + property tests | ✓ |
| 5.9 synthesis with citations, M4 Refiner, citation critic | D11 | ✓ |
| 5.10 `ResearchAgent` on the bus, progress per round, cancellation, idempotent | E, D14, D15 | ✓ |
| 5.11 research tasks get a brief; report stored; `research.completed`; no Manager edit | D1, D13, D14 | ✓ |
| 5.12 injection hygiene; adversarial test | D12 | ✓ |
| 5.13 API + UI: tree, sources with scores, evidence viewer, coverage, stop reason | F, D18 | ✓ |
| 5.14 offline corpus + `HMAP_RESEARCH_MODE` | D3, D16, D22 | ✓ |
| 5.15 eval: 8–10 questions, fact coverage, citation validity, source quality, rounds, tokens | D17, B, G | ✓ |
| 5.16 tests incl. integration over the bus in replay | G | ✓ |
| Stretch: SearXNG, reranker, per-domain trust lists, parallel sub-question research, query refinement from gaps | **not planned as must**. SearXNG = one more `SearchProvider`; trust list = D8's table made editable; query refinement from gaps is partly in D10 (new queries for uncovered sub-questions; never from page text) | not built (as planned): SearXNG, reranker, trust lists, parallel sub-questions |
| §6 local notes: roles, per-chunk extraction, co-resident embed model, batching | D9, D21 | ✓ |
| §7 interface to M6 (report, event, verbatim + sha256 guarantee) | §5, D2, D13, D14 | ✓ |
| §8 DoD: cached / online, 0 fabricated, adversarial page, check_sprint 5 | §4 | ✓ |
| §9 risks | §7 | ✓ |
| Mid-eval storyline (research step live, failure injection on the research agent) | D20 (research part + kill test), Phase G | ✓ |
| Mid-eval readiness gate (`make demo`, live = replay, `demo_chaos.sh` 3×, check_sprint, real-vs-stub table) | **Member 6** (D20); Member 5 hands over a research step that passes it offline | ✓ |
| Mid-eval evidence: `docs/members/5/eval.md` (cited report, coverage, stop reason, offline replay) | G | ✓ |
| Member 6: page artifacts + sha256, public providers, follow-up research, poisoned pages | D5, D4, D15, D12 | ✓ |
| Member 7: reusable embeddings / index helpers | D7 (`HybridIndex` public) | ✓ |
| Member 10: report as review evidence; M5 → M6 contract pair | §5 (contract unchanged in shape, additive only) | ✓ |
| Member 11: fact-coverage gold set + evaluator; recorded traces | D17, D22 | ✓ |
| Member 4 hand-over: Refiner via mixin, `StopPolicy` reuse, spans with `hmap.obs`, D17 privacy | D10, D11, D19 | ✓ |
| Project rules: no git by Claude, keys only in `.env`, offline tests, stop background processes, M2–M4 folders untouched | §2, D22 | ✓ |

Gaps found while checking (now in the plan):
- The mid-eval gate asks for `make demo` and `scripts/demo_chaos.sh`; nobody owned them before Sprint 9 → D20:
  Member 6 (last before the mid-eval).
- `samples/demo/` holds only a text file, not the three mid-eval inputs → D20 (Member 6).
- The pgvector extension is not created by any migration → D7 (`005`).
- `ResearchReport` has no sub-question tree and `Source` has no hash or provider, which the UI and Member 6 need →
  D2 (additive).
- Member 6's follow-up loop (6.8) needs a follow-up input on research tasks → D15.
- Member 6 reuses Member 5's providers "via public interface" → D4 makes the registry public.
- Fetching arbitrary URLs on a laptop that runs local services is an SSRF risk the spec does not name → D5.
- Queries come from private documents → `cached` default and no query text in telemetry (D3, D19).
- Embeddings cannot be recorded on the cloud (embed is always local) → D22.

## 9. Overlap check with other members

| Area | Member 5 does | Not Member 5 (owner) |
|---|---|---|
| Prompt injection | `sanitize.py`, untrusted-text wrapping, adversarial samples + tests for **research inputs** | the platform-wide injection regression suite (Member 6, 6.13); `core/policy.py` security layer (Member 6, 6.20) |
| Search providers | builds them, public registry | independent verification queries and the verifier's own retrieval (Member 6, 6.4: reuses the providers, writes its own query generator) |
| Claim checking | mechanical quote match + citation critic **inside its own report** | entailment, cross-source conflicts, verdicts (Member 6) |
| Follow-up research | accepts `follow_up_of` + gap questions | deciding when to ask for it and creating the task (Member 6, 6.8) |
| Refinement | uses Member 4's library (mixin, stop policies) | the library itself (Member 4; not edited) |
| Document parsing | calls Member 2's loaders for PDFs and project uploads | the loaders (Member 2; not edited) |
| Research questions | reads them from task inputs | generating them in the plan (Member 3; not edited) |
| Index / embeddings | a generic hybrid index for text chunks | repository / code retrieval (Member 7, may reuse the index) |
| Observability | spans + metrics for research | the telemetry stack, Ops page, alerts (Member 4) |
| Demo | `demo_sprint_5.sh` (research part, offline) | mid-eval readiness gate: `make demo`, `demo_chaos.sh`, `samples/demo/`, real-vs-stub table (Member 6); full packaging (Member 9); golden scenarios (Member 10) |
| Model routing | uses roles only | routing, model tiers, benchmarks (Member 11) |
| Review | — | judging the report against requirements (Member 10) |

No overlap remains. D20 splits the mid-eval preparation: Member 5 the research part, Member 6 the gate.
