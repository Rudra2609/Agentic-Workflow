#!/usr/bin/env bash
# Sprint 6 demo: start the API (in-process Manager, the real doc_intel / planning / refine / research / verify agents,
# the stubs) on a spare port, run the scripted demo (scripts/demo_sprint_6.py), stop it.
# Uses HMAP_LLM_MODE=replay (recorded answers in samples/llm_cache/{doc_intel,planning,refine,research,verify}): no model, key or
# network needed. `--live` uses the real models (team cloud keys from .env first, local Ollama as fallback).
# `--record-missing` replays, but fetches and records the verifier answers that are missing (needs the team keys).
# Research runs in HMAP_RESEARCH_MODE=cached (the offline corpus in samples/research, never the network) unless you
# set it yourself; the demo works with Wi-Fi off.
# Set HMAP_BUS/HMAP_STORE to run on RabbitMQ/Postgres; DEMO_SPLIT=1 (needs rabbitmq) runs the agents in their own
# process (`hmap-agents run --all`, as `make agents`), the API process runs only the Manager.
set -uo pipefail
case "${1:-}" in
  --live) export HMAP_LLM_MODE=live ;;
  --record-missing) export HMAP_LLM_RECORD_MISSING="${HMAP_LLM_RECORD_MISSING:-verify}" ;;
esac
root="$(cd "$(dirname "$0")/.." && pwd)"
port="${DEMO_PORT:-8768}"
log="$root/logs/demo_sprint_6_api.log"; agents_log="$root/logs/demo_sprint_6_agents.log"; mkdir -p "$root/logs"
export HMAP_LLM_MODE="${HMAP_LLM_MODE:-replay}" HMAP_STUB_DELAY_S="${HMAP_STUB_DELAY_S:-0.2}"
export HMAP_ARTIFACT_ROOT="${HMAP_ARTIFACT_ROOT:-$root/data/demo_artifacts}"
export HMAP_RETRY_DELAYS_S="${HMAP_RETRY_DELAYS_S:-0.3,0.3,0.3}" HMAP_METRICS_INTERVAL_S="${HMAP_METRICS_INTERVAL_S:-0.5}"
export HMAP_RESEARCH_MODE="${HMAP_RESEARCH_MODE:-cached}"
if [ -z "${HMAP_RESEARCH_CACHE_DIR:-}" ]; then   # an empty local cache: only the committed corpus counts
  export HMAP_RESEARCH_CACHE_DIR="$root/data/demo_research_cache"; rm -rf "$HMAP_RESEARCH_CACHE_DIR"
fi
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
uv run --no-project --python 3.11 "$root/scripts/demo_sprint_6.py" "http://127.0.0.1:$port"
status=$?
if [ $status -ne 0 ]; then
  echo "--- API log tail ---"; tail -30 "$log"
  [ "${DEMO_SPLIT:-0}" = "1" ] && { echo "--- agents log tail ---"; tail -30 "$agents_log"; }
fi
exit $status
