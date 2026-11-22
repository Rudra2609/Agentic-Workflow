# Troubleshooting

What to do when the demo does not start or a step fails. The pre-flight (`scripts/demo_preflight.py`, run by
`make demo`) prints most of these fixes itself. Checked against the code like the [runbook](runbook.md).

| Symptom | Cause | Fix |
|---|---|---|
| `FAIL port 3000` / `port 8000` in the pre-flight | an earlier copy is still running, or another program uses the port | `make stop`; if it persists, `lsof -nP -iTCP:3000 -sTCP:LISTEN` shows the program |
| `FAIL infra ports` | something else (another Postgres or RabbitMQ) holds port 5433 or 5672 | stop that program; this project's containers are fine |
| `FAIL free memory` | browsers, IDEs or a loaded model use the RAM | close heavy apps, or run `make demo-replay`; the floor is `HMAP_DEMO_MIN_FREE_GB` |
| `FAIL ollama` | Ollama is not running and there are no cloud keys | start it as in the project notes (`OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama ollama serve`), or paste the team keys into `.env` |
| `FAIL model qwen3.5:9b` / `nomic-embed-text` | the model is not pulled | `ollama pull qwen3.5:9b`, `ollama pull nomic-embed-text` |
| `WARN sandbox image` | the testing sandbox image was never built | `make sandbox-image` once with the internet; until then tests run in the local jailed runner |
| “make demo FAILED: colima start” | Colima cannot start (VM broken, disk full) | `colima stop`, then `colima start`; the log is `logs/demo/colima.log` |
| “make demo FAILED: migrations” | the database is older or newer than the code | `make reset-demo` (deletes the demo data) |
| “make demo FAILED: next build” | the dashboard does not compile | read `logs/demo/web-build.log`; `cd frontend && npm ci` after a dependency change |
| The dashboard says the server is not reachable | the API stopped | read `logs/demo/api.log`, then `make stop` and `make demo` |
| A step stays "assigned" and nothing happens | the agents process died | `scripts/demo_chaos.sh` shows the same recovery; or `make stop` and `make demo` |
| A step fails with a replay miss in `make demo-replay` | the recordings do not cover this input (a new document, a changed prompt) | use the inputs in `samples/demo/`, or run `make demo` (live) |
| Steps are slow, "all keys cooling down" in `logs/demo/agents.log` | every team key hit its rate limit; the local model answers instead | wait a minute, or `make cloud-check` to see which keys work |
| The Docs tab says "facts only (no model)" | no model answered (replay without recordings, no keys and no Ollama) | expected in replay for new projects; the documents are still checked against the code |
| `make stop` printed "stopped" but a process is left | a process ignored the stop signal | run `make stop` again: it waits, then force-stops the demo's own processes |
| The sign-in fails for the demo account | it was created with another password | `make reset-demo`, or set `HMAP_DEMO_EMAIL` / `HMAP_DEMO_PASSWORD` for `scripts/demo.sh` |
