# Evaluation — Member 11: local models, routing, benchmarking, fine-tuning

Reproduce (`cd backend`): `make bench` (the benchmark, replayed: no model call),
`uv run python -m hmap.agents.models.bench.run quick --models <model> --mode record` (a new model, live),
`scripts/demo_sprint_11.sh` (router on vs off, offline), `python3 ../samples/models/check_memory.py` /
`check_router.py` (the prototype checks). Results: `samples/models/bench/`, `samples/models/finetune/`.

**Measured after a restart on 2026-11-02** (swap 0 GB at the start): speed, memory at three context lengths,
warm-up, tier smoke runs, the scheduler under mixed load, peak RAM with the demo, adapter serving, member gold sets.

## 1. Memory: predicted vs measured (item 11.2)
`hardware.py` = the prototype's model (weights + KV cache only in the attention layers of hybrid models). On the
prototype's saved `/api/ps` numbers: mean error 0.21 GB over 5 models, no fitted constants (the every-layer formula
0.34 GB). Ollama's log confirms the hybrid layout: a KV cache in 8 of 32 layers + a 50 MB recurrent state.

Measured 2026-11-02 at three context lengths (`samples/models/bench/results/memory_ctx.json`). `/api/ps` turned out
to be Ollama's **estimate**, not the memory in use (the same 9B load at 8k read 5.77 GB and 6.45 GB), so the ground
truth here is the drop in free system memory per load (2 loads each):

| Model | Context | Real (free-memory drop) | Ollama's estimate | Predicted | Error |
|---|---|---|---|---|---|
| qwen3.5:4b | 2k / 8k / 32k | 2.83 / 2.98 / 3.58 GB | 3.11 / 3.41 / 4.35 | 2.72 / 2.92 / 3.72 | −0.11 / −0.07 / +0.14 |
| qwen3.5:9b | 2k / 8k / 32k | 5.75 / 6.34 / 7.52 GB | 6.13 / 6.45 / 6.69 | 5.70 / 5.90 / 6.70 | −0.06 / −0.45 / −0.82 |

- The 4B is predicted within 0.15 GB at every length: the prototype's "+0.5 GB 4B gap" was Ollama's estimate
  over-counting, not the model.
- The 9B grows faster with context than predicted (+1.8 GB from 2k to 32k vs +1.0 predicted) and its repeats are
  noisy (7.10 / 7.95 GB at 32k): sizing.md budgets ~1 GB extra for the 9B at long context. `RUNTIME_OVERHEAD_GB`
  stays empty (a fixed offset would not fix a context-dependent gap).

## 2. Benchmark (item 11.5): the quick set, 8 models × 5 tasks × 4 roles
The §0 bake-off's 88 items (10 extraction docs, 7 plans, 10 critiques with 7 planted mistakes, 36 claim / quote pairs,
25 Python tasks with hidden tests), through the platform gateway, same prompts / settings / scoring code, **no JSON
repair retries**. Replaying the bake-off's saved local answers through the harness gives the bake-off's numbers
exactly (`tests/models/test_bench.py`), so local and cloud rows compare on one footing.

| Model | Where | Quality | Extraction | Planning | Critique (catch / false alarm) | Verify | Coding pass@1 |
|---|---|---|---|---|---|---|---|
| **qwen/qwen3.8-27b** | Groq (free) | **0.987** | 0.986 | 1.000 | 1.000 (100 % / 0 %) | 1.000 | **0.96** |
| openai/gpt-oss-120b | Groq (free) | 0.937 | 0.965 | 1.000 | 1.000 (100 % / 0 %) | 0.972 | 0.80 |
| qwen3.5:9b | local (default) | 0.833 | 0.949 | 0.971 | 0.600 (71 % / 67 %) | 0.944 | 0.68 |
| qwen3.5:4b | local (lite) | 0.827 | 0.953 | 0.969 | 0.700 (86 % / 67 %) | 1.000 | 0.56 |
| qwen3:8b | local | 0.728 | 0.971 | 0.932 | 0.600 | 0.861 | 0.32 |
| openai/gpt-oss-20b | Groq (free) | 0.697 | 0.595 | 0.429 | 0.900 (100 % / 33 %) | 0.917 | 0.76 |
| qwen2.5-coder:7b | local | 0.651 | 0.889 | 0.976 | 0.200 | 0.889 | 0.28 |
| llama3.1:8b | local | 0.581 | 0.865 | 0.908 | 0.000 | 0.889 | 0.20 |
| gemma-4-31b-it / 26b-a4b-it | Gemini API (free) | **too slow to use**: answers carry the model's thinking text (`<thought>…`), the gateway's thinking switch is rejected (400), and a call takes ~110 s (31b: extraction 0.90 on 10 / 10 answered); the full set and the 56-claim test were stopped after 35 / 71 min | | | | | |
| gemini-3.6-flash / 3.5-flash | Gemini | **not measurable on the free tier**: on 2026-11-01 the daily quota was spent; on 2026-11-02 Gemini 3.6 Flash answered 5 extraction items, then 30 rate-limited attempts with growing cooldowns (160 s) and no further answer in 20 min | | | | | |

