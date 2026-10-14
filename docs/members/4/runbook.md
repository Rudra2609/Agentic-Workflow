# Operator runbook (Member 4)

This page is for whoever is running the platform. It covers what each alert means, where to look, and what to do.
Every alert in `infra/observability/prometheus/alerts.yml` links to its section here.

## Start and stop the observability stack

```bash
make infra-up                 # RabbitMQ + Postgres (Colima / Docker must be running)
make obs-up                   # Jaeger :16686, Prometheus :9090, Grafana :3001 (127.0.0.1 only, ~650 MB RAM in all)
export HMAP_OTEL_ENDPOINT=http://127.0.0.1:4318    # or put it in .env, then restart:
make api                      # API + Manager: /metrics on :8000
make agents                   # agent process: /metrics on :9464 (HMAP_METRICS_PORT)
make obs-open                 # opens Jaeger, the Prometheus alerts page and the Grafana dashboard
make obs-down                 # when done (frees the RAM); traces live in memory and are gone
```

- Grafana is anonymous and view-only. The admin password is `HMAP_GRAFANA_PASSWORD` from `.env`; `make obs-up`
  makes a random one if it is not set.
- With no `HMAP_OTEL_ENDPOINT`, nothing is traced. `/metrics` on the API still works.

## Where to look

| Question | Where |
|---|---|
| Why did this task fail? | dashboard → **Operations** → the task, or `GET /api/ops/explain/{task_id}`; also "Why did this step fail?" in a task's inspector |
| What happened, step by step? | the trace link on the Operations page → Jaeger: `manager.assign` → `send hmap.cap.X` → `process hmap.cap.X` → `agent.handle` → `refine.loop` → `chat <role>`; every attempt and replay of a task is in the same trace |
| Is anything piling up? | Grafana "hmap — platform overview": queue depth, oldest READY step, tasks by state, dead letters |
| Which alerts are firing? | Prometheus `/alerts`, or the alerts table at the top of the Grafana dashboard |

## Replay, replan, or stop?

| Situation | Do |
|---|---|
| The cause was outside us and is gone (a site was down, a model quota is reset, an agent was restarted) | **Replay**: Operations → "Replay as a new attempt", with a reason |
| The step itself is wrong (bad inputs, an impossible step, a missing capability) | **Change the plan**: the project's Plan tab → "Change plan…" (sends the failed steps along) |
| Nobody needs the result any more, or it would fail the same way again | **Stop**: leave it, or cancel the project |

A replay is never automatic, and it does not reuse the old attempt:

- It needs a person and a reason.
- It creates a **new execution** with a fresh retry budget. The old attempts stay in the history.
- It writes a `task.replayed` event saying who replayed it and why.
- Steps that were blocked by it start again.
- A failed project goes back to running.

Replay the same step twice only if you changed something in between.

---

## HmapDeadLetter
**Means:** at least one step used all its retries and is in the dead-letter state, so its project cannot finish.
(`max(hmap_dead_lettered_tasks) > 0`, fires at once.)
**Look:** Operations → Dead letters → the step → "Why?". The verdict names the error code (for example
`TOOL_TRANSIENT`, `TIMEOUT`, `AGENT_UNAVAILABLE`), the number of attempts, and which agent ran each one.
**Do:** use the replay / replan / stop table above. A transient cause that is gone → replay. An `INVALID_TASK`,
`MISSING_CONTEXT` or `WRONG_RESULT` error → replan. The alert clears when nothing is dead-lettered any more.

## HmapBusDeadLetters
**Means:** RabbitMQ moved messages to its dead-letter queue. A message could not be handled at all (for example it
was malformed or rejected); this is not a task error. (`max(hmap_bus_dlq_messages) > 0`.)
**Look:** `GET /api/dead-letters` (Manager-level) and the API / agent logs around that time. Look for the message's
type and which process rejected it.
**Do:** usually a bug or a version mismatch between processes. Restart the processes on the same code. Messages in
the bus DLQ are not replayed from the UI; the task they belonged to is retried or dead-lettered by the Manager as
usual.

## HmapAgentHeartbeatExpired
**Means:** an agent stopped sending heartbeats for more than 30 s. It crashed, was killed, or the laptop slept. The
Manager re-assigns its work after the heartbeat timeout.
(`hmap_agent_heartbeat_age_seconds > 30`; an agent that went offline stays visible for 10 minutes.)
**Look:** Agents page (state OFFLINE), the agents process log, and `make agents` still running?
**Do:** restart the agents process (`make agents`). Its steps continue as new executions. If it keeps dying,
check RAM (see HmapLowMemory) and the log for a crash in one agent.

## HmapQueueStale
**Means:** a step has been READY for more than 60 s for 2 minutes, and no agent takes it.
(`hmap_queue_oldest_ready_seconds > 60`.)
**Look:** Grafana queue panels: which capability? The Agents page: is an agent with that capability online and
not busy?
**Do:** start the agent that serves it, or wait if all its agents are busy with long model calls (local models take
minutes). If no plug-in serves the capability, change the plan.

## HmapLLMErrors
**Means:** more than 20 % of model calls failed over 5 minutes. (Rate of `hmap_llm_calls_total{outcome="error"}`.)
**Look:** Grafana "Model calls / min by outcome" and "Model latency p50 / p95 by role". The API / agent logs show the
error code and the key fingerprint, never the key.
**Do:**
- Cloud 429s or quota errors cool the key down, then the next key or the local model is used. The alert means all
  keys are exhausted or Ollama is not running: start Ollama, or wait for the quota to reset.
- If the local model fails, check RAM, and that `OLLAMA_MODELS` points to the SSD.

## HmapLowMemory
**Means:** less than 1.5 GB of RAM is left on this computer for a minute. Ollama plus Docker plus the obs stack can
fill 16 GB. (`hmap_system_memory_available_bytes < 1.5e9`.)
**Look:** Grafana "Memory" row: the process RSS of the API and agents, and free RAM. Activity Monitor for Ollama and
Docker.
**Do:** `make obs-down` first (frees ~650 MB). Then unload unused Ollama models (`OLLAMA_MAX_LOADED_MODELS=2`)
or stop Colima if the in-memory bus is enough.
