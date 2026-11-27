# Design — Member 11: local models, routing, benchmarking, fine-tuning

The plug-in is `backend/src/hmap/agents/models/` (no agent: nothing in a task graph is a "models" capability). It
plugs in through the `llm_provider` strategy slot (Member 1's wiring, [core-requests](core-requests.md) 1–4); agent
code is unchanged: agents still ask for roles.

## 1. The call path

```text
agent ── generate(role, messages) ──► Gateway ──(replay hit / fake: answered here, the router is not asked)
                                         │
                                         ├─ route.decide(RouteQuery{role, plug-in, ~tokens, schema?, cloud allowed,
                                         │                         role-map model, configured routes, usable keys})
                                         │      └─► RoutePlan{cloud route order | [] , local model, local provider,
                                         │                    reason, decision id}            (None = role maps)
                                         ├─ key pool: the plan's routes in its order (per-key cooldown, auth disable,
                                         │            transient retry: unchanged) ── each attempt ─► observe_attempt
                                         ├─ local: the plan's provider (the scheduler / an MLX server) or Ollama
                                         └─ route.observe(outcome) ─► the decision log (route_decisions, 7 days)
```

The replay key does not include the model, so routing never changes what a replay answers: router on and off are
identical in `fake` / `replay` (the matrix's tier-0 rows), and the router's effect shows only live (eval.md §4).

## 2. Pieces

| Module | Item | What |
|---|---|---|
| `registry.py`, `gguf.py`, `store.py`, migration `011` | 11.1 | `ModelSpec` rows from Ollama (`/api/tags`, `/api/show`, `/api/ps`, the GGUF header), the cloud routes (keys present → `available`), MLX / llama.cpp servers, else the saved snapshot. Pin / disable survive a sync |
| `hardware.py` | 11.2 | memory = weights + hybrid-aware KV cache × context; live RAM / swap / GPU (Metal, CUDA) / Docker VM / loaded models; `feasible` → fits / fits alone / does not fit + why; the sizing table; a peak-RAM sampler (`--watch`) |
| `backends/` | 11.3 | one interface (health cached 10 s, `chat(ChatRequest)`): Ollama, `mlx_lm.server`, llama.cpp `llama-server`, the key pool. The gateway's JSON validation / repair covers the servers without schema support |
| `scheduler.py` | 11.4 | local calls only: priority by role, swap-aware grouping, starvation guard, admission (does not fit → refused; fits alone → the other heavy model unloaded: the old unload guard) |
| `bench/` | 11.5, 11.6 | the quick set (the bake-off's 88 items through the gateway, any model), the member gold sets (each owner's evaluator, results redirected), speed, the quality table, the quant report |
| `router.py` | 11.7, 11.8 | the strategy (below) |
| `finetune/` | 11.9–11.12 | dataset (validator, contamination, dedupe, split by claim), MLX LoRA, base vs LoRA eval, serving (Ollama `ADAPTER` or MLX server) |
| `api.py` + `frontend/src/features/models/` | 11.13 | `/api/models`: registry, hardware, routes (+ `since` poll = the stream), bench, fine-tune; the Models page |
| `warmup.py`, `smoke.py`, `scripts/pull_models.sh`, `scripts/release_matrix.*` | 11.16–11.19 | tiers, warm-up, the release matrix |

## 3. Router policy (`router.py`)

The team's decision (every chat role cloud-first, then the local model) is the frame: the router orders the routes
the policy lists and picks the local fallback; it never adds a provider.

1. **Override** `HMAP_ROUTE_OVERRIDES=plugin:role=model` (`*` any plug-in; `provider:model` = only that route).
2. **Rules**: a route that rejected a prompt at least 90 % this size is skipped (learned per model); a **saturated**
   route goes last: its provider has no usable key now, or the model answered 429 in the last minute with no
   success since, or it used its free-tier budget this minute (requests per key: Groq 30, Gemini 10).
   `cloud_ok=false` → no cloud.
3. **Benchmark table**: when every remaining route is measured for the role and they differ by more than 0.05, the
   best goes first; otherwise the configured order stands (88-item sets: smaller differences are noise).
4. **Local step**: the role map's model if installed, enabled and it fits; the already-loaded model instead when it
   is within 0.02 for that role (no swap); else the best installed model that fits; unknown machine state (Ollama
   never answered) → the role map. It runs through the scheduler.

Every decision gets one reason line, the rule that decided and its outcome (who answered, attempts, 429s, latency,
tokens); no prompt or answer is logged. Background tasks (only while routing): the registry + hardware refresh every
30 s, the log flush every 1 s (Postgres when the platform runs on it, so the API process sees the agents' process).

Not built: the cascade (cheap model first, escalate on a failed self-check; plan D8, stretch). The prototype's +0.046
is an upper bound and the team does not use the local models in the demo.

## 4. Benchmark design

- **Quick set** = the §0 bake-off, unchanged prompts, schemas, settings (temperature 0, seed 42, `think` off, **no
  repair retries**) and scoring code, now through the gateway, so a cloud model is asked exactly like a local one.
  Each model records into its own root (`samples/llm_cache/models/<model>/`); the bake-off's saved answers were
  imported as the local models' recordings, and replaying them reproduces the bake-off's scores exactly (a test).
- An unanswered call (rate limited past 3 retries) is **not scored**; the table shows answered / items.
- Role quality for the router: reasoner = extraction + planning, judge = critique + verify, coder = coding,
  fast / classify = extraction + verify (a proxy, stated).
- **Gold sets**: each member's evaluator runs unchanged in a child process with every chat role on the model under
  test and its results folder pointed at `samples/models/bench/sets/` (no member's folder is written).

## 5. Fine-tune design

Skill: Member 6's claim-vs-passages judge (plan Q5). Data: the recorded cloud judge answers (distillation), filtered
by the validator, with every evaluation claim removed (the M6 benchmark, the bake-off verify set), deduped, split by
claim. Base: `mlx-community/Qwen3.5-4B-MLX-4bit` (the lite model's family and size; 4-bit base = QLoRA-style).
Eval: the same engine (MLX, greedy) for base and LoRA, on the M6 benchmark (never trained on) + the in-distribution
test split + a regression check (bake-off critique + extraction). Serving: Ollama `ADAPTER` if the architecture is
supported, else `mlx_lm.server --adapter-path` behind the `mlx` backend.

## 6. Differences from the plan

- The decision stream is a 2 s poll (`GET routes?since=`), not a WebSocket: the plug-in mount's session dependency
  does not work on WebSocket routes (core-requests, last note).
- `HMAP_ROUTER_CASCADE` was dropped with the cascade (stretch, not built).
- Registry routes are `/api/models/registry…` (`/api/models/models` read badly).
