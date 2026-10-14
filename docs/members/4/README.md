# Member 4 — Self-reflection and refinement (+ observability)

Two things, kept apart on purpose:

1. **Refinement.** A result (requirements, a plan, later a report or code) is checked, its problems are labelled
   (10 kinds × 4 severities), it is revised where it was flagged, and the loop stops on a clear rule. The best
   version is kept, never a worse one. Code checks come first; a judge model only checks what code cannot.
2. **Observability and operations.** Each task gets one trace (Manager → bus → agent → model) in Jaeger. Prometheus
   metrics are shown on a Grafana dashboard, with alert rules. An Operations page answers "why did this task fail?",
   lists dead letters, and replays one as a new attempt.

| | |
|---|---|
| Plug-ins | `backend/src/hmap/agents/refine/` (library + `refine.run` agent + adapters for `document.extract` and `plan.generate`), `backend/src/hmap/agents/ops/` (failure explanation, dead letters, replay) |
| Telemetry | `backend/src/hmap/obs/` (OpenTelemetry spans, Prometheus metrics, sampler); a no-op unless `HMAP_OTEL_ENDPOINT` / the metrics port are set |
| Hook into existing agents | `Plugin.refiners` (D1): the worker runs the adapter on the agent's result when `task.refine` is true; Members 2 and 3's folders are not touched |
| Switch | project setting `refine` ("Check and improve results" in the dashboard; default off, `HMAP_REFINE_DEFAULT`), per task `inputs["refine"]` |
| Events | `refine.iteration {task_id, run_id, iteration, score, issues_by_category}`, `refine.stopped {…, stop_reason, best_iteration, applied}`, `task.replayed {by, reason, replay, previous_attempts, last_error}` |
| Artifacts | `refinement-trace` (one per refined task, versioned per round), `refine-output` (each round's output), `refinement-progress`, `reflection-memory` |
| UI | project tab **Refinement** (`frontend/src/features/refine/`): rounds, problems by kind, score curve, stop reason, what changed; page **Operations** (`frontend/src/features/ops/`) |
| API | `/api/refine/policy`, `/api/refine/runs/{project_id}[/{run_id}[/diff?a=&b=]]`, `POST /api/refine/runs/{project_id}`; `/api/ops/overview`, `/failures`, `/explain/{task_id}`, `/dlq`, `POST /replay/{task_id}`; `GET /metrics` |
| Infra | `infra/docker-compose.obs.yml` + `infra/observability/` (Jaeger 2.22, Prometheus 3.13 + `alerts.yml`, Grafana 13 + `dashboards/hmap.json`, `load/soak.py`) |
| For later members | `Refiner`, critics, revisers, `StopPolicy` (usable on its own), `ReflectionMemory`, `RefinementMixin` / `@refinable` — see [integration](integration.md) |
| Docs | [plan](plan.md) · [research](research.md) · [design](design.md) · [eval](eval.md) · [testing](testing.md) · [integration](integration.md) · [runbook](runbook.md) |

## Run
```bash
cd backend && uv run pytest tests/refine tests/obs tests/ops -q          # unit, property, adapters, API (+ integration with infra up)
uv run python -m tests.refine.eval.run_eval --suite all --producer rules     # ablation, rule-made outputs, no network
uv run python -m tests.refine.eval.run_eval --suite all --producer replay    # ablation, recorded cloud outputs
uv run python -m tests.refine.eval.taxonomy_eval                             # labelling accuracy on 80 issues
HMAP_LLM_RECORD_MISSING=refine uv run python -m tests.refine.eval.run_eval --mode replay ...   # record only what is missing
uv run python -m tests.refine.eval.run_eval --suite plan --producer rules --refine-local --mode live  # local model, never recorded
uv run python ../infra/observability/load/soak.py --projects 40              # load test on stub agents
cd .. && scripts/demo_sprint_4.sh                                            # demo (replay; --live for real models)
make obs-up    # Jaeger http://127.0.0.1:16686, Prometheus :9090, Grafana :3001; then start the API with HMAP_OTEL_ENDPOINT
make obs-down
```

## Limitations
- On the recorded cloud outputs the gain is small: they are already good (requirements F1 0.98, plan must-have
  links 0.94). The loop mostly confirms them and stops after one check. The clear gains are on the weaker rule-made
  outputs (see [eval](eval.md)).
- Locally the judge is the same `qwen3.5:9b` that produced the output. In a local-only run it improved nothing
  (it missed what the cloud judge found, and long cases hit the 180 s budget), so refinement pays off with cloud keys.
  That is also why code checks come first and can overrule the judge.
- Refinement costs about 2–4 model calls (≈ 2–10 k tokens) per checked step, which is why it is off by default.
- Recorded answers exist for the gold sets and the demo. A replay run on any other input falls back to the
  code checks: the judge is skipped, and the round says so (the Refinement tab shows "Only the automatic checks
  scored this round"; `run_eval` lists it under `errors`).
- The traces, metrics and alerts are for one laptop: Jaeger keeps traces in memory only, and alerts show in
  Prometheus / Grafana (there is no Alertmanager, so nobody gets an email).
