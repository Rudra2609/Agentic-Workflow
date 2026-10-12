#!/usr/bin/env bash
# Sprint 1 demo: start the API (in-process Manager + stub agents) on a spare port, run the scripted demo, stop it.
# Uses HMAP_LLM_MODE=fake so no model or key is needed. Set HMAP_BUS/HMAP_STORE to run on RabbitMQ/Postgres.
# DEMO_SPLIT=1 (needs HMAP_BUS=rabbitmq): agents run in their own process (`hmap-agents run --all`, as `make agents`)
# and the API process runs only the Manager — the two-process layout used for the real demo.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
port="${DEMO_PORT:-8765}"
log="$root/logs/demo_sprint_1_api.log"; agents_log="$root/logs/demo_sprint_1_agents.log"; mkdir -p "$root/logs"
export HMAP_LLM_MODE="${HMAP_LLM_MODE:-fake}" HMAP_ARTIFACT_ROOT="${HMAP_ARTIFACT_ROOT:-$root/data/demo_artifacts}"
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
uv run --no-project --python 3.11 "$root/scripts/demo_sprint_1.py" "http://127.0.0.1:$port"
status=$?
if [ $status -ne 0 ]; then
  echo "--- API log tail ---"; tail -30 "$log"
  [ "${DEMO_SPLIT:-0}" = "1" ] && { echo "--- agents log tail ---"; tail -30 "$agents_log"; }
fi
exit $status
