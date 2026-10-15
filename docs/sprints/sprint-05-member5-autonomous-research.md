# Sprint 5 — Member 5: Autonomous AI Research

**Owner:** Member 5 · **Needs:** Sprint 4 accepted · **Unblocks:** Sprint 6 (verification) and the **mid-eval demo** (after Sprint 6; Member 6 owns the readiness gate, Member 5 hands over a research step that runs offline)
**Replaces stub:** `research.run` → `agents/research/`

## 1. Goal
An agent that, given a `ResearchBrief` (questions from a plan task), **plans research, searches, retrieves, selects sources, extracts quote-level evidence, synthesizes a cited report, and decides when to stop** — running on local LLMs, with an **offline/cached mode** so the demo never depends on the internet.

## 2. Provided by earlier sprints
Bus/agent runtime, gateway (`reasoner`, `fast`, `embed`), Postgres (+pgvector), artifact store, M3 tasks carrying research seeds, **M4 `Refiner`** (use for synthesis), UI shell.

## 3. Research deliverable
Search strategies (query decomposition, query expansion, iterative/“deep research” loops), retrieval (BM25 vs dense vs hybrid, chunking, reranking), source evaluation (authority, recency, relevance, redundancy), evidence extraction & attribution, synthesis with citations, coverage tracking, **stopping conditions** (all sub-questions answered, marginal-novelty threshold, budget), failure modes (SEO spam, stale pages, prompt injection in web pages).

## 4. Design

```text
ResearchBrief{questions[], scope, constraints, budget}
 → [Planner]  sub-questions tree, search queries per sub-question, success criteria      (LLM schema)
 → loop until Stop:
     [Searcher]  providers: DuckDuckGo(ddgs) | SearXNG(optional) | arXiv | Wikipedia | LOCAL-CORPUS  (pluggable)
     [Fetcher]   httpx + robots.txt + rate-limit + cache → trafilatura text → content_sha256
     [Indexer]   chunk → embed(nomic) → pgvector (per-project namespace)
     [Selector]  score = relevance(embedding+BM25) × authority × recency × novelty; dedup; top-k
     [Extractor] LLM → evidence{quote, url, supports sub-question}; quote must string-match fetched text
     [Tracker]   coverage per sub-question; novelty of last round
     [Stopper]   all covered ∨ novelty<ε ∨ budget ∨ max_rounds
 → [Synthesizer] claims each tied to evidence_ids  → M4 Refiner (programmatic critic: every claim cited, every quote verified; LLM critic: completeness)
 → ResearchReport artifact
```
**Untrusted-content rule:** fetched pages are data; strip instructions, never allow them to alter the plan (prompt-injection defence; ties to M1 §30).

## 5. Work items

### MUST
| # | Item | Files (`agents/research/`) | Acceptance |
|---|---|---|---|
| 5.1 | Research planner (sub-questions, queries, success criteria) | `planner.py` | covers all brief questions |
| 5.2 | Search provider interface + DDG, Wikipedia, arXiv, **LocalCorpus** (folder of docs) providers | `providers/` | swap by config; offline works |
| 5.3 | Fetcher: robots.txt, rate limit, timeouts, retries, caching on disk keyed by URL+date, content hash | `fetch.py` | cached re-run = 0 network |
| 5.4 | Extraction/cleaning (trafilatura/readability), PDF sources via M2 loaders (reuse) | `clean.py` | |
| 5.5 | Indexing: chunk + embeddings + pgvector (migration `005_*`) + hybrid retrieval | `index.py` | recall@k on mini benchmark |
| 5.6 | Source scoring/selection & dedup | `select.py` | explainable score breakdown stored |
| 5.7 | Evidence extraction with **quote-must-match** verification | `evidence.py` | 0 fabricated quotes (checked mechanically) |
| 5.8 | Coverage tracker + stopping conditions + budgets | `stop.py` | terminates; stop_reason recorded |
| 5.9 | Synthesis with citations; **integrate M4 Refiner** (citation-completeness programmatic critic) | `synthesize.py` | every claim has ≥1 evidence id |
| 5.10 | `ResearchAgent` capability `research.run`; progress events per round; cancellation | `agent.py` | on bus; idempotent |
| 5.11 | Manager hook (plug-in `manager_hooks`): research tasks from plan get `ResearchBrief`; report stored; event `research.completed` for M6 | `hooks.py`, registered in `plugin.py` | no file under `manager/` edited |
| 5.12 | Prompt-injection hygiene for fetched content (strip/neutralize, label provenance) | `sanitize.py` | adversarial page test passes |
| 5.13 | API + UI: research tree (sub-questions), source list w/ scores, evidence viewer (quote ↔ source), coverage bars, stop reason | `agents/research/router.py` (auto-mounted), `frontend/src/features/research/` (auto-registered) | |
| 5.14 | **Offline demo corpus** for the mid-eval questions (cached pages + embeddings) + `HMAP_RESEARCH_MODE=online|cached|local` | `samples/research/` | demo runs with Wi-Fi off |
| 5.15 | Eval: 8–10 research questions with gold facts → fact-coverage %, citation validity %, source-quality, #rounds, tokens | `tests/research/eval/` | `eval.md` |
| 5.16 | Tests: planner, provider mocks, quote-match, stop logic, integration over bus in `replay` mode | `tests/research/` | green |

### STRETCH
SearXNG self-hosted provider; reranker model; per-domain trust lists; multi-agent parallel sub-question research; query-refinement from gaps.

## 6. Local-LLM notes
`reasoner` for planning/synthesis, `fast` for relevance triage, `embed` for retrieval. Evidence extraction is **per chunk** (small context). Embedding model + chat model stay co-resident (`OLLAMA_MAX_LOADED_MODELS=2`, doc 02 §2.1), so no swap per embedding call; still batch embeddings together for throughput.

## 7. Interface handed to Member 6
```text
Artifact: ResearchReport.json
  claims[{id,text,evidence_ids[]}], evidence[{id,url,quote,content_sha256,retrieved_at,sub_question}], sources[], coverage, stop_reason
Event: research.completed {task_id, report_ref}
Guarantee: every evidence quote is verbatim from content with matching sha256 (cached page artifacts stored) — M6 can re-check independently.
```

## 8. Definition of Done (additions)
- [ ] Offline (`cached`) run reproduces the demo report; `online` run works with network
- [ ] 0 fabricated quotes on eval set; citation validity reported
- [ ] Adversarial/injected web page does not change behaviour
- [ ] **Sprint 1–5 regression green: `scripts/check_sprint.sh 5`**; the research step runs offline in the full storyline for the [mid-evaluation](mid-evaluation.md) (gate run by Member 6)

## 9. Risks
Search blocked/flaky → cached/local providers; low-quality sources → scoring + dedup; runaway loops → budget; slow on 16 GB → small chunks, cache everything.
