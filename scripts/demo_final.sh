#!/usr/bin/env bash
# Final end-to-end demo (Member 10, Sprint 10): the three golden scenarios (scripts/demo_final.py) on the whole
# platform — every capability real, the Manager's recovery slot on: TCP chat from the PDF, a report assignment, and
# a change request mid-run.
# Default: HMAP_LLM_MODE=replay with the recordings in samples/llm_cache/review/e2e (every agent's answers for these
# inputs): no model, key or network needed. `--record` runs live once (team cloud keys from .env first, local Ollama
# as fallback) and records every answer there; `--live` runs live without recording.
# Single-model tier (doc 02 §2.2b): `DEMO_TIER=single` keeps every chat role on the local qwen3.5:9b (no cloud);
# `DEMO_TIER=single-cloud` puts every chat role on one cloud model (Groq's Qwen, team keys).
# Research runs in HMAP_RESEARCH_MODE=cached (the offline corpus, never the network) unless you set it yourself.
# Set HMAP_BUS/HMAP_STORE to run on RabbitMQ/Postgres; DEMO_SPLIT=1 (needs rabbitmq) runs the agents in their own
# process. Extra arguments go to demo_final.py (e.g. --only=tcp, --json=out.json).
set -uo pipefail
mode_arg=""
case "${1:-}" in
  --live) export HMAP_LLM_MODE=live; mode_arg=1; shift ;;
  --record) export HMAP_LLM_MODE=record; mode_arg=1; shift ;;
esac
root="$(cd "$(dirname "$0")/.." && pwd)"
port="${DEMO_PORT:-8772}"
log="$root/logs/demo_final_api.log"; agents_log="$root/logs/demo_final_agents.log"; mkdir -p "$root/logs"
export HMAP_LLM_MODE="${HMAP_LLM_MODE:-replay}" HMAP_STUB_DELAY_S="${HMAP_STUB_DELAY_S:-0.2}"
export HMAP_ARTIFACT_ROOT="${HMAP_ARTIFACT_ROOT:-$root/data/demo_final_artifacts}"
export HMAP_RETRY_DELAYS_S="${HMAP_RETRY_DELAYS_S:-0.3,0.3,0.3}" HMAP_METRICS_INTERVAL_S="${HMAP_METRICS_INTERVAL_S:-0.5}"
export HMAP_RESEARCH_MODE="${HMAP_RESEARCH_MODE:-cached}"
# one plan step at a time: parallel steps finish in a different order on every run, which changes the project head
# and so the next prompts (the Sprint 7 "parallel order" replay trap); one order = one recording that always replays
export HMAP_PLAN_MAX_PARALLEL="${HMAP_PLAN_MAX_PARALLEL:-1}"
export HMAP_LLM_CACHE_DIR="${HMAP_LLM_CACHE_DIR:-$root/samples/llm_cache/review/e2e}"
if [ "${DEMO_TIER:-full}" = "single-cloud" ]; then
  # single-model tier on the team keys: one model (Groq's Qwen) for every chat role, no other cloud model; embeddings
  # stay local (Ollama) as in every tier
  q="groq:qwen/qwen3.8-27b"
  export HMAP_CLOUD_ROLE_MAP="reasoner=$q,coder=$q,judge=$q,fast=$q,classify=$q,vision=gemini:gemini-3.6-flash"
  export HMAP_LLM_CACHE_DIR="$root/samples/llm_cache/review/e2e_single"
fi
if [ "${DEMO_TIER:-full}" = "single" ]; then
  export HMAP_CLOUD_OK=false
  export HMAP_ROLE_MAP="${HMAP_ROLE_MAP:-reasoner=qwen3.5:9b,judge=qwen3.5:9b,coder=qwen3.5:9b,fast=qwen3.5:9b,classify=qwen3.5:9b,embed=nomic-embed-text}"
  export HMAP_LLM_CACHE_DIR="$root/samples/llm_cache/review/e2e_single"
fi
if [ -z "${HMAP_RESEARCH_CACHE_DIR:-}" ]; then   # an empty local cache: only the committed corpus counts
  export HMAP_RESEARCH_CACHE_DIR="$root/data/demo_final_research_cache"; rm -rf "$HMAP_RESEARCH_CACHE_DIR"
fi
if [ -z "${HMAP_CODING_WORK_DIR:-}" ]; then     # workspaces outside the project folder, fresh each run
  export HMAP_CODING_WORK_DIR="${TMPDIR:-/tmp}/hmap-demo-final"; rm -rf "$HMAP_CODING_WORK_DIR"
fi
rm -rf "$HMAP_ARTIFACT_ROOT"
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
[ -n "$mode_arg" ] && echo "LLM mode: $HMAP_LLM_MODE (cache $HMAP_LLM_CACHE_DIR)"
uv run --no-project --python 3.11 "$root/scripts/demo_final.py" "http://127.0.0.1:$port" "$@"
status=$?
if [ "$HMAP_LLM_MODE" = "replay" ]; then
  misses=$(grep -c "ReplayMissError\|replay miss" "$log" 2>/dev/null || true)
  # a call that failed while recording (every key cooling down and no Ollama, embeddings with Ollama stopped) has no
  # recording either: the agent takes the same no-model path in both, so the outcome is still the recorded one
  echo "model calls without a recording (incl. ones that failed while recording): ${misses:-0}"
fi
if [ $status -ne 0 ]; then
  echo "--- API log tail ---"; tail -30 "$log"
  [ "${DEMO_SPLIT:-0}" = "1" ] && { echo "--- agents log tail ---"; tail -30 "$agents_log"; }
fi
exit $status
