# Sprint 11 plan of action — Member 11: Local LLMs, fine-tuning & model routing (+ the final release gate)

Spec: [`docs/sprints/sprint-11-member11-local-llm-routing.md`](../../sprints/sprint-11-member11-local-llm-routing.md)
(items 11.1–11.15, optional 11.L1–11.L4, release gate 11.16–11.24). Research: [`research.md`](research.md). Model
choice (the §0 bake-off): [`model-choice.md`](model-choice.md). Prototype: [`samples/models/`](../../../samples/models/README.md).
Written 2026-11-01 against the code as handed over after Sprint 10 (`check_sprint.sh 10` PASS, 2026-11-01).

**Status (2026-11-02): built with the defaults (Q1–Q12; Q4 answered by Member 1: no extra local download) and Q6 (the
restart: personal). `check_sprint.sh 11` passes with the router on and off; the release gate's results are in
[release.md](release.md), the numbers in [eval.md](eval.md). Local-model measurements done after a restart (2026-11-02). Still open: the
model decisions (eval.md §7), the live rehearsals, the video and the sign-off.**
Done before this sprint: the research deliverable (spec §3, [`research.md`](research.md)) and the §0 bake-off
([`model-choice.md`](model-choice.md)).

The sprint in one line: turn the gateway's fixed role → model maps into model infrastructure. That means:
- a registry, a memory-feasibility check and backends behind one interface;
- a scheduler, benchmarks on every member's own gold sets, and a model-size study;
- a **router** that decides per call and logs why, plus one measured LoRA experiment;
- then the **final release gate**: model tiers on the presenter laptop, the regression matrix, chaos, the clean-copy
  run, rehearsals and the freeze. This ends the project.

