# Runbook: running the platform on the demo laptop

Everything runs on Member 1's laptop; nothing is deployed (doc 02 §3). This page is written by hand and checked by
the documentation agent's grounding checker against the code (`tests/docgen/test_platform_docs.py`): every command,
setting, port and path below exists.

## Start
```bash
make demo
```
The live demo: team cloud keys first, the local model as fallback. It runs a pre-flight first
(`scripts/demo_preflight.py`), starts Ollama when it is installed and not running, starts Colima and the
Postgres + RabbitMQ containers, runs the migrations, starts the API (port 8000), the agents (their own process) and
the dashboard (port 3000, a production build), signs in the demo account and seeds a project waiting at the plan
approval. The account is in `samples/demo/README.md`.

Offline (recorded model answers and saved pages; works with Ollama stopped and Wi-Fi off):
```bash
make demo-replay
```

Options (environment variables for `scripts/demo.sh`): `HMAP_DEMO_SKIP_PREFLIGHT=1`, `HMAP_DEMO_NO_OPEN=1` (do not
open the browser), `HMAP_DEMO_DEV=1` (hot-reloading dashboard instead of the production build),
`HMAP_DEMO_NO_SEED=1`. The free-memory floor of the pre-flight is `HMAP_DEMO_MIN_FREE_GB`.

## Stop
```bash
make stop
```
Stops the dashboard, the agents and the API, then the containers, Ollama and Colima, each only if `make demo` started
it. Safe to run twice.

## Reset to the demo state
```bash
make reset-demo
```
Asks first, then empties the database (the schema is dropped and migrated again) and deletes the artifacts. The next
`make demo` creates the demo account and the seeded project again. `.env`, `samples/`, the Ollama models and the
Docker images are never touched.

## Check the laptop without starting anything
```bash
python3 scripts/demo_preflight.py --mode live
python3 scripts/demo_preflight.py --mode replay
make doctor
make cloud-check
```

## Logs and state
- `logs/demo/`: one file per process (`api.log`, `agents.log`, `web.log`, `web-build.log`, `infra.log`,
  `migrate.log`, `seed.log`, `ollama.log`).
- `data/demo/`: process ids and what `make demo` started (read by `make stop`); `data/artifacts/`: the artifacts.

## Failure injection (for the audience)
```bash
scripts/demo_chaos.sh
```
Kills the agents process while a research step runs and restarts it: the step is retried as a new execution.

## The final-report skeleton
```bash
make report
```
Writes `reports/final-report.md` from every member's research, design and eval documents.

## Before a presentation
1. `make stop`, then `make reset-demo` (fresh state).
2. `make demo` once on the Wi-Fi you will present on; keep `make demo-replay` ready as the safety net.
3. Close heavy apps (browsers with many tabs, IDEs): the pre-flight needs free memory.
4. Things go wrong: [troubleshooting](troubleshooting.md).
