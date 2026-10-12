# Sprint 11 — Member 11: Local LLMs, Fine-Tuning & Model Routing

**Owner:** Member 11 · **Needs:** Sprint 10 accepted · **Unblocks:** project completion (this sprint ends with the final release gate)
**Replaces:** internals of `core/llm` role→model mapping (agent code **unchanged** — they use roles). Lives in `agents/models/`; plugs in through the `llm_provider` plug-in strategy slot (Sprint 1 §3.5) — no edit to `core/llm`.

## 0. Prep-week task (before Sprint 2 starts) — default-model bake-off — **DONE 2026-10-10** (Member 1): `qwen3.5:9b` for all roles, `qwen3.5:4b` lite; results and re-run commands in `docs/members/11/model-choice.md`. Sprint 11 extends this harness rather than starting over.
Every member from Sprint 2 on tunes prompts against the Tier-1 model, so it must be chosen **early**, not in Sprint 11.
- Candidates: 2–4 current 7–8B instruct models that fit 16 GB at ~4-bit (e.g. Qwen 3 8B, Llama 3.1 8B, plus any newer local model released by then — check the Ollama library).
- Tiny harness (plain Ollama HTTP, no platform needed): ~10 prompts each for schema-constrained JSON extraction, task decomposition, short critique, and a code snippet; measure valid-JSON %, a quick quality check, tok/s, TTFT and RAM, with `think: false`.
- Output: `docs/members/11/model-choice.md` + the default `HMAP_ROLE_MAP` in `.env.example` (Member 1 applies it). Sprint 11 can still change routing later, but only with the regression matrix green.

## 1. Goal
Turn the thin Sprint-1 gateway into proper **local-model infrastructure**: model registry, hardware profiling, multi-backend serving, **benchmarking on the project’s own gold sets**, **routing** by task/context/latency/hardware, quantization comparison, and a measured **LoRA fine-tune** — with every decision logged and visible.

## 2. Provided
Gateway interface (roles, modes, record cache), per-call latency/token logs, gold sets & evaluators from M2/M3/M5/M6/M7/M8/M9/M10, recorded LLM traces (`samples/llm_cache/`), UI shell, Manager task metadata (capability, context size).

## 3. Research deliverable
Local inference (llama.cpp, Ollama, MLX, vLLM), quantization (GGUF Q4_K_M/Q5/Q8, AWQ/GPTQ) quality/speed/memory trade-offs, KV-cache & context-length memory cost, LoRA/QLoRA, dataset construction, specialization vs generalist, routing (rule-based, cascaded/FrugalGPT, learned routers, RouteLLM), benchmarking methodology (tok/s, TTFT, memory, task quality), hardware sizing for 8/16/24/48 GB.

## 4. Design

```text
Model Registry (Postgres): ModelSpec{id, family, params, quant, ctx, backend, mem_gb, tok_s, capabilities, roles_ok, status}
Hardware Profiler: RAM, GPU/Metal/CUDA, free memory, Docker overhead → feasible set
Backends (provider interface): Ollama | llama.cpp server | mlx_lm.server | cloud key pool (Groq + Gemini, from Sprint 1)
Scheduler: one-big-model-at-a-time on 16 GB, model swap cost aware, request queue by priority
Router: input = {role, task type, est. context tokens, latency budget, quality need, hardware state}
        policy = rules → (optional) learned from benchmark table → fallback chain (e.g. coder: cloud pool → local qwen3.5:9b; others: local first)
        output = RouteDecision{model, backend, params, reason}  (logged + shown in UI)
Benchmark Harness: runs gold sets of every earlier sprint per (model×quant) → quality score per role + speed + memory → BenchmarkResult table
Fine-tune pipeline: traces → filter (passed validators/tests) → dataset → MLX LoRA → eval vs base on held-out → publish adapter (or not)
```

## 5. Work items