**Context that shapes this plan (Member 1, 2026-11-01).** The team will probably not use local models in the demo:
- every chat role is cloud-first (`DEFAULT_CLOUD_ROLE_MAP`, the team's decision, not re-argued here);
- the local `qwen3.5:9b` tier could not finish a golden scenario in 90 min on this laptop (Sprint 10 eval §6);
- the single-model tier runs on Groq's `qwen/qwen3.8-27b`, where ~180 of ~217 calls hit the free-tier rate limits.

So the router's most useful job here is **spreading calls over the cloud models and keys**: what to try first, what to
skip because it is cooling down or the prompt is too long, and which local model to fall back to. Picking between two
local models matters less. The local items the spec requires (size study, LoRA, sizing) are still done, at the size
this laptop allows, and reported honestly.

---

## 0. What already exists (checked in the code)

| Thing | Where | State |
|---|---|---|
| `ModelSpec`, `RouteDecision`, `BenchmarkResult` | `core/contracts/domain.py:460-490` | done (Sprint 1). `ModelSpec{id, family, params_b, quant, ctx, backend ollama/llamacpp/mlx/cloud, mem_gb, tok_s, roles_ok, status}`, `RouteDecision{role, model, backend, params, reason}`, `BenchmarkResult{model, quant, role, task, quality_score 0–1, tok_s, ttft_s, mem_gb}`. **No contract change needed**: the spec's `capabilities` field is covered by `roles_ok` (see D1) |
| `llm_provider` strategy slot | `core/plugins.py:27` (`STRATEGY_SLOTS`) | declared, **never read** (trap T1) |
| Gateway | `core/llm/gateway.py` | modes fake / replay / live / record, `HMAP_LLM_RECORD_MISSING`, `for_plugin`, `local_only`. Role → model `resolve_model(settings.role_map, role)` (`classify` → `fast` → `reasoner`). Dispatch (`_dispatch`): key pool (`CloudRouter`) for mapped roles, then the legacy lane, then the local provider under `asyncio.Semaphore(llm_max_concurrency=1)`. Telemetry span + `hmap_llm_*` metrics + `llm.call` log per call |
| Team key pool | `core/llm/cloud.py`, `key_pool.py` | `CloudRouter.chat(request)` tries the role's `provider:model` routes in a **fixed** order with per-key cooldown (429 / retry-after), auth disable, transient retry; `None` → local. `usage()` = per key fingerprint counters. Routes come from `DEFAULT_CLOUD_ROLE_MAP` (`config.py:31`) |
| Providers | `core/llm/providers/{ollama,openai_compat}.py` | `ChatProvider` / `EmbedProvider` / `LocalProvider` protocols (`providers/base.py`). `OpenAICompatProvider` works against any OpenAI-compatible server, which is what `mlx_lm.server` and `llama-server` both expose |
| Settings | `core/config.py` | `HMAP_ROLE_MAP`, `HMAP_CLOUD_ROLE_MAP`, `HMAP_CLOUD_OK`, `OLLAMA_BASE_URL`, `HMAP_OLLAMA_NUM_CTX` 8192, `HMAP_LLM_MAX_CONCURRENCY` 1. No `HMAP_ROUTER` yet |
| Replay cache | `core/llm/cache.py` | the key is plug-in + role + messages + schema + options. **It does not include the model** (trap T2) |
| Gateway wiring | `system.py:145` (`build_llm(settings)`), `core/runtime/host.py:85` (`make_llm`, agents in their own process) | two places build the gateway (T3) |
| Bake-off harness | `scripts/model_bakeoff.py`, `samples/model_bakeoff/` | 88 items × 5 local models (extraction, planning, critique, verify, coding), speed (taken under swap, **not final**), `coding-loop`, `gen-data` |
| Fine-tune trial | `scripts/finetune_trial.py` (uv script, `mlx-lm>=0.28`), `samples/model_bakeoff/finetune/` | 42 accepted coding solutions of `qwen3.5:4b`, held-out tasks c16–c25. LoRA on `mlx-community/Qwen3.5-4B-MLX-4bit` (weights cached in `/Volumes/Tirth_SSD/hf_cache`, 2.9 GB) **failed with a Metal out-of-memory error under swap**; validation loss already 0.31 |
| Prototypes | `samples/models/{gguf_meta,memory,router,check_memory,check_router,build_snapshot}.py`, `data/` | GGUF header reader; hybrid-aware memory model (mean error 0.21 GB over 5 models); router simulation (single 9b 0.832 / 582 s; single 4b 0.829 / 275 s; overfit tables; cascade 4b → 9b 0.879 / 327 s, an upper bound) |
| Gold sets + evaluators (benchmark sources, from the handoff notes) | M2 `tests/doc_intel/eval/` (F1) · M3 `tests/planning/eval/run_eval.py` (validity) · M4 `samples/refine/taxonomy_gold.jsonl` + `taxonomy_eval.py` (classify) · M5 `samples/research/gold/questions.jsonl` + `tests/research/eval/run_eval.py` (fact coverage, citations) · M6 `samples/verify/benchmark.jsonl` + `tests/verify/eval/run_eval.py` (detection) · M7 `tests/coding/eval/run_eval.py` (pass@1) + `samples/coding/trajectories/` · M8 testing eval · M9 docgen eval · M10 `samples/review/calibration/` + `tests/review/eval/run_eval.py --judge` (κ, probe flips) | each has `--mode live --local-only` (never records); flags and outputs differ per member (T8) |
| Recordings (fine-tune / classify data) | `samples/llm_cache/` (25 MB) | ~1,940 recorded calls: verify judge 406, research reasoner 225, docgen reasoner 180, review judge 165, **refine classify 147**, coding coder 95, research embed 277, … Almost all are **cloud** answers (Groq / Gemini) |
| Demo / release commands | `Makefile` (`demo`, `demo-replay`, `demo-final`, `reset-demo`, `report`, `stop`), `scripts/demo.sh` (starts Ollama with `OLLAMA_MODELS` + `MAX_LOADED_MODELS=2`), `scripts/demo_preflight.py` (checks Ollama + pulled models), `scripts/make_handoff.sh`, `scripts/doctor.sh`, `scripts/demo_chaos.sh` (M4), `infra/observability/load/soak.py` (M4) | done. No `pull_models.sh`, no warm-up, no `make_handoff.sh final` mode (it takes any label: `final` already works as a name) |
| Laptop | Mac15,12 (M3), 16 GB, Ollama 0.35.1, models on `/Volumes/Tirth_SSD/ollama` (qwen3.5 9b + 4b, qwen3, qwen2.5-coder, llama3.1, gemma4, nomic-embed-text), 130 GB free on the SSD. **3.1 GB of swap in use** right now (T5). `mlx-lm` not in the backend env (the uv script brings it) | |
| Ownership | `ownership.toml [members.11]` | plugin `models`: `agents/models/**`, `tests/models/**`, `frontend/src/features/models/**`, `docs/members/11/**`, `samples/models/**`, `samples/llm_cache/models/**`, `alembic/versions/011_*` |

## 0b. Traps found while reading the code

| # | Trap | Consequence for the plan |
|---|---|---|
| T1 | **The `llm_provider` slot is declared but nothing reads it.** This is the same as the `recovery` slot before Sprint 10. The gateway is built by `build_llm(settings)` with no plug-ins, and agents get it through `for_plugin` | a router plug-in would do nothing → **Q1**: Member 1 wires the slot (a `RouteStrategy` protocol in `core/plugins.py`, one call in the gateway, the plug-in list passed to `build_llm`) |
| T2 | The replay cache key **ignores the model**: the same prompt replays the same answer whichever model the router picks | router on / off are identical in `fake` and `replay` (good for the matrix: the escape hatch is free), but the router's effect is visible **only live**. The benchmark cannot use the normal cache: it records per model under `samples/llm_cache/models/<model-slug>/` (its own `ReplayCache` root) |
| T3 | The gateway is built in two places: `system.py` (one process) and `host.make_llm` (agents in their own process, `DEMO_SPLIT=1`) | both must attach the router, or split mode silently runs without it. A test runs the split demo with `HMAP_ROUTER=on` and checks that decisions appear |
| T4 | Ollama is usually **off** (Member 1 does not use local models; the team rule: stop it after use) | the registry, hardware page and router must work with Ollama down: the registry falls back to its last sync + `samples/models/data/model_specs.json` and says "Ollama not running"; the router never routes to a model that is not installed / not reachable |
| T5 | **3.1 GB swap in use** now. The bake-off speeds were taken under swap, and the LoRA trial died with a Metal out-of-memory error | speed numbers and LoRA need a **restarted laptop with other apps closed** (Q6, personal step). Until then speeds are marked "under swap" in every table |
| T6 | `mlx-lm` is Apple-only and heavy; it is not (and should not be) a backend dependency | training / MLX serving run through `uv run --with mlx-lm` (as `finetune_trial.py` does). The code in `agents/models/finetune/` imports MLX lazily; tests use a fake trainer |
| T7 | The key pool tries routes in a **fixed** order: every reasoner call hits Gemini 3.6 Flash first even when its keys are all cooling. With one model for every role (single tier) the pool saturates (Sprint 10: ~180 rate-limited calls) | the router's measurable job: reorder / skip routes using the pool's live state (cooldowns, recent 429s), the prompt size vs each model's request limit, and a per-model request budget. Needs a `routes=` override on `CloudRouter.chat` (part of Q1) |
| T8 | Each member's eval CLI has its own flags, cache, output and runtime (local coding ~136 s per task; local research found nothing) | `bench/sets.py` = one adapter per gold set (how to run it with a given role map, where the score is); local runs get a **time budget** and subset sizes; anything not run is reported as "not run", never as a number |
| T9 | Heavy local calls are serialised by one gateway semaphore (`llm_max_concurrency=1`); `OLLAMA_MAX_LOADED_MODELS=2` (embedder + one heavy model) is set only in `demo.sh` | the scheduler (11.4) takes this over: per-model queues, priority, and a swap-aware choice ("the resident model, unless the task needs another"). The plain gateway path (router off) is unchanged |
| T10 | Ollama's `ADAPTER` supports only some architectures; `qwen35` (hybrid attention / state-space) may not be one of them | verify first (11.12); fallback = `mlx_lm.server` with `--adapter-path` behind the same provider interface |
| T11 | Every local model on disk is Q4_K_M; another variant would be a ~5 GB **download** | ask first (Q4); the study compares the installed sizes |
| T12 | The spec names `HMAP_MODEL_ROLES`; the code has `HMAP_ROLE_MAP` | **one** map: `HMAP_MODEL_ROLES` is accepted as an alias of `HMAP_ROLE_MAP` (documented), no second source of truth |
| T13 | Any new setting breaks Member 9's configuration-reference drift test until `python -m hmap.agents.docgen.config_reference` is re-run | re-run it in the build (as in Sprint 10) |
| T14 | The clean-copy run (11.21) wipes `./data` + the DB. Team rule: never reset Member 1's real `hmap` DB without asking | the clean copy uses its **own** database name (`hmap_release`) in the same Postgres container and its own data folder. Wiping the real DB only on Member 1's explicit yes (Q9) |
| T15 | Recordings contain the **evaluation** sets' own prompts (e.g. verify judge calls on `benchmark.jsonl`, docgen on its eval projects) | the dataset builder drops every example whose input overlaps an evaluation item (hash + near-duplicate check), splits by source item (not by sample), and logs what it dropped |
| T16 | `check_sprint.sh 11` must pass with the router **on and off** (DoD) | `check_sprint.sh` stays as it is. The matrix script runs precommit twice (`HMAP_ROUTER=off`, `=on`); the Sprint 11 demo runs both |
| T17 | Docker / Colima and Ollama are stopped between sessions | each step that needs them starts them and stops them after (team rule) |
| T18 | The spec's router input includes the task's capability and context size (spec §2 "Manager task metadata"), but the gateway only knows the plug-in a client is bound to (`for_plugin`) and the messages | task type = the plug-in name (one plug-in ≈ one capability family); context size = estimated from the messages + `max_tokens`. When an agent serves several capabilities (e.g. `docs.generate` / `docs.update`) the router cannot tell them apart: stated as a limit, not worked around in agent code |

## 1. Decisions

| # | Decision | Item |
|---|---|---|
| D1 | **Registry** `registry.py`: `ModelSpec` rows in Postgres (`model_registry`, migration `011_sprint_11_models`) + an in-memory store for tests / Tier 0. Sources: `ollama list` + `/api/show` (digest, quant, ctx, family, params), the GGUF header (`gguf_meta.py` moved into the package) for layers / KV heads, the cloud routes of `HMAP_CLOUD_ROLE_MAP` (backend `cloud`, `status` from the key pool: keys present or not), and MLX / llama.cpp servers that answer. `roles_ok` = the roles the benchmark found the model fit for (or the role map's roles until benchmarked). Extra columns outside the contract (digest, last_seen, source, `pinned`) live in the table, not in `ModelSpec`. CRUD: list / get / sync / disable / pin | 11.1, 11.24 |
| D2 | **Hardware profiler** `hardware.py` = the prototype `memory.py` (weights + hybrid-aware KV cache × context) + live state: total / free RAM (`vm_stat`, `sysctl`), swap in use, the GPU (Metal = unified memory on Apple; CUDA via `nvidia-smi` when present, for teammates' machines), Docker / Colima VM size, models resident (`/api/ps`). `feasible(model, ctx)` → fits / fits-alone / does-not-fit + why. **Predictions vs measured**: `/api/ps` at 2–3 context lengths for the Qwen 3.5 models (closes the prototype's open 4b gap: fixed overhead vs per-token) | 11.2 |
| D3 | **Backends** `backends/`: one `Backend` interface (`name`, `kind`, `health()`, `models()`, `chat(ChatRequest)`, `embed()` where supported). `ollama` (wraps the existing `OllamaProvider`), `mlx` (`mlx_lm.server`, via `OpenAICompatProvider` at `HMAP_MLX_BASE_URL`), `llamacpp` (`llama-server`, same client at `HMAP_LLAMACPP_BASE_URL`), `cloud` (the Sprint-1 `CloudRouter`, unchanged: per-key cooldown, local fallback, the `cloud_ok` flag still a hard "no"). Health checks are cached for 10 s. "Same request works across backends" = one contract test that sends the same `ChatRequest` (with a JSON schema) to each backend that is up (fake servers in CI) | 11.3 |
| D4 | **Scheduler** `scheduler.py`: wraps the local backends only (cloud has its own pool). Per-model queues, priority by role (interactive `fast` / `classify` > `reasoner` / `judge` > `coder` batch), a concurrency limit from free RAM (1 heavy model at a time on 16 GB), **swap-aware**: prefer the resident model; group queued calls by model before switching; the embedder + one heavy model resident (`keep_alive` + the old `OLLAMA_MAX_LOADED_MODELS=2` guard). Admission control: a call whose model does not fit is rerouted (router) or refused with a clear error, never loaded into an out-of-memory crash. "No OOM under mixed load" = a test with a fake backend that tracks resident memory + a short live check with 4b + 9b + embed | 11.4 |
| D5 | **Benchmark harness** `bench/`: `sets.py` (one adapter per gold set: M2 F1 extraction → `reasoner`; M3 validity → `reasoner`; M4 taxonomy → `classify`; M5 fact coverage → `reasoner`; M6 detection → `judge`; M7 pass@1 → `coder`; M10 κ → `judge`; + the bake-off's 88 items as the quick set), `speed.py` (TTFT, generation and prefill tok/s, cold load, resident memory; fixed prompts, 3 runs, median), `run.py` (model × quant × role → `BenchmarkResult` rows in `benchmark_results` + `samples/models/bench/results/*.json`, digests pinned, seed 42, temperature 0). Cloud models are benchmarked too (they are what the platform uses); their speed column is latency / tokens, with rate-limited calls counted, not timed. Local runs have a time budget per set (default 20 min) and use subsets where a full set would take hours (stated in the table). Non-model parts replay (`HMAP_RESEARCH_MODE=cached`, recorded fetches) so only the model under test varies (spec §6). Noise: speed = median of 3; quality on the quick set repeated 3× with seeds 42 / 43 / 44 for the local models (temperature 0 still varies on Metal), and once for cloud models (quota), with the spread reported | 11.5 |
| D6 | **Model-size study** `bench/quant.py`: the two installed sizes (`qwen3.5:4b` vs `qwen3.5:9b`, both Q4_K_M) on the bake-off quick set + speed + memory → a report with a recommendation in `eval.md`. Needs the Q8 download (Q4) | 11.6 |
| D7 | **Router** `router.py` (the policy, not the API: the API module is `api.py`, see D11), behind the slot (Q1). Input: `RouteQuery{role, plugin (task type), capability, est_tokens (chars / 3.5 of the messages + max_tokens), schema?, latency budget (per role default), quality need (per role), hardware state (D2), pool state (cooldowns, recent 429s per route)}`. Policy, in order: (1) **per-task overrides** (`HMAP_ROUTE_OVERRIDES=plugin:role=model,…`); (2) **rules**: never a model that is not installed / not reachable / does not fit; a prompt longer than a route's request limit skips that route; a route whose every key is cooling goes last; `cloud_ok=false` → local only; (3) **benchmark table**: among the remaining cloud routes, order by quality for that role (from D5; ties → the cheaper / less loaded); (4) **fallback chain**: the cloud routes, then the best feasible local model (the resident one if its quality for that role is within 0.02 of the best: no swap), then the lite model when RAM is short. Output: `RouteDecision{role, model, backend, params (the chain), reason}` (one line saying which rule decided). It is logged for every call (ring buffer + `route_decisions` table, 7 days) and streamed to the UI. `HMAP_ROUTER=off` → the gateway behaves exactly as today | 11.7 |
| D8 | **Cascade** (from the prototype): `fast`-class work on the small model first, escalating to the bigger one when a self-check the platform really has fails (invalid JSON after repairs, a cyclic plan, failing acceptance tests). Implemented **inside the router for local models only** and **off by default** (`HMAP_ROUTER_CASCADE=off`). The bake-off number (+0.046 at −44 % time) is an upper bound (the escalation signal there was the grading tests); measured here with the agents' own checks | 11.7, stretch |
| D9 | **Gateway integration** `plugin.py`: `PLUGIN = Plugin(name="models", router=api_router, provides={"llm_provider": ModelRouter}, priority=100)`. With `HMAP_ROUTER=off` (or the plug-in disabled) the slot answers "no opinion" and the gateway uses the role maps; agent code unchanged (they ask for roles) | 11.8 |
| D10 | **Fine-tune** `finetune/`: `data.py` (from the record cache: keep answers that passed their validator (schema-valid, parsed) and, where the platform had a downstream truth, agreed with it; dedupe by prompt hash; drop anything overlapping an eval set (T15); split train / val / test **by source item**; target ≥ 200 clean training examples, the real count reported, and below 100 the experiment switches to the fallback skill), `train.py` (MLX-LM LoRA on `mlx-community/Qwen3.5-4B-MLX-4bit` (4-bit base = QLoRA-style; the spec's 16 GB limit is ~1–3B at full precision), rank 8, 4–8 layers, max seq 1536, the run's config + loss curve saved; if it still runs out of memory after the restart: fewer layers / shorter sequences, then a smaller model of the same family in MLX form, which is a download and asks first), `eval.py` (base vs base + LoRA on the held-out set **and** a regression check on unrelated bake-off tasks), `serve.py` (the adapter through Ollama `ADAPTER` if `qwen35` is supported, else `mlx_lm.server --adapter-path`, registered as a `ModelSpec` with backend `mlx`). **Skill (Q5): the M6 verify judge** ("does this quote support this claim?"). It has the most recorded examples (406 judge calls, cloud answers = a distillation target), a gold set the platform already scores (`samples/verify/benchmark.jsonl`, never trained on), and a measurable label. Fallback: the coding trial data (42 examples) | 11.9–11.12 |
| D11 | **API + UI**: `api.py` mounted at `/api/models`: `GET /models` (registry + resident + memory + tok/s), `POST /models/sync`, `POST /models/pull` (**the helper prints / starts `ollama pull <name>` only for names already in the registry's "available" list, owner only**), `GET /hardware`, `GET /routes` (recent decisions, filter by role / plug-in), `WS /routes/stream`, `GET /bench` (tables), `GET /bench/{set}`, `GET /finetune` (runs + results). Frontend `features/models/` (auto-registered tab "Models"): installed / resident / memory bars, route decisions stream, benchmark tables + bar charts (no new npm dependency; SVG), the quant study, the fine-tune result. Read-only for non-owners | 11.13 |
| D12 | **Sizing** `docs/members/11/sizing.md`: from **measured** numbers (D2, 11.17), the recommended tier / config for the 16 GB presenter laptop with the demo stack running, and for 8 GB teammates (Tier 0 replay, or the model host), plus the research's 24 and 48 GB rows (computed, marked "not measured") | 11.14 |
| D13 | Settings (all in `core/config.py` + `.env.example`): `HMAP_ROUTER` (`on`/`off`, default after the eval, Q2), `HMAP_ROUTER_CASCADE` (off), `HMAP_ROUTE_OVERRIDES`, `HMAP_MODEL_ROLES` (alias of `HMAP_ROLE_MAP`, T12), `HMAP_MLX_BASE_URL`, `HMAP_LLAMACPP_BASE_URL`, `HMAP_MODEL_TIER` (`0`/`lite`/`1`/`2`), `HMAP_WARMUP` (on), `HMAP_ROUTE_LOG_DAYS` (7) | 11.8 |

### Platform work (5b: model setup + the release gate, items 11.16–11.24)

| # | Decision | Item |
|---|---|---|
| P1 | **Model tiers** `scripts/pull_models.sh --tier 0|lite|1|2`: 0 pulls nothing (prints the replay setup); lite = `qwen3.5:4b` + `nomic-embed-text`; 1 = `qwen3.5:9b` + embed; 2 = 1 + 4b. It honours `OLLAMA_MODELS` (external disk) and refuses when the disk is short. It writes the matching `HMAP_ROLE_MAP` (role aliasing) as a line to paste, never into `.env` itself. **Model-host mode**: `OLLAMA_HOST=0.0.0.0` on the host, `OLLAMA_BASE_URL=http://<host>:11434` on the others. Documented + a pre-flight check that the remote host answers and has the models (no second machine to test end to end: stated) | 11.16 |
| P2 | **Presenter laptop**: `make demo` with Tier 1 and with lite. Peak RAM (demo stack + model) measured with a sampler (`hardware.py --watch`, 1 s) during one golden scenario; the tier picked and written in `sizing.md`; `make demo-replay` (replay fallback) re-checked | 11.17 |
| P3 | **Warm-up**: on `make demo` start (live, Ollama up) one tiny call per chat model in the role map + one embed (`keep_alive` 30 m), in the background; the first real call's latency is measured with and without warm-up | 11.18 |
| P4 | **Regression matrix** `scripts/release_matrix.sh` (+ `.py`): every sprint's tests (`precommit`) × `HMAP_ROUTER` {off, on} in fake mode; the golden scenarios (`demo_final.sh`) × {off, on} in replay; a **live smoke** (`make cloud-check` + one golden scenario live, cloud) × {off, on}; tier 1 (Ollama, `qwen3.5:9b`, one short scenario: extraction + plan) × {off, on}. Tier 0 = the replay rows. Output: a table in `docs/members/11/release.md`; any red cell names the failing test | 11.19 |
| P5 | **Chaos + soak**: `scripts/demo_chaos.sh` (M4) re-run on the full stack with broker down, DB down, Ollama down and agent kills, with the router on; `infra/observability/load/soak.py` for 15 min; recovery checked by the events (no stuck projects, no lost tasks) | 11.20 |
| P6 | **Clean-copy run**: `scripts/make_handoff.sh final` → a fresh folder → `scripts/doctor.sh` → `make demo` against an empty `hmap_release` DB + empty data folder (T14) → the release checklist (doc 02 §3.5), including **"the same demo passes with no cloud keys"** (all roles local) and **`make reset-demo` + `make demo-replay` with Ollama stopped and Wi-Fi off**. Results → `release.md` | 11.21 |
| P7 | **Rehearsals**: offline ×1 (replay + cached research) by the build; live ×3 on Member 1's laptop and the **video backup**: personal (Member 1 / 11) | 11.22 |
| P8 | **Slides pack**: `make report` output + a `docs/members/11/slides.md` skeleton with one 60-second slide per member (each member fills their own); Member 11 compiles | 11.23 |
| P9 | **Freeze**: registry rows pinned (`pinned=true`, digest recorded) for every model the demo uses; the pinned set written to `docs/members/11/release.md`; `scripts/make_handoff.sh final`; a runbook `docs/members/11/runbook.md` (start, stop, reset, what to do if X fails) | 11.24 |

### Open questions for Member 1 (defaults taken when the build starts)

| # | Question | Default |
|---|---|---|
| Q1 | The `llm_provider` slot is not read (T1). May Member 1's code get the small wiring? (a) `RouteStrategy` protocol + `NoRouting` in `core/plugins.py`; (b) `Gateway(route=…)`, and `_complete` / `_dispatch` asks `route.decide(query)` → `RoutePlan{cloud_routes?, local_model?, local_backend?, reason}` and reports the outcome back (`route.observe`); (c) `CloudRouter.chat(request, routes=…)` takes an optional route list; (d) `system.py` / `host.make_llm` pass the discovered plug-ins' slot to `build_llm`. About 60 lines + tests, no behaviour change when the slot is empty | **yes** (as Q1 of Sprint 10) |
| Q2 | Router default once it is evaluated | **`HMAP_ROUTER=on` only if** the live comparison (§3) shows no worse outcome and fewer rate-limited / fallback calls; otherwise ship `off` and say why |
| Q3 | Local-model work, given the team will not use local models in the demo | **do the spec's local items at reduced size**: registry, hardware, size study, LoRA, sizing; local benchmark runs on subsets with a time budget. The cloud models get the full benchmark |
| Q4 | May the build **download** another local model variant (~5 GB) for the study? | **no** (Member 1, 2026-11-02: the team runs cloud-first; the study uses the installed models) |
| Q5 | LoRA target skill | **the M6 verify judge** (D10); fallback the coding trial data |
| Q6 | **Restart the laptop** (other apps closed) before the speed re-run and the LoRA training (T5) | **yes, Member 1 restarts when the build reaches step 9**; until then speeds are labelled "under swap" |
| Q7 | Backends that need software installed: `mlx-lm` (PyPI, via `uv run --with`, no system change) and `llama.cpp` (`brew install llama.cpp`) | **MLX yes (via uv)**; llama.cpp: interface + fake-server tests only, the real server not installed (first item in the spec's cut order) |
| Q8 | Laya `classify` experiment (§5c, optional) | **cut** (first in the spec's cut order; it needs a new package + Hugging Face weights, and it scores below the majority baseline zero-shot). The data collection (11.L1) is kept as a table of the 147 + 29 recorded classify calls, so it can be picked up later |
| Q9 | The clean-copy run wipes a DB and a data folder (T14) | **its own DB `hmap_release` + its own folder**; the real `hmap` DB is never touched |
| Q10 | Router decisions table: keep every call? | **yes, 7 days** (~200 rows per golden run); no prompt or answer text, only role / plug-in / model / reason / outcome / latency / tokens |
| Q11 | The "pull model" helper in the UI | **show the command + start `ollama pull` only for models in the tier list, owner only**; never arbitrary names |
| Q12 | Paths outside Member 11's folders (§4) | **approved as listed**, reported by the ownership check for sign-off |

## 2. Step-by-step build

1. **Member 1's wiring (Q1)**: `RouteStrategy` / `NoRouting` (`core/plugins.py`), the gateway's `route=` hook (query → plan → observe), `CloudRouter.chat(routes=)`, slot resolution in `system.py` and `host.make_llm`. Tests in `tests/core/llm/` (empty slot = today's behaviour, byte for byte, in all four modes).
2. **Package skeleton** `agents/models/` (`plugin.py`, `model.py` ids / extra types, `store.py` Postgres + memory), migration `011_sprint_11_models` (`model_registry`, `route_decisions`, `benchmark_results`, `finetune_runs`), settings (D13), `.env.example`, the regenerated configuration reference (T13).
3. **Registry + hardware** (D1, D2): `ollama list` / `/api/show` / `/api/ps` sync, GGUF reader, cloud routes, MLX / llama.cpp discovery; `hardware.py` with the memory model and live state. Tests with recorded Ollama JSON (no Ollama needed). Live: sync once with Ollama up, prediction vs `/api/ps` at 3 context lengths for 4b and 9b.
4. **Backends** (D3): interface, ollama / mlx / llamacpp / cloud, health; the cross-backend contract test (fake OpenAI-compatible server + fake Ollama).
5. **Scheduler** (D4): queues, priority, swap awareness, admission; fake-backend memory test ("no OOM"); live mixed-load check (4b + 9b + embed) once.
6. **Router** (D7, D9): rules, overrides, benchmark table (seeded from the bake-off + whatever step 7 has), fallback chain, pool-aware ordering (T7), decision log + stream. Unit tests for every rule; gateway tests router on / off; split-mode test (T3).
7. **Benchmark harness** (D5): set adapters, speed, runner, results table. Runs: cloud models on every gold set that has a live mode (team keys, paced for the rate limits); local 9b / 4b on the quick set + subsets within the budget. Results → `samples/models/bench/results/`, `eval.md` §2.
8. **Model-size study** (D6): quick set + speed + memory for the 4b and the 9b → `eval.md` §3 with a recommendation.
9. **(Restart, Q6)** speed re-run on a clean machine (bake-off `speed` + the harness) → replaces the "under swap" speeds; sizing measurements (P2).
10. **Fine-tune** (D10): dataset (verify judge, contamination filter, split by item, the count reported), LoRA train (MLX, Ollama stopped), eval base vs LoRA on held-out + regression, serving path verified (Ollama `ADAPTER` or the MLX server) + registry entry. Honest result in `eval.md` §5, also when it is null.
11. **API + UI** (D11): routes, WS stream, the Models tab with tests; browser check.
12. **Router evaluation** (§3 target): (a) the prototype simulation re-run with the real router code on the bake-off results; (b) **live, cloud**: the three golden scenarios with the router off vs on (team keys, same day, alternating) — outcome, wall time, calls answered, rate-limited, local fallbacks; (c) the single-model tier with the router choosing the local fallback model vs today. Decide Q2.
13. **Model setup** (P1–P3): `pull_models.sh`, model-host doc + pre-flight check, warm-up in `demo.sh`, peak-RAM measurement, `sizing.md`.
14. **Demo** `scripts/demo_sprint_11.{sh,py}`: live route decisions (fake backends in CI, real when keys / Ollama are there) + the benchmark dashboard data through the API; runs with the router on and off.
15. **Release gate** (P4–P6, P8, P9): `release_matrix.sh`, chaos + soak, the clean-copy run (`hmap_release`), the offline rehearsal, `slides.md` skeleton + `make report`, the runbook, the freeze (pin digests, `make_handoff.sh final`). `release.md` with every result.
16. **Tests** (11.15) `tests/models/`: registry (sync from recorded Ollama JSON, CRUD, pin), hardware (memory model vs the snapshot, feasibility), backends (fake servers, same request on each), scheduler (priority, swap grouping, admission, no-OOM), router (every rule, overrides, fallback chain, pool-aware order, `off` = today, split mode), harness (FakeLLM + one tiny set, the results rows), dataset builder (validator filter, dedupe, contamination drop, split by item), fine-tune eval (fake trainer), API (owner-only, stream). Real-model tests are marked `slow` and skip when Ollama / keys / MLX are absent. Plus the step-1 gateway tests (Member 1's).
17. **Docs**: `docs/members/11/{README,design,eval,sizing,release,runbook,slides}.md`, `core-requests.md`, the handoff notes, the README "real vs stub" / status line, `docs/README.md`.
18. **Acceptance**: `scripts/check_sprint.sh 11` with `HMAP_ROUTER=off` and `=on` (also split mode), stop Docker / Colima / Ollama / MLX, then the zip + `COMMIT_GUIDE.md` in `/Volumes/Tirth_SSD/Member 11/`.

### Stretch (after the MUST items are green; in the spec's cut order)
- Learned / cascade router (D8 switched on in the evaluation as a third arm).
- Embedding-model comparison (`nomic-embed-text` vs one other) on the M5 retrieval set.
- Continuous benchmark job (`make bench` re-runs the quick set and appends rows).
- Not planned (stated in `eval.md`): Laya (Q8), speculative decoding, prompt compression, QLoRA 7B (does not fit next to the stack on 16 GB).

## 3. Targets (Definition of Done)

| Target | How it is shown |
|---|---|
| Router active and **measurably evaluated** vs the single-model / today's config | `eval.md` §4: simulation + live cloud golden runs off vs on (+ single-model tier); "beats it on quality-per-latency or says honestly it doesn't" |
| Benchmark table covers **≥ 3 models / quants over ≥ 4 role tasks** | `eval.md` §2 + `/api/models/bench`: at least Groq Qwen 3.8 27B, gpt-oss-120b, Gemini 3.6 Flash, local 9b, local 4b × extraction, planning, classify, verify judge, review judge, coding |
| Model-size study with a recommendation | `eval.md` §3 |
| LoRA experiment finished with a held-out comparison | `eval.md` §5 (null result allowed, reported as such) |
| Predictions vs measured memory | `eval.md` §1 |
| No OOM under mixed load | scheduler tests + one live check |
| Tests (11.15) green, real-model tests marked `slow` | `tests/models/` in every pre-commit |
| Dataset ≥ N clean examples (11.9) | the builder's report: ≥ 200 target, real count stated |
| All earlier tests green with the router **on and off** | `check_sprint.sh 11` ×2 (+ split mode) |
| `demo_sprint_11.sh`: live route decisions + benchmark dashboard | the demo + browser check |
| Release checklist (doc 02 §3.5) executed | `release.md`; **signed off by Member 1 and Member 9** (personal) |
| Every model tier boots and passes a smoke test | `pull_models.sh` tiers 0 / lite / 1 / 2 (2 = 1 + 4b) |

## 3b. Handed to the release gate / whole team (spec §7)
Router decisions via API / WS; the model registry + benchmark tables; `sizing.md`; the fallback chains; config
`HMAP_ROUTER=on|off`, `HMAP_MODEL_ROLES` (= `HMAP_ROLE_MAP`), `HMAP_ROUTE_OVERRIDES`; the adapter registered (if it is
worth serving); `release.md`, `runbook.md`, the pinned model set.

## 4. Paths outside Member 11's folders (need Member 1 sign-off, Q12)
- **Member 1's code (Q1)**: `core/plugins.py`, `core/llm/gateway.py`, `core/llm/cloud.py`, `core/llm/__init__.py`, `system.py`, `core/runtime/host.py` + their tests (`tests/core/llm/`, `tests/core/runtime/`).
- Settings: `core/config.py`, `.env.example`, the regenerated `docs/members/9/platform/configuration.md`.
- Scripts: `scripts/pull_models.sh`, `scripts/demo.sh` (warm-up, tier), `scripts/demo_preflight.py` (model host, tier), `scripts/demo_sprint_11.{sh,py}`, `scripts/release_matrix.{sh,py}`, `scripts/make_handoff.py` (only if `final` needs anything extra), `Makefile` (`models-pull`, `bench`, `release-matrix`).
- `README.md` (real-vs-stub / status line, model tiers), `docs/README.md` (link), `HANDOFF.md` (Sprint 11 section), `ownership.toml` (`[cross_cutting] 11`), `frontend/src/features/_registry.generated.ts` (regenerated).

## 5. What Member 11 (and Member 1) must do personally (cannot be done by the build)
- Answer Q1–Q12 (or take the defaults).
- **Restart the laptop** with other apps closed before step 9 (speed + LoRA).
- Paste / check team keys in `.env` (never in a file the build writes).
- **Live rehearsals ×3 on Member 1's laptop** and the **video backup** of a full run (11.22).
- Collect each member's 60-second slide and compile the final slides (11.23).
- Execute and **sign off the release checklist with Member 1 and Member 9** (DoD addition).
- Optional: repeat the clean-copy run on a teammate's laptop as a backup demo machine.
- Commit the sprint (the build never commits).

## 6. Not Member 11's work
- Changing the team's cloud-first decision or the default cloud routes' *policy* (the router only orders / skips routes inside it, and `HMAP_ROUTER=off` restores today exactly).
- Agents' prompts and logic (they keep asking for roles); other members' gold sets and evaluators (used as they are; a broken one is reported to its owner).
- Member 8's per-test requirement ids (Sprint 10 defect 7), Member 1's `StateChip` wording (defect 24), Member 5's corpus coverage (defect 16).
- Any deployment (doc 02 §3: everything runs on Member 1's laptop).
