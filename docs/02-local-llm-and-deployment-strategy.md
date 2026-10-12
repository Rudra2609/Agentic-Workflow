# 02 — Local LLM Development & Demo-Run Strategy

## 1. Principle

Develop against **roles**, run on **whatever the machine can host**, and make the demo **deterministic**.

## 2. Local LLM — how we develop

### 2.1 Runtime
- **Ollama on the host machine** (not in Docker). Docker Desktop/Colima on macOS cannot pass the Apple GPU (Metal) to containers; containerized inference would be CPU-only and slow. Containers reach Ollama at `http://host.docker.internal:11434`.
- Env: `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=10m` for 16 GB machines. Two slots so the small embedding model (<1 GB) stays resident **next to** the 7–8B chat model; with `1`, every embedding call (Sprints 5–7) would evict the chat model and cost a 10–30 s reload.
  - Guard: on a machine holding **two** 7–8B models (Tier 2), the gateway unloads the previous heavy model (request with `keep_alive: 0`) when it switches heavy models, so at most one heavy model + the embedder are resident. Sprint 11's scheduler takes this over.
- **Thinking off by default.** Qwen 3 (and other hybrid-reasoning models) think out loud unless told not to. The gateway sends Ollama's `think: false` on every call; an agent can opt in per call (`think=True`) where reasoning measurably helps. Thinking on would slow every call and can break `format`-constrained JSON. Requires a recent Ollama (the `think` field); `scripts/doctor.sh` checks the version.

### 2.2 Model roles — DECIDED by the pre-Sprint-2 bake-off (results: `docs/members/11/model-choice.md`)

| Role | Used by | Model | Loaded RAM |
|---|---|---|---|
| `reasoner` | extraction, planning, research synthesis, review | **`qwen3.5:9b`** | 5.8 GB |
| `judge` | M6 verification, M10 judge | **`qwen3.5:9b`** with a separate judge prompt (no other-family model passed: `llama3.1:8b` caught 0/7 planted mistakes; `gemma4:12b` does not fit the demo RAM) | shared |
| `coder` | M7 / M8 | **`qwen3.5:9b`** (best coding: 68 % of tasks pass; the `qwen2.5-coder:7b` specialist scored 28 %) | shared |
| `fast`, `classify` | routing, short critiques, typed decisions | **`qwen3.5:9b`** (one resident model = no swap delays); Sprint 11 may move these to `qwen3.5:4b` or Laya | shared |

When team cloud keys are configured (§2.5), every chat role (`reasoner`, `coder`, `judge`, `fast`, `classify`) tries a
cloud model first and falls back to the local row above; `embed` always stays local. With no keys, this table is the
whole story.
| `embed` | M5 retrieval, M7 repo search | `nomic-embed-text` | <1 GB |

Constraint: **only one 7–9B model resident at a time** on 16 GB (plus the embedder, see §2.1). With every role on one
model there is no model-swap latency; anyone who maps roles to different heavy models pays 10–30 s per switch. The
gateway serializes heavy calls (Sprint 1 semaphore; Sprint 11 scheduler).

### 2.2b Storage-aware model tiers (most members have 16 GB RAM but little free disk)

On-disk sizes (from `ollama list`): `qwen3.5:9b` 6.6 GB · `qwen3.5:4b` 3.3 GB · `nomic-embed-text` 0.3 GB.

| Tier | Contents | Disk | Who |
|---|---|---|---|
| **0 — no model** | none; `HMAP_LLM_MODE=replay/fake` from the shared `samples/llm_cache/` | **0 GB** | anyone with no spare disk; all unit/integration tests and most development |
| **lite** | **`qwen3.5:4b`** + `nomic-embed-text` (all roles aliased to it) — quality 0.827 vs 0.833, weaker only at coding | **~3.6 GB** | low RAM/disk; fine for Members 2–6 |
| **1 — default (demo)** | **`qwen3.5:9b`** for every chat role + `nomic-embed-text` | **~6.9 GB** | everyone who wants live runs; the demo laptop |
| **2 — comparison set** | Tier 1 + `qwen3.5:4b` (+ any model Sprint 11 benchmarks) | ~10 GB+ | one shared "model host" machine only (Sprint 11 benchmarks/routing) |