### MUST
| # | Item | Files (`agents/models/`) | Acceptance |
|---|---|---|---|
| 11.1 | Model registry (tables, CRUD, `ollama list` sync), `ModelSpec` | `registry.py`, migration `011_*` | |
| 11.2 | Hardware profiler & feasibility calculator (weights + KV cache ≈ mem) | `hardware.py` | predictions vs measured |
| 11.3 | Backend providers behind one interface: Ollama (existing), llama.cpp server, **MLX server**, the Sprint-1 cloud key pool (Groq + Gemini, per-key cooldown, local fallback, `cloud_ok` flag) — the router decides per role/task when cloud is worth the quota; health checks | `backends/` | same request works across backends |
| 11.4 | Request scheduler/queue with priorities & swap-awareness; concurrency policy by RAM; takes over the Sprint-1 heavy-model unload guard (embedder + one heavy model resident, `OLLAMA_MAX_LOADED_MODELS=2`) | `scheduler.py` | no OOM under mixed load |
| 11.5 | **Benchmark harness**: speed (tok/s, TTFT), memory, and **quality via earlier gold sets** (M2 F1, M3 validity, M5 fact coverage, M6 detection, M7 pass@1, M10 judge agreement) | `bench/` | table per model×quant×role |
| 11.6 | Quantization study: ≥2 quants of the same model (e.g., Q4_K_M vs Q8) + ≥2 model sizes | `bench/quant.py` | report w/ recommendation |
| 11.7 | **Router** (rules + benchmark-driven table), fallback chain, per-task overrides, decision log | `router.py` | beats “single-model for all” on quality-per-latency or says honestly it doesn’t |
| 11.8 | Gateway integration: register `Router` in the `llm_provider` plug-in slot; `HMAP_ROUTER=off` reverts to the role→model map | `agents/models/plugin.py` | all earlier tests still green |
| 11.9 | **Dataset builder** from record cache (filter by validator pass, dedupe, split train/val/test) | `finetune/data.py` | ≥ N clean examples |
| 11.10 | **LoRA fine-tune** (MLX-LM) of a small model for one measurable skill (e.g., M2 JSON extraction or critic role) | `finetune/train.py` | training completes on 16 GB |
| 11.11 | Fine-tune eval: base vs LoRA on held-out set + regression check on unrelated tasks | `finetune/eval.py` | honest result in `eval.md` |
| 11.12 | Adapter serving path (Ollama `ADAPTER` / GGUF conversion, or MLX server) + registry entry — **verify architecture support first** | `finetune/serve.py` | |
| 11.13 | API + UI: model dashboard (installed, resident, memory, tok/s), route decisions stream, benchmark tables/charts, “pull model” helper | `agents/models/router.py` (auto-mounted), `frontend/src/features/models/` (auto-registered) | |
| 11.14 | Laptop sizing note: recommended model tier/config for the 16 GB presenter laptop (with the demo stack running) and for 8 GB teammates → feeds the release gate | `docs/members/11/sizing.md` | |
| 11.15 | Tests (router rules, scheduler, registry, harness with FakeLLM; real-model tests marked `slow`) | `tests/models/` | green |

### STRETCH
Laya `classify` experiment (§5c); learned/cascade router (cheap model first, escalate on low confidence); speculative decoding; embedding model comparison; prompt-compression; QLoRA 7B; continuous benchmark job.

## 5c. Optional experiment — Laya as a fast `classify` backend

**What Laya is** (Convai Innovations, Apache-2.0, released 18 Sep 2026 — re-check version/licence before use): a ~320–420M-parameter *non-generative* "System 1" decision model (ModernBERT/mmBERT backbone, `pip install laya`, weights on Hugging Face). Input = a short state text + typed questions (**boolean / choice / score**, each with a criteria map); output = a probability per option in one forward pass (~33 ms on a GPU/Apple Silicon, <1 GB RAM). It **cannot** write text, JSON, plans or code, so it never replaces `reasoner`/`coder`/`judge`.

**Why it may help us:** many platform decisions are short typed choices that currently cost a full 8B-model call (seconds, and a model swap if a different model is resident). Laya fits next to the 8B model in RAM.

**Honest caveats (from published benchmarks):** zero-shot it scores *below* the majority-class baseline on typed-decision tasks, degrades past ~20 options, needs per-question temperature calibration, and has a 512–1024-token context. ⇒ **only useful after fine-tuning on our own data**; short inputs only.