- Every cloud item was answered (rate-limited calls retried after 25 s); one Qwen critique item was not (9/10).
- `gpt-oss-20b`'s low extraction / planning come from invalid JSON (valid 60 % / 43 %; no repair here; the platform
  repairs once): it is the default `fast` / `classify` route, which asks only short structured questions.
- The router's table (`samples/models/bench/table.json`): reasoner = extraction + planning, judge = critique + verify,
  coder = coding, fast / classify = extraction + verify (a proxy). Differences under 0.05 do not reorder routes.

**Claim checks on held-out data** (the M6 benchmark's 56 clean / natural / wrong-number / unsupported claims, Member
6's own prompt; `samples/models/finetune/claims_cloud.json`). Accuracy = supported vs not supported (Member 6's
aggregator gives `refutes` and `not_enough` the same verdict, UNSUPPORTED):

| Judge | Accuracy | Unsupported claims judged supported | Median latency |
|---|---|---|---|
| Groq `gpt-oss-20b` | **0.946** | 2 | 0.57 s |
| Groq `qwen3.8-27b` | **0.946** | 1 | 0.26 s |
| Groq `gpt-oss-120b` | 0.929 | 2 | 0.63 s |
| local `qwen3.5:4b` + LoRA (§5) | 0.893 | 5 | ~3 s (MLX) |
| local `qwen3.5:4b` | 0.875 | 6 | ~3 s (MLX) |

**Member gold sets** (each owner's own evaluator, unchanged, every chat role on the model under test, live, 2026-11-02;
`samples/models/bench/sets/<model>/`):