How this works without changing agent code:
1. **Role aliasing**: `HMAP_ROLE_MAP=reasoner=qwen3.5:9b,judge=qwen3.5:9b,coder=qwen3.5:9b,fast=qwen3.5:9b,classify=qwen3.5:9b,embed=nomic-embed-text` (Sprint 1 gateway supports it; Sprint 11 router honours it and only routes to models that are actually installed).
2. **Model host (development convenience for low-disk teammates; not used in the demo)**: the one machine with Tier 2 runs `OLLAMA_HOST=0.0.0.0`; others set `OLLAMA_BASE_URL=http://<host>:11434` on the same network. No local models needed; they just need the network.
3. **Models on an external disk**: `OLLAMA_MODELS=/Volumes/<disk>/ollama` keeps ~/ free.
4. **Handoff folders never contain models** (already excluded by `make_handoff.sh`); `samples/llm_cache/` is small and shipped so Tier 0 works immediately.
5. **Pull only what your sprint needs** — e.g., M2/M3/M4 need only the reasoner; M5 adds `embed`; M7 is the only member who *benefits* from a dedicated coder model, and Tier 1 still works.

Honest caveats: (a) on Tier 0/1 the "judge ≠ producer model" independence (Sprints 6 and 10) is weakened — mitigated by a different prompt/temperature and by running the independence benchmark on the model host; (b) Tier 1 means one model serves everything, so quality differences between roles show up mainly in Sprint 11's benchmarks, which run on the model host; (c) LoRA fine-tuning (Sprint 11) also happens on the model host only.

### 2.3 Known weaknesses of 7–8B local models — and the countermeasures baked into the plan
| Weakness | Countermeasure |
|---|---|
| Unreliable JSON | JSON-Schema-constrained decoding (`format`) + Pydantic validation + ≤2 repair retries (Sprint 1 helper) |
| Short effective context | Map-reduce chunking (M2), hierarchical summaries (M9), repo maps (M7), per-agent trimming of the pinned context (M1 `context.resolve_view` is Sprint-1 stretch) |
| Weak self-critique | Programmatic checks first, LLM critic second; separate critic prompt/model (M4) |
| Hallucinated citations | Deterministic quote-in-source verification (M5/M6), not LLM trust |
| Slow | Cache + record/replay (below); small models for easy tasks (M11) |
| Non-determinism in demos | temperature 0–0.2, seed, **record/replay cache** |

### 2.4 Three LLM modes (Sprint 1 builds all three)
1. **`live`** — real Ollama.
2. **`record`** — live + store every (request-hash → response) in `samples/llm_cache/` (also becomes the **fine-tuning dataset** for Sprint 11).
3. **`replay`** — answers only from cache; **zero GPU, deterministic**. Used for CI, weak laptops, and **demo day safety net**.
4. `fake` — scripted `FakeLLM` for unit tests.

Config: `HMAP_LLM_MODE=live|record|replay|fake`.

**Replay-cache layout (merge-safe):** one JSON file per request, `samples/llm_cache/<plugin>/<key[:2]>/<key>.json`, where `<plugin>` is the calling agent's plug-in name (e.g. `doc_intel`). Members only ever add files inside their own folder, so merging handoff folders never collides.

**Cache key** = SHA-256 of a canonical JSON of: plug-in name, role, the **agent-supplied** messages, the output schema (JSON Schema), and generation params (temperature, max_tokens, seed, think). It deliberately **excludes**:
- any system-prompt text the gateway injects or shares across agents (shared preamble, safety header) — so changing it does not invalidate anyone's fixtures;
- the resolved model name — so a replay recorded on the model host works on a Tier-0 laptop.

The file still stores the full request (incl. injected preamble), resolved model + digest, response, tokens, latency and a `prompt_version` an agent can bump to force re-recording. A `replay` miss raises an error that prints the key ingredients so the member can see which part changed. These files are also the Sprint 11 fine-tuning dataset.

### 2.5 Cloud providers at runtime — team key pool (decided 2026-10-11)

The **product** may send selected roles to free-tier cloud models while it runs (development and tests never need a key).
Teammates voluntarily contribute their own free-tier keys — about **10 Groq + 10 Gemini** — so the platform can call
stronger models for the roles where the local 9B model is weakest. With no keys, everything still runs locally.

**Which roles (changed 2026-10-12: local + cloud wherever it helps):** with keys present, every chat role goes to the
cloud first, then the local `qwen3.5:9b`. This is the built-in default (`DEFAULT_CLOUD_ROLE_MAP` in
`backend/src/hmap/core/config.py`), used when `HMAP_CLOUD_ROLE_MAP` is empty:

