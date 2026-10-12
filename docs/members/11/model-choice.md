# Default model choice (Sprint 11 §0 prep task, run 2026-10-06 → 2026-10-10)

Run by Member 1 before Sprint 2 so every member tunes prompts on the model we ship. Data, harness and raw outputs:
`samples/model_bakeoff/` and `scripts/model_bakeoff.py` (re-run: see `samples/model_bakeoff/README.md`).

## Decision

| Role (`HMAP_ROLE_MAP`) | Model | Why |
|---|---|---|
| `reasoner`, `judge`, `coder`, `fast`, `classify` | **`qwen3.5:9b`** | best overall quality (0.833) and clearly best coding (68 % of tasks fully pass vs 56 % next); 5.8 GB fits the demo laptop budget (~6–7 GB for the chat model) |
| `embed` | `nomic-embed-text` | stays loaded next to the chat model (`OLLAMA_MAX_LOADED_MODELS=2`) |
| **lite tier** (low RAM/disk teammates) | **`qwen3.5:4b`** | almost the same quality (0.827), *better* critique/verification, 3.4 GB, ~1.7× faster; weaker only at coding |

`.env.example` already uses this map. One model for every role = no model-swap delays during the demo.

**Judge independence:** no other-family model is usable as the judge. `llama3.1:8b` caught 0 of 7 planted mistakes and
flagged all 3 correct outputs; `gemma4:12b` was skipped because it needs ~8 GB and does not fit next to Docker + the app
on the 16 GB demo laptop. So Members 6 and 10 get independence from a *separate judge prompt, temperature 0 and
objective checks first* (doc 02 §2.2b caveat (a)), not from a different model.

**Not chosen:** `qwen2.5-coder:7b` (the "coding specialist") was worse at coding than both Qwen 3.5 models (28 %) and
missed every planted mistake as a critic; `qwen3:8b` (the plan's old default) is beaten by the smaller `qwen3.5:4b`.

## Results (quality is speed-independent and final)

Quality = 0.25·extraction + 0.20·planning + 0.15·critique + 0.15·verify + 0.25·coding. All scored by code, no LLM judge.

| Model | Quality | Extraction | Planning | Critique (catch / false alarm) | Verify | Coding pass@1 (tests passed) | Valid JSON | Loaded RAM |
|---|---|---|---|---|---|---|---|---|
| **qwen3.5:9b** | **0.833** | 0.949 | 0.971 | 0.60 (71 % / 67 %) | 0.944 | **0.68** (0.82) | 100 % | 5.8 GB |
| qwen3.5:4b | 0.827 | 0.953 | 0.969 | **0.70** (86 % / 67 %) | **1.000** | 0.56 (0.68) | 98 % | 3.4 GB |
| qwen3:8b | 0.728 | 0.971 | 0.932 | 0.60 (86 % / 100 %) | 0.861 | 0.32 (0.52) | 100 % | 6.6 GB |
| qwen2.5-coder:7b | 0.651 | 0.889 | 0.976 | 0.20 (0 % / 33 %) | 0.889 | 0.28 (0.65) | 100 % | 5.0 GB |
| llama3.1:8b | 0.581 | 0.865 | 0.908 | 0.00 (0 % / 100 %) | 0.889 | 0.20 (0.52) | 98 % | 5.9 GB |
| gemma4:12b | — | skipped: ~8 GB, does not fit the demo RAM budget | | | | | | |

Sets: 10 extraction docs (2 with distractors / loose prose), 7 plans (2 with ordering rules), 10 critique items
(7 planted mistakes + 3 clean), 36 claim/quote pairs, 25 Python tasks with hidden tests. Settings: temperature 0,
seed 42, `think: false`, `num_ctx` 8192, JSON-schema `format`, no repair retries.

## Speed — NOT final

Measured tokens/s (generation): 4b 10.7 · 9b 6.3 · qwen3:8b 6.1 · coder 6.2 · llama 5.5. These were taken on a laptop
with ~5 GB swap in use after a day of model runs; an M3 normally does roughly 2–3× this. Re-run on a freshly
restarted machine with other apps closed (commands below) before quoting speeds. The *ranking* (4b ≈ 1.7× faster
than the 7–9B models) is consistent across runs.

## Coding with test feedback (2026-10-10, partial — paused by Member 1)

`uv run scripts/model_bakeoff.py coding-loop --model qwen3.5:9b --fix-rounds 2` (results in
`samples/model_bakeoff/results/_experiments/`). After a failed attempt the model gets the pytest output and retries.

| Setting | First try | After 1 fix | After 2 fixes | Tasks run |
|---|---|---|---|---|
| thinking off | 17/24 (71 %) | **20/24 (83 %)** | 20/24 (83 %) | 24 of 25 |
| thinking on | not run yet | | | 0 of 25 |

Never solved: multi-client chat server, URL router, CSV column means, markdown table — the multi-part tasks. ~2.5 min
per task on the current (swap-heavy) machine. Caveat: the retries see the hidden tests' output; in the platform those
are the acceptance tests the agent is given, so this is realistic but somewhat optimistic.

Consequence: one fix round is worth building in (Members 7/8); the team cloud key pool (doc 02 §2.5) is used for the
`coder` role to cover the multi-part tasks the local model still fails.

## What the critique numbers mean for Member 4

Every model flagged 2 of 3 correct outputs as wrong (67 % false alarms) — the small-model "rubber-stamp or nit-pick"
problem the Sprint 4 plan predicts. Programmatic critics must come first; the LLM critic needs a severity threshold
and calibration on Member 4's gold set.

## Fine-tune trial (rehearsal for Sprint 11) — blocked until a restart

- Data: `qwen3.5:4b` wrote 6 solutions for each of the 15 *training* tasks; the hidden tests kept 42 of 90
  (13 tasks covered). Held-out tasks c16–c25 are never trained on.
- LoRA on `mlx-community/Qwen3.5-4B-MLX-4bit` (4 layers, rank 8) fails with a Metal out-of-memory error on the
  current (swap-heavy) machine state; needs a restart.
- Early signal: validation loss starts at 0.31 — the model already finds its own accepted solutions very likely, so
  training on them has little to teach. Expect a null or tiny result; that is acceptable and will be reported.

## Re-run after a restart (clean machine, other apps closed)

```bash
OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama OLLAMA_MAX_LOADED_MODELS=2 ollama serve
uv run scripts/model_bakeoff.py speed --models qwen3.5:9b qwen3.5:4b
uv run scripts/finetune_trial.py train --num-layers 4 --max-seq 1536 --val-batches 2   # stop Ollama first
uv run scripts/finetune_trial.py eval
```