| Set (owner) | Model | Score | Notes |
|---|---|---|---|
| M3 planning: plan validity | Groq `gpt-oss-120b` (the reasoner route) | **1.00** | 9 cases, 42 s |
| M4 issue categories: accuracy | Groq `gpt-oss-20b` (the classify route) | 0.625 | 80 items; Member 4's recorded model run: 0.65 |
| M10 review judge alone: κ vs the reviewed labels | Groq `qwen3.8-27b` (today's judge) | **0.707** (acc 0.806) | 0 FAIL→PASS; the same as Member 10's own run |
| M10 review judge alone: κ | Groq `gpt-oss-20b` | 0.627 (acc 0.750) | 0 FAIL→PASS: weaker than Qwen for Member 10 |
| M6 verification: accuracy | Groq `gpt-oss-20b` / `qwen3.8-27b` | (0.686 / 0.674) | **not a model measurement**: 72 of 86 claims were decided by Member 6's rule fallback, only 2–4 model calls; the direct claim-check table above is the valid M6 number |
| M2 extraction F1, M5 research, M7 coding | — | not run | M2 / M7 cost many calls (the coder set is the quick set's coding suite already); M5's offline corpus covers only networking topics (Sprint 10 defect 16) |

## 3. Model-size study (item 11.6)
Speed measured 2026-11-02 on a restarted laptop (swap 0 GB; `bench/results/speed.json`; median of 3, 100 % GPU):

| Variant | Quality | Weights | Real memory (8k ctx) | Generation | JSON generation | Prefill | TTFT | Cold load |
|---|---|---|---|---|---|---|---|---|
| qwen3.5:4b Q4_K_M | 0.827 | 2.65 GB | 2.98 GB | **23.8 tok/s** | 22.7 tok/s | 133 tok/s | 0.19 s | 7.1 s |
| qwen3.5:9b Q4_K_M | 0.833 | 5.63 GB | 6.34 GB | 6.3 tok/s | 5.9 tok/s | 36 tok/s | 0.71 s | 10.7 s |

The clean 4B is 2.2× faster than under swap (10.7 → 23.8 tok/s); the 9B did not change (6.3), so it was not swap but
the model: it runs 100 % on the GPU yet is ~3.8× slower than the 4B at ~2.1× the size (both hybrid models; the M3's
memory bandwidth). The 4b is within noise of the 9b (−0.006 on 88 items) at 47 % of the memory and ~3.8× the speed;
it is worse only at coding (0.56 vs 0.68), where the cloud does the work anyway. **Recommendation (rule: smallest
memory within 0.015 of the best): `qwen3.5:4b` as the local fallback for every role except a local-only coder.**

## 4. The router vs the role maps (item 11.7)
**Offline** (`scripts/demo_sprint_11.sh`, scripted providers: Gemini answering 429 with a 1 s retry-after, Groq
answering): same answers; **10 HTTP attempts with the role maps, 7 with the router** (the key pool retries the cooled
Gemini key each time its second is over; the router remembers the model's 429 for a minute). With a long
retry-after the key pool alone already skips the route and the router saves nothing (stated in the demo).

**Live** (golden TCP-chat scenario, `scripts/demo_final.sh --live --only=tcp`, team keys, Ollama off, alternating
off / on, 2026-11-01; Gemini's quota was spent, so its route answered 429 all day):

| Run | Router | Answered by the cloud | Not answered (agent's no-model path) | 429 attempts | 429 per answer | Outcome |
|---|---|---|---|---|---|---|
| 1 | off | 55 | 180 | 29 | 0.53 | COMPLETED |
| 1 | on | 56 | 124 | 21 | 0.38 | COMPLETED |
| 2 | off | 71 | 1 | 28 | 0.39 | REVIEWING (escalated) |
| 2 | on | 91 | 2 | 12 | **0.13** | COMPLETED |

Fewer wasted rate-limited attempts per answer in both pairs; both router-on runs completed. Two pairs is thin: run 1
ran while the benchmark had just used the Groq keys (most calls unanswered in both arms), and live runs differ in how
much work the agents do (130 vs 150 calls in run 2), so the one escalation is not attributed to the router. By the
plan's rule (Q2: no worse outcome, fewer rate-limited calls) **`HMAP_ROUTER=on` is the default**; `off` restores the
role maps exactly. The benchmark table changes nothing on today's default routes yet: every role's route list
includes an unmeasured Gemini model, and the router reorders by quality only when every route is measured.

**Local policies** (prototype simulation on the bake-off, `check_router.py`): single 9b 0.832 / 582 s; single 4b
0.829 / 275 s (−53 % time); role tables picked from the data overfit (0.817–0.823); cascade 4b → 9b 0.879 / 320 s
(an upper bound: its escalation signal was the grading tests). The router does not use the cascade (stretch, not
built): the team does not run local models in the demo.

## 5. Fine-tune (items 11.9–11.12)
- **Data** (`finetune/data.py`): 235 clean examples of Member 6's claim judge (the cloud judge's recorded answers =
  distillation) on 93 claims; dropped: 146 evaluation claims (contamination), 34 invalid answers, 42 without a claim
  line; split by claim: 181 train / 24 valid / 30 test. Imbalanced: `refutes` appears twice in training.
- **Training** (`finetune/train.py`): LoRA on `mlx-community/Qwen3.5-4B-MLX-4bit`, rank 8, 4 layers, 200 iterations,
  lr 1e-5, max 1536 tokens: **completed on the 16 GB laptop in 18 min** (with 3 GB of swap in use; the §0 trial had
  run out of memory). Train loss 0.68 → 0.44; validation loss noisy (0.36–0.78, 2 batches).
- **Held-out result** (`finetune/eval.py`, MLX greedy for both arms, the gateway's schema hint for both):

| | Untrained 4b | 4b + LoRA |
|---|---|---|
| M6 benchmark, 56 claims never trained on: supported vs not | 0.875 | **0.893** |
| — strict 3-way label | 0.750 | 0.839 |
| — unsupported claims judged supported | 6 | 5 |
| own test split (30, in distribution) | 0.900 | 0.933 |
| regression: bake-off critique (10) | 0.70 | 0.60 |
| regression: bake-off extraction (5 docs) | 0.57 | 0.79 |

**Honest reading: no clear gain.** On the measure that decides the platform's verdict the adapter moves one claim of
56 (within the ±0.03 noise set in advance); most of the strict-label gain is the adapter answering `not_enough` where
the untrained model said `refutes`, which Member 6 treats the same. The regression rows are too small to call (one
critique item; 5 documents). The free cloud judges are better (0.93–0.95). A first evaluation without the schema hint
(0 → 0.89) only measured the output format and is kept as `eval_result_no_schema.json` for the record.
- The adapter's weights (`samples/models/finetune/adapters/<run>/adapters.safetensors`, 7.7 MB) are not committed
  (`*.safetensors` is git-ignored like every model file); `finetune.train` rebuilds it (18 min).
- **Serving (11.12)**, checked 2026-11-02: Ollama 0.35.1 refuses (`ollama create` with `ADAPTER`: "LoRA adapters are
  no longer supported"). The fallback works: `mlx_lm.server --adapter-path` behind the `mlx` backend answered 6 / 6
  held-out claims correctly through the gateway, ~1.7 s each (`finetune/serve_check.json`). Routing to it:
  `HMAP_MLX_BASE_URL=http://127.0.0.1:8080/v1` + `HMAP_ROUTE_OVERRIDES=verify:judge=mlx:default_model`. The real
  server found two defects the fake-server tests had missed, both fixed in the backend and now tested: Qwen's
  template takes one system message (the schema hint is merged into it), and Qwen 3.5 thinks unless told
  `chat_template_kwargs.enable_thinking=false` (the answer came back empty). Not deployed: no gain to deploy.

## 6. Time, memory and cost
| | |
|---|---|
| Warm-up (item 11.18) | first call 11.7 s cold → **0.56 s** after warm-up (9B); 7.9 s → 0.31 s (4B) |
| Scheduler under mixed load (11.4) | 16 chat calls (4B + 9B, 4 roles) + 4 embeddings at once: 0 errors, 0 refused, **1 model switch** (grouped by model), 1 unload, peak 14.8 GB (`bench/results/scheduler_live.json`) |
| A routing decision | < 1 ms (no I/O on the call path; machine state refreshed every 30 s in the background) |
| Decision log | ~200 rows per golden run, 7 days kept, no prompt text |
| Training | 18 min, peak below the 16 GB budget with the demo stack stopped |
| Benchmark | quick set per cloud model ~10–30 min live (free-tier limits); replay seconds |

## 7. Recommendations for Member 1 (model decisions, not applied)
1. **Member 6's claim judge → Groq `gpt-oss-20b`** (0.946 on held-out claims, as good as Qwen; a separate model
   quota), freeing `qwen3.8-27b`. Note: same family as the reasoner's fallback `gpt-oss-120b` (judge independence);
   Member 6's order swap and number guard limit the risk.
2. **Coder → `groq:qwen/qwen3.8-27b` first, `gpt-oss-120b` second** (0.96 vs 0.80 pass@1) in
   `DEFAULT_CLOUD_ROLE_MAP`; check one live golden run for 429s on Qwen first. Try without editing:
   `HMAP_ROUTE_OVERRIDES=verify:judge=groq:openai/gpt-oss-20b,*:coder=groq:qwen/qwen3.8-27b` (the override keeps
   only that route).
3. Member 10's review judge stays on Qwen: κ 0.707 vs 0.627 for `gpt-oss-20b` on Member 10's own set, and it makes
   only 0–6 calls per review.
4. Local fallback: **`qwen3.5:4b`** (`HMAP_ROLE_MAP` from `scripts/pull_models.sh --tier lite`): measured 13.1 GB
   peak with the demo vs 15.5 GB for the 9B, 3.8× faster, quality within noise except coding (§3, sizing.md).
5. Do not deploy the LoRA adapter (§5); the Laya / Kev decision-model experiment (spec §5c) stays cut.
6. Restart the laptop before the demo: the measurement session pushed swap back to 3 GB.

## 8. Honest limits
- 88 items per model: differences under ~0.01–0.03 are noise; one run per cloud model (temperature 0).
- The live router comparison is 2 pairs on one day with one saturated provider.
- `fast` / `classify` quality is a proxy (extraction + verify).
- Speeds and latencies were taken with swap in use.