| Role | Cloud route (left to right), then local | Why this model |
|---|---|---|
| `reasoner` | `gemini:gemini-3.6-flash` → `groq:openai/gpt-oss-120b` → `gemini:gemini-3.5-flash` | Extraction, planning, research synthesis and review send long inputs (whole documents). Gemini has a large context window; Groq's free tier caps each key at 8K tokens/min, which one long prompt can exceed |
| `coder` | `groq:openai/gpt-oss-120b` → `gemini:gemini-3.6-flash` → `gemini:gemini-3.5-flash` | Strongest free coding model and about 1 s per call. Local `qwen3.5:9b` passes 71 % of our coding tasks on the first try and fails the multi-part ones |
| `judge` | `groq:qwen/qwen3.8-27b` → `gemini:gemini-3.5-flash` | A model family that neither the reasoner (Gemini) nor the coder (gpt-oss) uses, so the judge checks work it did not write. The local bake-off could not give us that (§2.2) |
| `fast`, `classify` | `groq:openai/gpt-oss-20b` → `gemini:gemini-3.5-flash-lite` | Short, frequent calls: under 1 s in the cloud versus several seconds locally. They use their own model, so they don't eat into the big models' quota |
| `embed` | always local `nomic-embed-text` | Every vector must come from the same model to stay comparable, and it is cheap locally |

Each provider limits requests per **model** and per key, which is why the roles are spread over five different models.
All routes were checked on both free tiers on 2026-10-12. `gemini-3.8-flash` and `gemini-flash-latest` were left out
because they kept answering 503 "overloaded", and the Pro models have no free quota. Model names change, so re-check
them with `make cloud-check` before a demo. To keep the keys but use fewer cloud roles, set the map yourself
(e.g. `HMAP_CLOUD_ROLE_MAP=coder=groq:openai/gpt-oss-120b`). `HMAP_CLOUD_ROLE_MAP=none` or `HMAP_CLOUD_OK=false`
keeps every role local.

**Configuration (`.env` only, never committed):**
```bash
HMAP_GROQ_API_KEYS=gsk_...,gsk_...                  # comma-separated, one per contributing teammate
HMAP_GEMINI_API_KEYS=AIza...,AIza...
HMAP_CLOUD_ROLE_MAP=                                  # empty = the default above; or role=provider:model|...; none = all local
```
Both providers expose OpenAI-compatible chat endpoints, which the gateway's cloud provider already speaks.

**Gateway behaviour (Sprint 1 Phase B, item 1.14b):**
1. A role listed in `HMAP_CLOUD_ROLE_MAP` tries its providers in order; inside a provider it rotates through that
   provider's key pool.
2. HTTP 429 / `retry-after` → that key cools down for the stated time and the next key is tried; auth errors disable a
   key until restart (a teammate may have revoked it).
3. All keys of all providers busy or failing → **fall back to the local model** for that call. A run never stops because
   the free quota ran out.
4. Every cloud call is logged with provider, model, tokens and a short **key fingerprint** (never the key), so the team
   can see quota use per contributed key.
5. `record` mode still writes the replay cache (it stores the request without headers, so no key can leak into it);
   `replay` needs no network and no keys.

**Limits and honesty notes:**
- Free-tier limits are per account/organization and per model, and they change often. On 2026-10-12, Groq reported
  1,000 requests/day and 8K tokens/min per key and model; Gemini shows its limits only in AI Studio. One full project
  run uses very roughly 250–350K tokens in total, and with every chat role in the cloud most of that goes to the key
  pool. With 10 + 10 keys that is several full runs a day before calls start falling back to the local model. That
  fallback is automatic and per call, so a run never stops, it only gets slower.
- The keys belong to the teammates who contributed them; each can revoke theirs at any time, and the risk of a provider
  limiting an account sits with its owner. The gateway must treat any key as possibly gone.
- **Privacy:** prompts for cloud roles leave the laptop; on Gemini's free tier Google may use them to improve its
  products. Uploaded assignment documents are fine; anything private must stay on local roles. A project-level
  `cloud_ok` flag (on by default) lets a user keep a project fully local: "Keep this project on this computer" when
  creating it, or More → "Keep on this computer" later (applies to steps assigned after the change). The Manager
  puts it on every `task.assign`; the agent runtime then hands the task a gateway client that can never reach a
  cloud model, so it holds for every agent that uses `ctx.llm`.
- The demo still has a safety net: `make demo-replay` (no network, no keys, no Ollama) — see §3.

