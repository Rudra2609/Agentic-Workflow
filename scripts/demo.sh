#!/usr/bin/env bash
# `make demo` (Sprint 6 item 6.21, minimal; Member 9 replaces it with the full packaging in Sprint 9): the whole
# platform on this laptop in one command, offline by default.
#   infra (Colima + Postgres + RabbitMQ) -> API (Manager) on 127.0.0.1:8000 -> agents in their own process (so
#   scripts/demo_chaos.sh can kill them) -> dashboard on 127.0.0.1:3000 -> a demo account. Migrations run on start.
#   HMAP_LLM_MODE=replay (recorded answers) and HMAP_RESEARCH_MODE=cached (saved pages) unless set; no model, key
#   or network needed. `make stop` stops everything this started. Logs: logs/demo/. State: data/demo/.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
state="$root/data/demo"; logs="$root/logs/demo"; mkdir -p "$state" "$logs"
EMAIL="${HMAP_DEMO_EMAIL:-mid-eval@example.test}"       # local test account (samples/demo/README.md)
PASSWORD="${HMAP_DEMO_PASSWORD:-hmap-demo-2026}"
API=http://127.0.0.1:8000; WEB=http://127.0.0.1:3000
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE=docker-compose; fi

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mmake demo FAILED: %s\033[0m\n' "$*"; "$root/scripts/stop.sh" >/dev/null 2>&1; exit 1; }
up() { curl -fsS -o /dev/null "$1" 2>/dev/null; }
wait_for() { for _ in $(seq "$2"); do up "$1" && return 0; sleep 1; done; return 1; }

if [ -f "$state/api.pid" ] && kill -0 "$(cat "$state/api.pid")" 2>/dev/null; then
  echo "the demo is already running at $WEB (make stop first)"; exit 0
fi
for p in 8000 3000; do   # a just-stopped copy may still be closing its ports: give it a few seconds
  for _ in $(seq 10); do lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 1; done
  lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && fail "port $p is in use (another copy running? make stop)"
done

say "1/5 toolchain (first run on a clean copy installs the locked dependencies)"
command -v uv >/dev/null || fail "uv is not installed (docs/00-prerequisites-checklist.md)"
command -v npm >/dev/null || fail "npm is not installed (docs/00-prerequisites-checklist.md)"
[ -d backend/.venv ] || uv --directory backend sync --frozen --all-extras >"$logs/setup.log" 2>&1 || fail "uv sync"
[ -d frontend/node_modules ] || (cd frontend && npm ci >>"$logs/setup.log" 2>&1) || fail "npm ci"

say "2/5 infra: Postgres + RabbitMQ"
: >"$state/started"
if ! docker info >/dev/null 2>&1; then
  command -v colima >/dev/null || fail "Docker is not running and Colima is not installed"
  colima start >"$logs/colima.log" 2>&1 || fail "colima start (log: logs/demo/colima.log)"
  echo colima >>"$state/started"
fi
already=$(docker ps -q --filter name=hmap-postgres-1 --filter status=running 2>/dev/null)
$COMPOSE -f infra/docker-compose.yml up -d --wait >"$logs/infra.log" 2>&1 || fail "postgres/rabbitmq (logs/demo/infra.log)"
[ -n "$already" ] || echo infra >>"$state/started"      # make stop leaves infra running if it was already up
scripts/infra_init.sh >>"$logs/infra.log" 2>&1 || fail "database init"

export HMAP_BUS=rabbitmq HMAP_STORE=postgres
export HMAP_LLM_MODE="${HMAP_LLM_MODE:-replay}" HMAP_RESEARCH_MODE="${HMAP_RESEARCH_MODE:-cached}"
export HMAP_STUB_DELAY_S="${HMAP_STUB_DELAY_S:-0.5}" HMAP_RETRY_DELAYS_S="${HMAP_RETRY_DELAYS_S:-1,2,5}"
# only the committed corpus and search results count (as the recordings were made): empty local caches each start
if [ -z "${HMAP_RESEARCH_CACHE_DIR:-}" ]; then
  export HMAP_RESEARCH_CACHE_DIR="$state/research_cache"; rm -rf "$HMAP_RESEARCH_CACHE_DIR"
fi
if [ -z "${HMAP_VERIFY_CACHE_DIR:-}" ]; then
  export HMAP_VERIFY_CACHE_DIR="$state/verify_cache"; rm -rf "$HMAP_VERIFY_CACHE_DIR"
fi
printf 'HMAP_RESEARCH_CACHE_DIR=%s\nHMAP_VERIFY_CACHE_DIR=%s\n' "$HMAP_RESEARCH_CACHE_DIR" "$HMAP_VERIFY_CACHE_DIR" >"$state/env"

say "3/5 API + Manager (127.0.0.1:8000, migrations on start; LLM mode $HMAP_LLM_MODE, research $HMAP_RESEARCH_MODE)"
(cd backend && HMAP_RUN_AGENTS=false exec uv run --frozen uvicorn hmap.api.app:create_app --factory \
   --host 127.0.0.1 --port 8000 --log-level warning) >"$logs/api.log" 2>&1 &
echo $! >"$state/api.pid"
wait_for "$API/api/health" 120 || { tail -20 "$logs/api.log"; fail "API did not start (logs/demo/api.log)"; }

say "4/5 agents (own process: scripts/demo_chaos.sh kills it) + dashboard (127.0.0.1:3000)"
(cd backend && exec uv run --frozen hmap-agents run --all) >"$logs/agents.log" 2>&1 &
echo $! >"$state/agents.pid"
(cd frontend && exec npm run dev) >"$logs/web.log" 2>&1 &
echo $! >"$state/web.pid"
for _ in $(seq 90); do   # every agent logs "agent running" once it has registered
  n=$(grep -c 'agent running' "$logs/agents.log" 2>/dev/null); [ "${n:-0}" -ge 10 ] && break; sleep 1
done
wait_for "$WEB/login" 120 || { tail -20 "$logs/web.log"; fail "dashboard did not start (logs/demo/web.log)"; }

say "5/5 demo account"
reg=$(printf '{"name":"Demo presenter","email":"%s","password":"%s"}' "$EMAIL" "$PASSWORD")
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$reg" "$API/api/auth/register")
login=$(printf '{"email":"%s","password":"%s"}' "$EMAIL" "$PASSWORD")
ok=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$login" "$API/api/auth/login")
case "$code:$ok" in
  201:200) echo "account created" ;;
  *:200) echo "account ready" ;;
  *) echo "warning: could not sign in as $EMAIL (it exists with another password? set HMAP_DEMO_EMAIL)" ;;
esac

printf '\n\033[1;32mHMAP demo is running at %s\033[0m  (sign in: %s / %s)\n' "$WEB" "$EMAIL" "$PASSWORD"
printf '  Inputs: samples/demo/   Failure injection: scripts/demo_chaos.sh   Stop: make stop   Logs: logs/demo/\n'
