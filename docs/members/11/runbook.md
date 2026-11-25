# Demo-day runbook (release gate, item 11.24)

The full platform runbook (start, stop, reset, logs) is Member 9's [platform/runbook.md](../9/platform/runbook.md)
and [troubleshooting.md](../9/platform/troubleshooting.md). This page is the one sheet for the demo itself, on
Member 1's laptop (nothing is deployed).

## Before (the day before)
1. Restart the laptop, close other heavy apps (swap must be near 0: `uv run python -m hmap.agents.models.hardware`
   in `backend/`, look at `swap_used_gb`).
2. `scripts/doctor.sh` green. `make cloud-check`: the team keys answer (it prints which).
3. `scripts/pull_models.sh --tier 1 --check`: the fallback model and
   the embedder are there.
4. `make demo-replay` once with Wi-Fi off: the offline fallback works.
5. Keep the video backup (release.md §5) on the desktop.

## Start
```bash
make demo                 # live: cloud keys first, local qwen3.5:9b fallback; warm-up loads the model in the background
HMAP_ROUTER=on make demo  # the same with the model router (the Models page shows each decision)
```

## If X fails
| Symptom | Do |
|---|---|
| Wi-Fi is down / the cloud keys are all rate limited | it falls back to the local model by itself (slower); for the talk: `make stop`, `make demo-replay` |
| The first step takes ~10 s+ | the model is loading: warm-up was off or Ollama started late (`logs/demo/warmup.log`) |
| "does not fit on this machine" in a step | too much in memory: close apps, or `HMAP_ROLE_MAP` to the lite model (`scripts/pull_models.sh --tier lite`) |
| Ollama not answering | `OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama OLLAMA_MAX_LOADED_MODELS=2 ollama serve` |
| The router does something odd | `HMAP_ROUTER=off` and restart: the role maps, exactly as before Sprint 11 |
| A project is stuck | Operations page (why it failed, replay a dead letter); the Review tab if it waits for a person |
| Anything else | `make stop`, then `make demo-replay` (no model, key or network) and show the recorded run |

## After
`make stop` (stops what `make demo` started: dashboard, agents, API, containers, Ollama, Colima).