## 3. Running the demo — local laptop only (no deployment)

**Decision:** the platform is **never deployed**. Every demo (mid-eval and final) runs live on **Member 1's laptop** (Apple M3, 16 GB). There is no server, no public URL, no TLS, no production images. This removes the old production-packaging, multi-target and clean-server work; what remains is making the laptop run **one command, reproducible, and safe to repeat**.

### 3.1 What runs on the laptop

```text
Member 1's laptop (macOS, 16 GB)
 ├─ Ollama (host process, Metal GPU)        127.0.0.1:11434   one 7–8B model + embedder resident
 ├─ Docker (Colima/Docker Desktop) — infra only
 │    ├─ postgres  (pgvector)               127.0.0.1:5433   volume
 │    ├─ rabbitmq  (mgmt UI)                127.0.0.1:5672 / 15672
 │    └─ (Sprint 8) sandbox containers, spawned on demand, --network=none
 │    └─ (optional, Sprint 4) obs profile: jaeger / prometheus / grafana
 └─ native processes (started by `make demo`)
      ├─ api        FastAPI + Manager        127.0.0.1:8000
      ├─ agents     ONE host process running every discovered agent (`hmap-agents run --all`)
      ├─ frontend   Next.js production build 127.0.0.1:3000
      └─ ./data/artifacts   write-once artifact files
 cloud first for every chat role when keys are set → Groq / Gemini over HTTPS (team key pool, §2.5); local fallback
```
- App code runs **natively**, not in containers: fewer moving parts and ~1–2 GB less RAM than per-service containers, which matters with an 8B model loaded.
- Everything binds to `127.0.0.1`.
- Development uses exactly the same layout (`make infra-up` + hot-reload processes), so "works in dev" = "works in the demo".

### 3.2 Compose profiles (infra only)
| Profile | Purpose |
|---|---|
| default / `dev` | postgres + rabbitmq — used for development, integration tests and the demo |
| `obs` | observability stack (Sprint 4; open during the failure-injection step if RAM allows) |

### 3.3 Demo commands (Member 9 packages them in Sprint 9)
| Command | What it does |
|---|---|
| `make demo` | pre-flight (Ollama up, model pulled, free RAM, ports) → infra up → migrations → seed → api + agent host + frontend → opens dashboard |
| `make demo-replay` | same, with `HMAP_LLM_MODE=replay` — works with Ollama stopped or Wi-Fi off; the safety net |
| `make reset-demo` | wipe DB + `./data/artifacts` back to the seeded demo state |
| `make stop` | stop everything |

**RAM plan for demo day:** close other heavy apps; the chosen tier (Sprint 11 item 11.17) must leave headroom with the demo stack running. If the laptop is under memory pressure, switch to the lite tier or `make demo-replay`.

Teammates never need to run the demo; for their own development they use Tier 0 (`replay`), lite, Tier 1, or the LAN model host (§2.2b).

### 3.4 Config & secrets
- `.env.example` committed (no secrets); `.env` ignored. Per-agent service tokens (added in Sprint 6 by Member 6) generated by `scripts/seed.sh`.
- Cloud keys (§2.5) are only in `.env`. The demo uses them for every chat role when Wi-Fi is available; without network it falls back to the local model, and `make demo-replay` needs neither.

### 3.5 Release checklist (Member 11 executes in Sprint 11 as the release gate)
Fresh copy from `make_handoff.sh final` on Member 1's laptop → `scripts/doctor.sh` green → `make demo` (migrations + seed run automatically) → demo script passes → the same demo passes with **no cloud keys** (all roles local) → `make reset-demo` then `make demo-replay` passes with Ollama stopped and Wi-Fi off → video backup recorded → runbook (start, stop, reset, what to do if X fails) written.

## 4. Fine-tuning (Member 11, Sprint 11) — realistic scope on this hardware
- Method: **LoRA via MLX-LM on Apple Silicon**, 1–3B model (7B QLoRA may fit but is slow; treat as stretch).
- Data: harvested from the `record` cache of Sprints 2–10 (prompt/response pairs that passed validation/tests), cleaned and split.
- Candidate target skill: constrained requirement extraction or the critic role — chosen because it has a measurable gold set.
- Must **report honestly** whether it beat the base model on the held-out set; a null result is acceptable and still graded as research.
- Serving the adapter via Ollama (`Modelfile` `ADAPTER` / converted GGUF) — **verify supported architectures at the time**; fall back to serving via `mlx_lm.server` behind the same provider interface.
