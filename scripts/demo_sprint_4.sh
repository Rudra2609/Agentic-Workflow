#!/usr/bin/env bash
# Sprint 4 demo: start the API (in-process Manager, the real doc_intel / planning / refine agents, the stubs) on a spare
# port, run the scripted demo (scripts/demo_sprint_4.py), stop it.
# Uses HMAP_LLM_MODE=replay (recorded answers in samples/llm_cache/{doc_intel,planning,refine}): no model, key or
# network needed. `--live` uses the real models (team cloud keys from .env first, local Ollama as fallback).
# `--record-missing` replays, but fetches and records refine answers that are missing (needs the team keys).
# DEMO_OBS=1 (after `make obs-up`): send traces to Jaeger and check the trace + the firing alert as well.
# Set HMAP_BUS/HMAP_STORE to run on RabbitMQ/Postgres; DEMO_SPLIT=1 (needs rabbitmq) runs the agents in their own
# process (`hmap-agents run --all`, as `make agents`), the API process runs only the Manager.
set -uo pipefail
case "${1:-}" in
  --live) export HMAP_LLM_MODE=live ;;
  --record-missing) export HMAP_LLM_RECORD_MISSING=refine ;;
esac
root="$(cd "$(dirname "$0")/.." && pwd)"
port="${DEMO_PORT:-8767}"
log="$root/logs/demo_sprint_4_api.log"; agents_log="$root/logs/demo_sprint_4_agents.log"; mkdir -p "$root/logs"
export HMAP_LLM_MODE="${HMAP_LLM_MODE:-replay}" HMAP_STUB_DELAY_S="${HMAP_STUB_DELAY_S:-0.2}"
export HMAP_ARTIFACT_ROOT="${HMAP_ARTIFACT_ROOT:-$root/data/demo_artifacts}"
export HMAP_RETRY_DELAYS_S="${HMAP_RETRY_DELAYS_S:-0.3,0.3,0.3}" HMAP_METRICS_INTERVAL_S="${HMAP_METRICS_INTERVAL_S:-0.5}"
[ "${DEMO_OBS:-0}" = "1" ] && export HMAP_OTEL_ENDPOINT="${HMAP_OTEL_ENDPOINT:-http://127.0.0.1:4318}"
pids=()
trap 'for p in "${pids[@]}"; do kill "$p" 2>/dev/null; wait "$p" 2>/dev/null; done' EXIT
if [ "${DEMO_SPLIT:-0}" = "1" ]; then
  [ "${HMAP_BUS:-memory}" = "rabbitmq" ] || { echo "DEMO_SPLIT=1 needs HMAP_BUS=rabbitmq"; exit 2; }
  (cd "$root/backend" && exec uv run hmap-agents run --all) > "$agents_log" 2>&1 &
  pids+=($!)
  export HMAP_RUN_AGENTS=false
fi
(cd "$root/backend" && exec uv run uvicorn hmap.api.app:create_app --factory --host 127.0.0.1 --port "$port" \
   --log-level warning) > "$log" 2>&1 &
pids+=($!)
uv run --no-project --python 3.11 "$root/scripts/demo_sprint_4.py" "http://127.0.0.1:$port"
status=$?
if [ $status -ne 0 ]; then
  echo "--- API log tail ---"; tail -30 "$log"
  [ "${DEMO_SPLIT:-0}" = "1" ] && { echo "--- agents log tail ---"; tail -30 "$agents_log"; }
fi
exit $status
