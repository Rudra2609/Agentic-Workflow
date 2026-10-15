# Evaluation — does the research agent find and cite the right things? (Member 5)

Numbers from `samples/research/eval_results/{replay,rules,local}.json` (2026-10-14), written by:

```bash
cd backend
uv run python -m tests.research.eval.run_eval --ablation --name replay   # offline: cached corpus + recorded answers
uv run python -m tests.research.eval.run_eval --rules                    # no model at all
uv run python -m tests.research.eval.run_eval --mode live --local-only --only ... --name local   # local, not recorded
```

**Set-up.**
- **Gold set:** 10 questions (`samples/research/gold/questions.jsonl`). Eight are the exact research questions
  Member 3's planner wrote for the gold assignments, one is reworded, and one comes from the long lab. Each has 3–4
  gold facts (patterns), 31 facts in all.
- **Offline:** every run is `cached`: only the committed corpus (105 freely licensed pages: 76 Wikipedia, 19 arXiv
  abstracts, 8 Python docs, 1 FastAPI, 1 coverage.py) and the recorded search results. The local cache is replaced
  by an empty folder, so the numbers reproduce on any laptop.
- **Models:** the recorded model answers are cloud-first (Gemini `gemini-3.6-flash` / Groq `gpt-oss` for
  reasoner / fast); embeddings are local `nomic-embed-text`.
- **Determinism:** a pure replay reproduced the recording run exactly (all four conditions, the retrieval test and
  the demo brief), with 0 missing recordings and **0 network calls**.

## 1. Headline (hybrid retrieval, the shipped setting)

