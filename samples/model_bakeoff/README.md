# Model bake-off data (prep task for Member 11, Sprint 11 §0)

Small, hand-made samples of the work hmap's agents will do, used to pick the default local models
**before** Sprint 2 starts. All scoring is done by code — no LLM judges.

| Folder | Items | What is measured | Seeds the gold set of |
|---|---|---|---|
| `extraction/` | 8 made-up assignment documents (`e*.txt`) + `gold.json` keyword answer keys | recall of requirements / constraints / deliverables (half credit if put in the wrong category), rubric marks exactly right, requirement quotes copied verbatim | Member 2 |
| `planning/` | 5 requirement sets (`inputs.json`) | task graph: unique ids, no dangling deps, acyclic, every requirement covered, single review sink, code→test ordering, no code tasks for non-code projects | Member 3 |
| `critique/` | 10 outputs: 7 with one planted mistake, 3 clean (`items.json`) | planted mistake found (needs_revision + matching description); clean ones not flagged | Member 4 |
| `verify/` | 20 claim + quote pairs (`items.json`) | SUPPORTED / NOT_SUPPORTED / CONTRADICTED accuracy | Member 6 |
| `coding/` | 25 assignment-style Python tasks (`c*/task.md`) with hidden pytest suites | pass@1 (all hidden tests pass) and fraction of tests passed | Member 7 / 8 |

`coding/_reference/` holds reference solutions written **only** to prove each hidden test suite is correct
(all 25 pass). They are never shown to a model and never used as training data.
`coding/split.json`: `train` (c01–c15) may be used by the fine-tune trial, `heldout` (c16–c25) never.
`coding/sandbox.sb`: macOS `sandbox-exec` profile — generated code gets no internet, may only listen/connect on
localhost, and may only write inside its own work folder.

## Run

```bash
ollama serve                                   # with OLLAMA_MODELS on the SSD, MAX_LOADED_MODELS=2
uv run scripts/model_bakeoff.py run --models qwen3.5:9b qwen3:8b gemma4:12b
uv run scripts/model_bakeoff.py report         # -> results/summary.md + summary.json
uv run scripts/model_bakeoff.py rescore        # recompute scores from stored outputs after a scoring fix
```

Results go to `results/<model>/<suite>.jsonl` (every raw model output is kept) and `results/summary.md`.
Settings: temperature 0, seed 42, `think: false`, `num_ctx` 8192, JSON-schema `format` for structured suites,
no repair retries (we measure raw reliability; the platform gateway adds repair later).

Quality = 0.25·extraction + 0.20·planning + 0.15·critique + 0.15·verify + 0.25·coding.

## Limits (be honest when quoting numbers)
- Small sets (8/5/10/20/25 items): differences under ~5 points are noise.
- Keyword answer keys can miss a correct paraphrase; inspect raw outputs before concluding.
- Speed numbers are only valid when nothing else heavy runs (downloads, browser video, Docker).