| # | Item | Acceptance |
|---|---|---|
| 11.L1 | Collect labelled data from the record cache: every `ctx.llm.classify` call (state, questions, LLM answer) + downstream truth where known (e.g. M8 failure category confirmed by the test, M4 issue category confirmed by a programmatic critic) | ≥ a few hundred examples per task, strict held-out split |
| 11.L2 | Fine-tune a Laya checkpoint (MLX/PyTorch on the 16 GB Mac — encoder fine-tuning is cheap) for 2–3 tasks: route choice, M8 failure category, M4 issue category | training completes; calibration fitted |
| 11.L3 | `LayaClassifier` backend registered for role `classify` (via `llm_provider` slot); per-task switch + confidence threshold → falls back to the LLM when unsure | `HMAP_CLASSIFY_BACKEND=llm|laya`; all tests green both ways |
| 11.L4 | Evaluate vs the 8B LLM on held-out data: accuracy, latency, RAM, effect on end-to-end run time | table in `eval.md`; adopt only where it is at least as accurate — a null result is fine |

Cut first if Sprint 11 overruns (it is optional; never blocks the release gate).

## 5b. Platform-wide responsibility: Laptop Model Setup & FINAL RELEASE GATE (also owned by Member 11)

Why here: "running the platform on local LLMs" is this member's subject, and this is the last sprint, so it ends the project. There is **no deployment** — the final demo runs on Member 1's laptop (doc 02 §3).

### WP-D — model setup on the presenter laptop
| # | Item | Acceptance |
|---|---|---|
| 11.16 | **Storage-aware model tiers** (doc 02 §2.2b) implemented: `scripts/pull_models.sh --tier 0|1|2|lite`, `OLLAMA_MODELS` on external disk, role aliasing, **model-host mode** (one machine serves others over LAN via `OLLAMA_BASE_URL`) | each tier boots and passes smoke test |
| 11.17 | Presenter-laptop wiring: `make demo` with Tier 1 and with lite; measure peak RAM (demo stack + model) and pick the demo tier; `replay` fallback armed | measured; chosen tier documented |
| 11.18 | Warm-up/preload on start so first request isn't 30 s | measured |

### WP-R — FINAL RELEASE GATE (whole team on call for their own subsystem)
| # | Item | Acceptance |
|---|---|---|
| 11.19 | Regression matrix: all sprint tests × `HMAP_LLM_MODE` {fake, replay, live-smoke} × `HMAP_ROUTER` {on, off} × tier {0, 1} | green |
| 11.20 | Full-stack chaos re-run (broker, DB, Ollama down; agent kills) + load/soak (reuse M4 script) | recovery proven |
| 11.21 | **Clean-copy run on Member 1's laptop**: fresh folder from `make_handoff.sh final`, wiped `./data` + DB, `make demo` → release checklist (doc 02 §3.5). Optional: repeat on a teammate's laptop as a backup demo machine | passes release checklist |
| 11.22 | Offline rehearsal (`replay` + cached research) ×1, live ×3 on Member 1's laptop; full-run **video backup** | recorded |
| 11.23 | Final slides/Q&A pack: each member contributes their own 60-second slide; M11 compiles with `make report` output | done |
| 11.24 | **Freeze**: pin model digests in the registry, `scripts/make_handoff.sh final` | snapshot made |

Cut order if the sprint overruns (never cut WP-R): Laya experiment (§5c) → 7B QLoRA → learned/cascade router → llama.cpp backend → LoRA (keep dataset builder + report).

Definition of Done addition: release checklist (doc 02 §3.5) executed and signed off by M1 and M9.

## 6. Constraints & honesty notes
- 16 GB limits fine-tuning to ~1–3B (LoRA); report negative results truthfully.
- Don’t overfit adapters to the very sets used for evaluation (strict held-out split).
- Benchmarks must be reproducible: pinned model digests, seeds, `replay` for non-model parts.

## 7. Interface handed to the release gate / whole team
```text
Router decisions exposed via API/WS; model registry + benchmark tables; sizing guide; fallback chains;
Config: HMAP_ROUTER=on|off, HMAP_MODEL_ROLES=…; adapters (if any) registered.
```

## 8. Definition of Done (additions)
- [ ] Router active and measurably evaluated vs baseline single-model config
- [ ] Benchmark table covers ≥3 models/quants over ≥4 role tasks
- [ ] LoRA experiment finished with held-out comparison reported
- [ ] Full regression (`check_sprint.sh 11`) green with Router **on** and **off**
- [ ] Demo `demo_sprint_11.sh`: live route decisions + benchmark dashboard

## 9. Risks
Swap latency dominates (RAM) → scheduler batching by model; benchmark noise → fixed seeds, multiple runs; adapter incompatibility → MLX-server fallback; routing regressions → `HMAP_ROUTER=off` escape hatch.
