#!/usr/bin/env bash
# Failure injection for the mid-evaluation (Sprint 6 item 6.22): kill the agents process while a research step runs,
# restart it, and watch the Manager recover — the dead agent's lease expires, the step is retried as a NEW execution
# on the new agents, and it completes. Repeated ROUNDS times (default 3). Uses the `make demo` stack (starts it if it
# is not running, and then stops it again at the end). Then: Operations page http://127.0.0.1:3000/features/ops.
#   scripts/demo_chaos.sh            # 3 rounds
#   ROUNDS=1 scripts/demo_chaos.sh
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
state="$root/data/demo"; logs="$root/logs/demo"
started=0
if ! { [ -f "$state/api.pid" ] && kill -0 "$(cat "$state/api.pid")" 2>/dev/null; }; then
  scripts/demo.sh || exit 1
  started=1
fi
restart_agents() {
  set -a; [ -f "$state/env" ] && . "$state/env"; set +a     # the same caches as make demo
  (cd backend && HMAP_BUS=rabbitmq HMAP_STORE=postgres HMAP_LLM_MODE="${HMAP_LLM_MODE:-replay}" \
     HMAP_RESEARCH_MODE="${HMAP_RESEARCH_MODE:-cached}" exec uv run --frozen hmap-agents run --all) \
     >>"$logs/agents.log" 2>&1 &
  echo $! >"$state/agents.pid"
}
export -f restart_agents
export root state logs HMAP_DEMO_STATE="$state"
uv run --no-project --python 3.11 "$root/scripts/demo_chaos.py" "${ROUNDS:-3}"
status=$?
[ "$started" = 1 ] && scripts/stop.sh
exit $status
