# Research — what we read and what it changed in the code (Member 5)

Each topic ends with **→ code**: where it shows up in what we built.

## 1. Search strategies: decomposition, expansion, iterative research
- **Query decomposition:** Self-Ask (Press et al., 2023) and least-to-most prompting (Zhou et al., 2023) answer a
  hard question through simpler sub-questions.
- **Iterative research:** IRCoT (Trivedi et al., 2023) interleaves retrieval with reasoning steps. STORM (Shao et
  al., 2024) plans an outline from several perspectives first, then researches each part. "Deep research" agents run
  search → read → decide loops.
- **Query expansion:** HyDE (Gao et al., 2023) searches with a hypothetical answer. Multi-query rewriting searches
  several phrasings.

**→ code:**
- `planner.py` splits each question into 1–4 sub-questions with 2–3 plain queries each (several phrasings = cheap
  expansion) and a success criterion.
- `pipeline.py` runs rounds: each round searches only the still-open sub-questions, with their next query.
- We did not use HyDE. A hypothetical answer written by a 9B model would be a guess, and searching with a guess
  pulls in pages that confirm it.

## 2. Retrieval: keyword vs dense vs hybrid, chunking, reranking
- **Each ranking misses different things:** BM25 is strong on rare exact terms (function names, RFC numbers); dense
  embeddings are strong on paraphrase.
- **Fusing them helps:** Reciprocal Rank Fusion (Cormack et al., 2009) combines rankings without tuning weights and
  beats either alone on mixed queries (BEIR results, Thakur et al., 2021).
- **Chunking:** a few hundred tokens with overlap is the usual trade-off between precision and context.
- **Reranking:** cross-encoder rerankers (stretch) add a second model.

**→ code:**
- `index.py`: RRF (k = 60) over cosine on `nomic-embed-text` vectors plus BM25Plus in memory, or `ts_rank_cd` in
  Postgres.
- Sentence-aligned ~800-character chunks with 120 characters of overlap.
- The eval measures fact recall@k for hybrid vs dense vs keyword. BM25**Plus**, not Okapi: Okapi gives zero weight
  to terms in half the documents, and so returned nothing on a tiny corpus (found by the smoke test).

## 3. Source evaluation
Credibility checklists (CRAAP: currency, relevance, authority, accuracy, purpose), and redundancy / near-duplicate
detection (shingling, MinHash; Broder 1997).

**→ code:**
- `select.py`: an explainable `relevance × authority × recency × novelty` score with a small table of domain
  classes.
- Recency counts only when the question asks for current facts.
- Novelty = 1 − cosine to passages already chosen. A same-page penalty pushes towards two independent sources.
- Shingle Jaccard ≥ 0.9 drops near-duplicates. The breakdown is stored in `Source.score_breakdown` and shown in the
  UI.

## 4. Evidence extraction and attribution
- **Attribution:** AIS, "Attributable to Identified Sources" (Rashkin et al., 2023), asks whether a statement is
  supported by its cited source. ALCE (Gao et al., 2023) measures citation recall and precision.
- **Fabrication:** models fabricate quotes and citations (Liu et al., 2023, "Evaluating verifiability in generative
  search engines": about half of generated sentences were not fully supported).

**→ code:**
- **Quote-must-match** (`quotes.py`): a quote counts only if it is a verbatim substring of the cleaned page; only
  typography is normalised. Invented quotes are dropped and counted.
- Every claim must cite evidence ids, and the citation check drops claims that cite nothing or share no words with
  their quotes.
- Member 6 checks support (entailment) independently.

## 5. Synthesis with citations, coverage, stopping
- Synthesis grounded only in the collected evidence (retrieval-augmented generation, Lewis et al., 2020).
- Coverage tracking per sub-question, as in STORM's outline.
- Stopping rules: all answered, marginal novelty (diminishing returns), budget, maximum rounds.

**→ code:**
- `synthesize.py` asks for claims per sub-question from the evidence only.
- `stop.py`: coverage needs two independent sites (a single site counts 75 %). `AllCovered`, `LowNovelty` (< 10 %
  new evidence in a round, or no queries left), a token budget and `max_rounds`, built on Member 4's `StopPolicy`
  (property-tested).

## 6. Failure modes of web research
- **SEO spam and content farms:** low authority in `select.py`.
- **Stale pages:** the recency factor, when it matters.
- **Indirect prompt injection** (Greshake et al., 2023): instructions hidden in a page the agent reads. → **code:**
  hidden HTML removed, invisible characters removed, AI-directed lines removed and counted, page text wrapped as
  untrusted in every prompt, page text never becomes a query or a URL. Adversarial pages are tested.
- **SSRF:** a fetched link pointing at `127.0.0.1`, the cloud metadata IP or the LAN. → **code:** the guard in
  `fetch.py` (resolve, refuse non-public addresses, re-check redirects).
- **Polite crawling:** robots.txt (RFC 9309) via `protego`, one request per second per host, a clear User-Agent,
  everything cached.
- **Licences of cached content:** only permissively licensed pages are committed (`samples/research/LICENSES.md`).

## 7. Local models
- A 9B model takes 20–60 s per call on the laptop (Sprint 4 measurement), and embeddings must stay loaded beside the
  chat model.

**→ code:**
- Triage before extraction, at most 4 chunks per extraction call, embeddings in batches of 32.
- `OLLAMA_MAX_LOADED_MODELS=2`, cloud first when keys exist.
- The local-only run is measured in [eval](eval.md) (never recorded).
