# Local models & routing prep (Member 11, prepared ahead of Sprint 11)

Builds on the Sprint 11 §0 model bake-off already on main (`docs/members/11/model-choice.md`,
`samples/model_bakeoff/`). Three working pieces, runnable with only Python 3.11 (no Ollama, no models, no project
code; the checks read the snapshot in `data/`):

```bash
python3 samples/models/check_memory.py        # predicted vs measured model memory + laptop sizing table; OK
python3 samples/models/check_router.py        # router policies simulated on the bake-off results; OK
python3 samples/models/memory.py qwen3.5:9b 32768                                  # one model at one context
python3 samples/models/gguf_meta.py --ollama /Volumes/Tirth_SSD/ollama qwen3.5:9b  # needs the models on disk
```

## Pieces
| File | Sprint 11 item | What it does |
|---|---|---|
| `gguf_meta.py` | 11.1, 11.2 | Reads a GGUF model file's header (architecture, layers, KV heads, head size, context, quantization) with the standard library. Finds the file from an Ollama model name through its manifest. The 150k-entry vocabulary is skipped, so it takes 0.2 s. |
| `memory.py` | 11.2, 11.14 | Memory = weights + KV cache × context. **Hybrid-aware**: Qwen 3.5 keeps a KV cache in only every 4th layer (`full_attention_interval` = 4). |
| `router.py` | 11.7 | Router policies (one model, a benchmark-picked role table, a cascade with self-check escalation), each call logged as a `RouteDecision` with a reason. Simulates them on real bake-off results, including model-swap cost when two models do not fit in memory together. |
| `build_snapshot.py` | | Rebuilds `data/` from `samples/model_bakeoff/results/` (88 items × 5 models) and the GGUF headers. |
| `check_memory.py`, `check_router.py` | 11.2, 11.7 | The two checks. |

## 1. Memory: predicted vs measured (`check_memory.py`)
| Model | Weights | Predicted @ 8k ctx | Measured (`/api/ps`) | Error |
|---|---|---|---|---|
| qwen3.5:9b | 5.63 | 5.90 | 5.77 | +0.13 |
| qwen3.5:4b | 2.65 | 2.92 | 3.41 | −0.49 |
| qwen3:8b | 5.23 | 6.43 | 6.63 | −0.20 |
| qwen2.5-coder:7b | 4.68 | 5.15 | 4.98 | +0.17 |
| llama3.1:8b | 4.92 | 5.99 | 5.92 | +0.07 |

**Mean error 0.21 GB with no fitted constants** (naive formula with KV in every layer: 0.34 GB; for qwen3.5:9b it is
off by 0.93 GB). The 4b gap is an **open question**. It is not the vision projector, and Sprint 11 should measure
`/api/ps` at 2–3 context lengths to separate fixed overhead from per-token cost.

Sizing table (assumed: macOS + apps 4.5 GB, demo stack 3 GB, 1 GB headroom; item 11.17 replaces these with
measurements):
- **16 GB:** the 9b fits even at 32k context.
- **9b + 4b together:** need 24 GB, so on the demo laptop any routing between them pays a cold load.
- **8 GB:** no live model next to the demo stack. Use Tier 0 (`replay`) or run without the stack.

## 2. Router simulation (`check_router.py`, 16 GB laptop, scored on held-out halves)
| Policy | Quality | Time per project | vs today |
|---|---|---|---|
| single qwen3.5:9b (**today**) | 0.832 | 582 s | |
| single qwen3.5:4b (lite) | 0.829 | 275 s | −0.003 quality, **−53 % time** |
| table, Qwen 3.5 pair | 0.817 | 438 s | −0.015, −25 % |
| table, all 5 models | 0.823 | 380 s | −0.010, −35 % |
| cascade 4b → 9b on failed self-check | **0.879** | 327 s | **+0.046, −44 %** (upper bound, see below) |

What it says:
- **Per-role tables picked from the data overfit:** the two halves pick different models for extraction,
  planning and coding, and both tables score below today. With ~10 items per task type, a table learns noise.
- **The lite model is nearly as good at half the time.** The bake-off already found 4b ≈ 9b except coding. This
  makes the time side concrete.
- **A cascade is the promising router:** 4b first, and 9b only when a check the platform really has fails (invalid
  JSON, a plan with a cycle, failing acceptance tests). It escalates on about 11 of 25 coding tasks and almost
  nothing else.

Sanity check: the single-model policies reproduce the bake-off's 0.833 / 0.827 exactly.

## Honest limits
- **The cascade number is an upper bound.** In the bake-off, the tests that trigger escalation are the same tests
  that grade the result. In the platform the agent's acceptance tests are not the grader's hidden tests. Sprint 11
  must measure the cascade with separate tests.
- Speeds come from a laptop under swap pressure (`model-choice.md` says re-run on a clean restart). The ratios are
  more reliable than the seconds.
- 88 items: differences of about 0.01 are noise.
- **Nothing here changes the team's model decision** (`qwen3.5:9b` for every role). A routing change needs the
  Sprint 11 regression matrix green first (item 11.19).
- No cloud models in the simulation: the bake-off measured local models only.
