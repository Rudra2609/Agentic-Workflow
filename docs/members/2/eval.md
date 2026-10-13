# Evaluation — Member 2: document intelligence

## 1. Gold set
`samples/doc_intel/gold/`: 10 cases, 12 files, written for this project and labelled sentence by sentence
(`content.py`), rendered by `build_gold.py` (deterministic). The cases: a native PDF assignment, a DOCX lab manual,
a rubric with merged cells, a skewed and speckled scan, a phone photo, a DOCX brief with a deliverables table, a
two-column PDF with header, footer and footnote, a three-part upload in folders (PDF + DOCX + Markdown), a typed
request, and a two-page lab sheet whose requirements are list items under lead-in sentences ("At minimum, your
program needs to support:", added after a real IT 314 lab sheet showed that case).
In total: 63 requirements, 17 constraints, 17 deliverables and 34 marking criteria.

## 2. Metrics
| Metric | Definition | Target (spec §8) |
|---|---|---|
| Precision / recall / F1 per field | fuzzy one-to-one match (`tests/doc_intel/eval/metrics.py`): same kind and file, `max(Jaccard, overlap of the gold words in the quote)` >= 0.6 | requirements F1 >= 0.75 |
| Priority accuracy | must/should/could right, over matched requirements | — |
| Rubric marks accuracy | matched criteria with the exact marks | >= 0.9 on structured tables |
| Total marks | `total_marks` equals the stated total (or both empty) | all |
| Quote verified | requirements whose quote was found in the document | all |
| OCR gate | native files never OCR'd, scans always | all |
| OCR word accuracy | word-sequence similarity of the OCR'd text to the reference text | — |
| Heading recall | gold section titles found as headings | — |
| Latency | wall time per document / per page | — |

## 3. Results (2026-10-12, M3 MacBook, 16 GB; final code, prompt v3)
| Run | Mode | Models | Req F1 | Con F1 | Del F1 | Crit F1 | Priority | Marks | Totals | Quotes | OCR words | Time |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Cloud (shipped, recorded)** | `record` -> `replay` | Groq `gpt-oss-120b` (Gemini over its daily free quota) + Tesseract | **0.98** | **0.91** | **1.00** | **0.98** | 0.94 | 100 % | 9/10 | 100 % | 0.974 | 46 s (replay 1.5 s) |
| Rules + Tesseract | `rules` | none | 0.96 | 0.84 | 0.94 | 0.98 | 1.00 | 100 % | 9/10 | 100 % | 0.974 | 1.6 s |
| Earlier: Gemini 3.6 Flash, prompt v3, 9 cases | `record` | Gemini (reasoner + vision) | 0.98 | 0.91 | 0.97 | 1.00 | 0.98 | 100 % | 9/9 | 100 % | 0.997 | 88 s |
| Earlier: local only, prompt v2, 9 cases | `live --local-only` | `qwen3.5:9b`, no OCR | 0.84 | 0.76 | 0.86 | 0.93 | 0.95 | 100 % | 8/9 | 100 % | — | 829 s |

Text documents only (the 7 non-OCR cases of the earlier runs): local `qwen3.5:9b` 0.94 requirements F1 vs 0.93 for
the cloud, so the cloud mainly buys speed (about 15x) and reading scans. Every Sprint-2 target is met;
`tests/doc_intel/test_pipeline.py` keeps them as a regression gate in replay mode.

**Recordings.** `samples/llm_cache/doc_intel/` holds the shipped answers: extraction by Groq `gpt-oss-120b` (all
four Gemini keys hit `GenerateRequestsPerDayPerProjectPerModel-FreeTier` after a day of recording). There is no
recorded vision answer yet, so replay reads the scan and the photo with the local Tesseract (word accuracy 0.974;
the scan loses one marks-table row, so its total is withheld and asked about). To record Gemini again once its
quota resets: `uv run python -m tests.doc_intel.eval.run_eval --mode record`.

**Bugs found while evaluating (fixed, with tests):** Gemini rejected every call with `seed` (400), so seeded
calls never reached it; Gemini's and gpt-oss's hidden reasoning used up `max_tokens` and cut answers off; models
wrote `null` for fields that do not apply; Gemini sometimes answered an empty list for a part with clear
requirements (now treated as a miss: rules fill in); one 2,450-token part with 20+ items overflowed the answer
budget (parts are now at most ~1,200 tokens); a sentence ending in ":" was kept as a requirement while the list under
it was dropped (now each list item is a requirement); models turned "should" into "must" (an explicit modal word in
the source now decides the priority).

Reproduce (in `backend/`):
```bash
uv run python -m tests.doc_intel.eval.run_eval --mode rules
uv run python -m tests.doc_intel.eval.run_eval --mode replay          # recorded answers, no network
uv run python -m tests.doc_intel.eval.run_eval --mode record          # re-records; needs the team keys
uv run python -m tests.doc_intel.eval.run_eval --mode live --local-only   # needs Ollama; never use record here
```
Per-document numbers, misses, extras and open questions: `samples/doc_intel/eval_results/*.json`.

## 4. Ablations / comparisons
- **Rules vs LLM vs hybrid:** rules alone are precise (requirements precision 1.00) but miss sentences without
  modal verbs (recall 0.72) and cannot read scans. The LLM adds recall; the rules still raise confidence where they
  agree, and they are the fallback.
- **Prompt v1 -> v2:** clearer definitions of requirement vs constraint, with examples (requirements F1 0.92 ->
  0.95). **v3** adds the lead-in-list rule. Tuning stopped there on purpose (see §5).
- **OCR:** vision model 0.997 words (Gemini), Tesseract 0.974 after rule-line removal, single-column layout
  (`--psm 4`) and deskewing only above 2 degrees (each step measured on the scan and the photo).
- **PDF libraries:** measured in `research.md` §3.1. Plain-text quality is about the same; the layout rules make
  the difference.
- **Remaining errors** are borderline kinds: "The schema must be in third normal form" (gold: requirement; model:
  constraint) and "All tests must run with the single command pytest -q" (gold: constraint; local model:
  requirement). Reasonable people would label some of these differently.

## 5. Honest limitations
- The gold set is small, written by us, and was used while developing (prompt v2 was chosen on it), so the
  numbers are optimistic for real course documents.
- The shipped recordings come from Groq, not Gemini (daily quota); re-record when it resets.
- Real documents can still hold cases the gold set lacks: a real IT 314 lab sheet (not included, it is course
  material) found the lead-in-list problem, now fixed and covered by case g10.
- Gemini's free tier sometimes answers 503: `gemini-3.8-flash` was left out of the routes because of that. The
  recorded answers make tests and the demo independent of it.
- The local run is from before the final fixes (prompt v2, larger parts) and used Ollama's 4096-token context;
  `HMAP_OLLAMA_NUM_CTX=8192` is now the default.