| Metric | Value |
|---|---|
| **Fact coverage** (gold facts found in the claims or cited quotes) | **0.65** (20 of 31 facts) |
| **Citation validity** (quote verbatim in its page, page hash matches) | **64 / 64 = 100 %** |
| Invented quotes in a report | **0** — the check dropped 2 of 79 proposed quotes that were not on the page |
| Findings (claims) per question | 3.5 (0–7) |
| Sources per question | 2.4; mean source quality (authority) 0.89 |
| Rounds | 2.6 per question; stops: `low_novelty` 7, `all_covered` 2, `no_sources` 1 |
| Cost | 8 248 tokens and 6.4 model calls per question (planner + extraction batches + synthesis) |
| Time (live, cloud + local embeddings, recording run) | median 14.5 s per question (4.6–27 s); replay < 1 s |
| Demo brief (Member 3's 4 TCP-chat questions) | 8 findings, 15 / 15 quotes valid, 6 sources, 8 sub-questions (2 fully answered), 3 rounds, 11 calls, 25.6 k tokens |

Per question (facts found, findings, sources, stop):

| Question | Facts | Findings | Sources | Stop | Missed |
|---|---|---|---|---|---|
| q01 threads / selectors / asyncio | 2/4 | 3 | 3 | all_covered | event loop, selectors |
| q02 non-blocking broadcast | 1/3 | 2 | 5 | low_novelty | drain / buffer, streams |
| q03 measuring latency | 0/3 | 3 | 1 | low_novelty | perf_counter, monotonic, round trip |
| q04 pytest + coverage command | 0/3 | 0 | 0 | no_sources | all (no permissive page in the corpus) |
| q05 Django vs FastAPI | 2/3 | 5 | 3 | low_novelty | type hints / Pydantic |
| q06 JWT vs bearer | 3/3 | 7 | 3 | all_covered | — |
| q07 useState vs useReducer | 3/3 | 3 | 1 | low_novelty | — |
| q08 localStorage serialisation | 3/3 | 4 | 2 | low_novelty | — |
| q09 argparse | 3/3 | 5 | 4 | low_novelty | — |
| q10 strategy pattern | 3/3 | 3 | 2 | low_novelty | — |

**Why the misses** (looked at by hand):
- **q04:** every good page for "pytest + coverage in one command" (pytest-cov / coverage.py docs, blogs) was either
  not found by the online search or not redistributable. The corpus has no page with `coverage run` or `--cov`.
  That is a corpus limit, not the loop.
- **q03:** the planner's sub-questions turned towards Unix time and generic timestamps, and the corpus has no page
  about `time.perf_counter`.
- **q01, q02:** the pages found (threading docs, the sockets HOWTO) answer the question but not with the gold
  set's words (`event loop`, `drain`).

The facts are patterns over the claims and quotes, so a correct paraphrase can still miss. Read 0.65 as a lower
bound.

## 2. Ablations

### Retrieval: hybrid vs dense vs keyword (same everything else)

| Retrieval | Fact coverage | Findings / q | Sources / q | Citation validity | Stops (covered / low novelty / none) |
|---|---|---|---|---|---|
| **hybrid (RRF)** | **0.650** | 3.5 | 2.4 | 64 / 64 | 2 / 7 / 1 |
| dense only | 0.617 | 4.5 | 2.5 | 80 / 80 | 2 / 7 / 1 |
| keyword only (BM25) | 0.583 | 3.9 | 3.0 | 65 / 65 | 3 / 6 / 1 |

**Fact recall@k** over the whole corpus (is a passage stating each gold fact among the top k retrieved for the
question? 31 facts):

| Retrieval | @3 | @6 | @10 |
|---|---|---|---|
| **hybrid** | 0.45 | **0.61** | **0.71** |
| dense | **0.48** | 0.58 | 0.65 |
| keyword | 0.45 | 0.55 | 0.68 |

Hybrid is best at 6–10 passages, which is what the loop uses (8 candidates per sub-question). Dense alone is best
at 3. The differences are a few facts out of 31; with 10 questions they are indicative, not significant.

### Synthesis with vs without Member 4's refinement (`task.refine`)

| Condition | Fact coverage | Findings / q | Refinement result |
|---|---|---|---|
| without | 0.650 | 3.5 | — |
| with | 0.650 | 3.4 | improved 2 of 9 reports (q02 0.77 → 0.80, q06 0.85 → 1.00, dropping one weakly supported claim); 6 plateaued, 1 already at 1.0; +11.6 k tokens per report |

**Refinement makes no measurable difference to fact coverage here.** It checks the claims against the quotes
already found; it cannot add facts the search did not find. Its only visible effect is removing a weakly supported
claim now and then, at about 2.4× the tokens. It stays behind the project switch (off by default).

### No model at all (rules)

| | Fact coverage | Findings / q | Model calls |
|---|---|---|---|
| rules only (planner = the question, keyword search, best-overlap sentence as the quote) | 0.283 | 3.7 | 0 |
| **with the model** | **0.650** | 3.5 | 6.4 |

With no keys and no Ollama the agent still works offline and cites real quotes, but finds less than half as much.

## 3. What went wrong while building, and was fixed (each measured)

| Problem | Fix | Effect |
|---|---|---|
| Embeddings were never recorded (record-missing covered chat only): retrieval was silently keyword-only | the gateway records missing embeddings too; the index records `keyword_only` and why | dense / hybrid actually ran |
| Triage threw away most passages and extraction returned 0–1 quotes per batch | triage only above 8 passages; extraction asks for 1–3 sentences per useful passage | fact coverage on 3 questions 0.11 → 0.69; on 10 questions 0.33 → 0.65 |
| One page could "fully answer" a sub-question | coverage needs two sites (one site ≤ 75 %); same-page penalty in selection | more sources per answer (1.8 → 2.4) |
| Overlapping quotes counted twice | overlap check | cleaner evidence lists |
| Wall-clock budget made replays take a different path | token budget by default | replay = recording, exactly |
| trafilatura's de-duplication is process-global | turned off | the same page always cleans to the same text and hash |
| Recordings were 76 MB | float16 base64 embeddings, at most 40 chunks per page | 11 MB |

## 4. Local model only (not recorded)

`run_eval --mode live --local-only --only q01_tcp_concurrency q06_token_scheme q07_react_state --name local`: the
whole loop on `qwen3.5:9b` + `nomic-embed-text` through Ollama, on the M3 / 16 GB laptop. Same offline corpus. Live,
never recorded; 0 cloud calls (checked in the log).

| Question | Cloud model (above) | Local 9B | Local time |
|---|---|---|---|
| q01 threads / selectors / asyncio | 2/4 facts, 3 findings | **0/4, no findings** | 96 s |
| q06 JWT vs bearer | 3/3, 7 findings | **0/3, no findings** | 251 s |
| q07 useState vs useReducer | 3/3, 3 findings | **0/3, no findings** | 176 s |

**The local model found nothing.** It planned one sub-question per question. In every extraction call (17–112 s
each) it returned **no quote at all** for passages that the cloud model quoted, so every run ended `no_sources`. This
is not a crash: the loop, the checks and the honest empty report all worked. But it means research on a laptop
without keys currently gives **less than the rule fallback** (0.28 fact coverage with no model). Two ways out, both
for later:
- if the model returns no quote for a batch, take the rule quote (the sentence with the most question words,
  verbatim by construction);
- or use a larger local model for `reasoner` during research (Member 11's routing).

Neither was done in this sprint: changing the extraction path changes every recorded cloud run, which would have to
be recorded again.

## 5. Safety checks (from the tests)
- **0 invented quotes** in any report: a lying model's quote is dropped and counted (unit test). In the evaluation,
  9 of 329 proposed quotes over all conditions were dropped, none reached a report.
- **An injected page changes nothing:** identical queries, claims and quotes with and without injected lines. 4
  adversarial pages are cleaned of every instruction.
- **SSRF:** 12 local / private URL forms, a private DNS answer and a redirect to 127.0.0.1 are all refused before
  any request.
- **Offline:** `cached` mode makes 0 network calls (asserted in a test, and `network_calls = 0` in every evaluation
  run).

## 6. Honest weak spots
- **10 questions, 31 facts**, written by us. The fact patterns are strict, so the numbers are indicative.
- **The offline corpus is small and skewed** to Wikipedia (76 of 105 pages): only what one online harvest found and
  what may be redistributed. Questions whose best answers live in blogs or third-party docs (q04) cannot be
  answered offline.
- **The planner sometimes drifts:** q03's sub-questions went to Unix time and other languages; the brief had no
  project context in the evaluation. In the platform the brief carries the requirements as scope.
- **Support is checked only loosely** (the citation check needs shared words). One demo finding cites a marginal
  page (inter-process communication for "broadcast"). Real entailment checking is Member 6's verification.
- **DuckDuckGo** often rate-limited during the harvest; Wikipedia and arXiv carried most of the searching.
- **The local 9B model returns no quotes** (§4): offline without keys, research falls back to nothing better than the
  rules unless the extraction path gets a rule fallback (recommended for Member 11).
- **Stopping:** `low_novelty` ends 7 of 10 runs, often with a sub-question still open. More rounds rarely help
  offline, because the corpus has nothing more to give.
