# Laptop sizing (item 11.14) — which model tier on which machine

Budget = RAM − macOS and apps (4.5 GB) − the demo stack (Docker infra + API + agents + dashboard, 3 GB) − 1 GB
headroom; the model gets the rest. Model memory = weights + KV cache (`hardware.py`, mean error 0.21 GB, eval.md §1).
The rows are **computed** (`uv run python -m hmap.agents.models.hardware` on any machine shows its own state and the
Models page shows "fits / fits alone / does not fit"); the 16 GB row is **measured** (below).

| Laptop RAM | Model budget | What fits next to the demo stack | Tier |
|---|---|---|---|
| 8 GB | none (−0.5 GB) | no live local model | **Tier 0**: `make demo-replay`, or the cloud keys with no local fallback, or the model host |
| 16 GB (the presenter laptop) | 7.5 GB | one model: `qwen3.5:9b` (measured 6.3 GB at 8k, 7.5 GB at 32k) or `qwen3.5:4b` (3.0 / 3.6 GB), + the embedder | **lite** (measured below); Tier 1 fits only at short context |
| 24 GB | 15.5 GB | 9b and 4b together (no swap when routing between them) | Tier 2 |
| 48 GB | 39.5 GB | every bake-off model, incl. `gemma4:12b` | Tier 2 |

## Recommendation for the presenter laptop (Member 1's, 16 GB, Apple M3)
- The demo runs on the **cloud keys** (the team's decision); the local model is only the fallback when Wi-Fi or the
  keys fail, and documents always need the local embedder.
- Fallback model: **`qwen3.5:4b` (lite)**. It is within noise of the 9b on everything but coding (eval.md §3), needs
  3.0 GB instead of 6.3 GB (measured), and is ~3.8× faster, so the laptop stays out of swap with the browser and the
  dashboard open. Keep `qwen3.5:9b` pulled for a "no keys" run of the release checklist.
- `make demo-replay` stays the offline fallback (no model, no key, no network).

## Measured on the presenter laptop (2026-11-02, Apple M3, 17.2 GB)
`make demo` live (Colima + Postgres + RabbitMQ, API, agents, the dashboard's production build) with the local
fallback loaded, used memory sampled every second (`samples/models/release/peak_ram.json`):

| State | Peak used | Left | Swap |
|---|---|---|---|
| demo + **lite** (`qwen3.5:4b` + embedder) | **13.1 GB** | 4.1 GB | no growth |
| demo + `qwen3.5:9b` (Ollama also kept the 4b loaded) | **15.5 GB** | 1.7 GB | +0.3 GB |

- Lite leaves 4 GB for the browser and the slides; the 9B leaves under 2 GB and starts swapping. **Pick lite.**
- Speed (restarted, swap 0): 4B 23.8 tok/s, first token 0.19 s; 9B 6.3 tok/s (eval.md §3).
- Warm-up (`make demo` does it in the background): the first local call takes 0.3–0.6 s instead of 8–12 s.
- Tier smoke tests (`scripts/pull_models.sh --tier 0|lite|1|2 --check`): every tier boots and answers.
- Swap built up again during the long measurement session (3+ GB): restart before the demo (runbook.md).

## 8 GB teammates and the model host
- 8 GB: Tier 0 (`HMAP_LLM_MODE=replay`, every test and most development), or the team cloud keys.
- **Model host** (development only, never the demo): the one machine with the models serves the others on the same
  network. On the host: `OLLAMA_HOST=0.0.0.0 OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama ollama serve` (this exposes
  Ollama to the local network, so only on a trusted network). On the others: `OLLAMA_BASE_URL=http://<host>:11434`
  in `.env`, then `scripts/pull_models.sh --tier 1 --model-host http://<host>:11434` checks the host has the models;
  the `make demo` pre-flight names a remote Ollama as the model host. Not tested end to end (one machine).
