#!/usr/bin/env bash
# `make demo` / `make demo-replay` (Sprint 9 items 9.15-9.17, Member 9; replaces Sprint 6's minimal 6.21): the
# whole platform on this laptop in one command, nothing deployed (doc 02 §3).
#   pre-flight (scripts/demo_preflight.py: tools, ports, free RAM, disk, model) -> Colima + Postgres + RabbitMQ
#   (wait healthy) -> migrations -> API (Manager) 127.0.0.1:8000 -> agents in their own process (so
#   scripts/demo_chaos.sh can kill them) -> dashboard as a production build (next build, only when the frontend
#   changed; next start) 127.0.0.1:3000 -> demo account + seeded project -> opens the browser.
# Modes: DEMO_MODE=live (make demo: cloud keys first, local Ollama fallback; starts Ollama if it is installed and
# not running) or DEMO_MODE=replay (make demo-replay: recorded answers + saved pages; no model, key or network).
# Logs: logs/demo/. State: data/demo/. make stop stops everything this started; make reset-demo wipes the state.
#   HMAP_DEMO_SKIP_PREFLIGHT=1  skip the pre-flight     HMAP_DEMO_NO_OPEN=1  do not open the browser
#   HMAP_DEMO_DEV=1             next dev instead of the production build (hot reload)
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
MODE="${DEMO_MODE:-live}"
state="$root/data/demo"; logs="$root/logs/demo"; mkdir -p "$state" "$logs"
EMAIL="${HMAP_DEMO_EMAIL:-mid-eval@example.test}"       # local test account (samples/demo/README.md)
PASSWORD="${HMAP_DEMO_PASSWORD:-hmap-demo-2026}"
API=http://127.0.0.1:8000; WEB=http://127.0.0.1:3000
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE=docker-compose; fi

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mmake demo FAILED: %s\033[0m\n' "$*"; "$root/scripts/stop.sh" >/dev/null 2>&1; exit 1; }
up() { curl -fsS -o /dev/null "$1" 2>/dev/null; }
wait_for() { for _ in $(seq "$2"); do up "$1" && return 0; sleep 1; done; return 1; }
envval() { [ -n "${!1:-}" ] && { printf '%s' "${!1}"; return; }; [ -f .env ] && sed -n "s/^$1=\([^ #]*\).*/\1/p" .env | tail -1; }

case "$MODE" in live|replay) ;; *) echo "DEMO_MODE must be live or replay"; exit 2 ;; esac
if [ -f "$state/api.pid" ] && kill -0 "$(cat "$state/api.pid")" 2>/dev/null; then
  echo "the demo is already running at $WEB (make stop first)"; exit 0
fi
for p in 8000 3000; do   # a just-stopped copy may still be closing its ports: give it a few seconds
  for _ in $(seq 10); do lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 1; done
done
: >"$state/started"

say "1/7 pre-flight ($MODE)"
ollama_url="$(envval OLLAMA_BASE_URL)"; ollama_url="${ollama_url:-http://127.0.0.1:11434}"
if [ "$MODE" = live ] && command -v ollama >/dev/null && ! up "$ollama_url/api/version" \
   && [[ "$ollama_url" == *127.0.0.1* || "$ollama_url" == *localhost* ]]; then
  # the local fallback (and the embedder documents need): start it with the models on the external disk
  models="${OLLAMA_MODELS:-$(envval OLLAMA_MODELS)}"; models="${models:-/Volumes/Tirth_SSD/ollama}"
  if [ -d "$models" ]; then
    OLLAMA_MODELS="$models" OLLAMA_MAX_LOADED_MODELS=2 nohup ollama serve >"$logs/ollama.log" 2>&1 &
    echo $! >"$state/ollama.pid"; echo ollama >>"$state/started"
    wait_for "$ollama_url/api/version" 20 || echo "  (Ollama did not answer in 20 s; see logs/demo/ollama.log)"
  fi
fi
if [ -z "${HMAP_DEMO_SKIP_PREFLIGHT:-}" ]; then
  python3 scripts/demo_preflight.py --mode "$MODE" || fail "pre-flight (fix the FAIL lines above, or HMAP_DEMO_SKIP_PREFLIGHT=1)"
fi
# Sprint 11 (item 11.18): load the local model + embedder in the background while the rest starts, so the first
# step is not a cold load (HMAP_WARMUP=false to skip; logs/demo/warmup.log has the seconds)
if [ "$MODE" = live ] && [ "$(envval HMAP_WARMUP)" != false ] && up "$ollama_url/api/version" && [ -d backend/.venv ]; then
  (cd backend && nohup uv run --frozen python -m hmap.agents.models.warmup >"$logs/warmup.log" 2>&1 &)
fi

say "2/7 toolchain (a clean copy installs the locked dependencies once)"
[ -d backend/.venv ] || uv --directory backend sync --frozen --all-extras >"$logs/setup.log" 2>&1 || fail "uv sync (logs/demo/setup.log)"
[ -d frontend/node_modules ] || (cd frontend && npm ci >>"$logs/setup.log" 2>&1) || fail "npm ci (logs/demo/setup.log)"

say "3/7 infra: Postgres + RabbitMQ (wait until healthy)"
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
if [ "$MODE" = replay ]; then
  export HMAP_LLM_MODE=replay HMAP_RESEARCH_MODE="${HMAP_RESEARCH_MODE:-cached}"
else
  export HMAP_LLM_MODE="${HMAP_LLM_MODE:-$(envval HMAP_LLM_MODE)}"; HMAP_LLM_MODE="${HMAP_LLM_MODE:-live}"
  [ "$HMAP_LLM_MODE" = replay ] && HMAP_LLM_MODE=live      # make demo is the live demo; replay = make demo-replay
  export HMAP_RESEARCH_MODE="${HMAP_RESEARCH_MODE:-$(envval HMAP_RESEARCH_MODE)}"
  HMAP_RESEARCH_MODE="${HMAP_RESEARCH_MODE:-cached}"
fi
export HMAP_STUB_DELAY_S="${HMAP_STUB_DELAY_S:-0.5}" HMAP_RETRY_DELAYS_S="${HMAP_RETRY_DELAYS_S:-1,2,5}"
# only the committed corpus and search results count (as the recordings were made): empty local caches each start
if [ -z "${HMAP_RESEARCH_CACHE_DIR:-}" ]; then
  export HMAP_RESEARCH_CACHE_DIR="$state/research_cache"; rm -rf "${HMAP_RESEARCH_CACHE_DIR:?}"
fi
if [ -z "${HMAP_VERIFY_CACHE_DIR:-}" ]; then
  export HMAP_VERIFY_CACHE_DIR="$state/verify_cache"; rm -rf "${HMAP_VERIFY_CACHE_DIR:?}"
fi
printf 'HMAP_LLM_MODE=%s\nHMAP_RESEARCH_MODE=%s\nHMAP_RESEARCH_CACHE_DIR=%s\nHMAP_VERIFY_CACHE_DIR=%s\nDEMO_MODE=%s\n' \
  "$HMAP_LLM_MODE" "$HMAP_RESEARCH_MODE" "$HMAP_RESEARCH_CACHE_DIR" "$HMAP_VERIFY_CACHE_DIR" "$MODE" >"$state/env"

say "4/7 migrations"
(cd backend && uv run --frozen python -c "from hmap.db.migrate import upgrade; upgrade()") >"$logs/migrate.log" 2>&1 \
  || { tail -20 "$logs/migrate.log"; fail "migrations (logs/demo/migrate.log)"; }

say "5/7 API + Manager (127.0.0.1:8000; LLM mode $HMAP_LLM_MODE, research $HMAP_RESEARCH_MODE) + agents"
(cd backend && HMAP_RUN_AGENTS=false exec uv run --frozen uvicorn hmap.api.app:create_app --factory \
   --host 127.0.0.1 --port 8000 --log-level warning) >"$logs/api.log" 2>&1 &
echo $! >"$state/api.pid"
(cd backend && exec uv run --frozen hmap-agents run --all) >"$logs/agents.log" 2>&1 &
echo $! >"$state/agents.pid"
wait_for "$API/api/health" 120 || { tail -20 "$logs/api.log"; fail "API did not start (logs/demo/api.log)"; }
expected=$(cd backend && uv run --frozen python -c "from hmap.core.runtime.discovery import discover
from hmap.core.runtime.host import agents_to_run
print(len(agents_to_run(discover())))" 2>/dev/null)
for _ in $(seq 120); do   # every agent logs "agent running" once it has registered
  n=$(grep -c 'agent running' "$logs/agents.log" 2>/dev/null); [ "${n:-0}" -ge "${expected:-1}" ] && break; sleep 1
done
echo "  ${n:-0}/${expected:-?} agents running"

say "6/7 dashboard (127.0.0.1:3000)"
if [ -n "${HMAP_DEMO_DEV:-}" ]; then
  (cd frontend && exec npm run dev) >"$logs/web.log" 2>&1 &
else
  hash=$(cd frontend && find src public package-lock.json next.config.* -type f 2>/dev/null | LC_ALL=C sort \
         | xargs cat 2>/dev/null | shasum | cut -c1-16)
  if [ ! -f frontend/.next/BUILD_ID ] || [ "$(cat frontend/.next/hmap-build.hash 2>/dev/null)" != "$hash" ]; then
    echo "  production build (the frontend changed; ~1-2 min, log: logs/demo/web-build.log)"
    (cd frontend && npm run build) >"$logs/web-build.log" 2>&1 || { tail -20 "$logs/web-build.log"; fail "next build"; }
    echo "$hash" >frontend/.next/hmap-build.hash        # kept by make reset-demo (lives with the build)
  else
    echo "  production build is up to date"
  fi
  (cd frontend && exec npm run start) >"$logs/web.log" 2>&1 &
fi
echo $! >"$state/web.pid"
wait_for "$WEB/login" 120 || { tail -20 "$logs/web.log"; fail "dashboard did not start (logs/demo/web.log)"; }

say "7/7 demo account + demo state"
reg=$(printf '{"name":"Demo presenter","email":"%s","password":"%s"}' "$EMAIL" "$PASSWORD")
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$reg" "$API/api/auth/register")
login=$(printf '{"email":"%s","password":"%s"}' "$EMAIL" "$PASSWORD")
ok=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$login" "$API/api/auth/login")
case "$code:$ok" in
  201:200) echo "account created" ;;
  *:200) echo "account ready" ;;
  *) echo "warning: could not sign in as $EMAIL (it exists with another password? set HMAP_DEMO_EMAIL)" ;;
esac
if [ "$ok" = 200 ] && [ -z "${HMAP_DEMO_NO_SEED:-}" ]; then
  HMAP_SEED_EMAIL="$EMAIL" HMAP_SEED_PASSWORD="$PASSWORD" scripts/seed.sh "$API" --if-empty >"$logs/seed.log" 2>&1 &
  echo "  seeding the demo project in the background (logs/demo/seed.log): it stops at the plan approval"
fi

printf '\n\033[1;32mHMAP demo (%s) is running at %s\033[0m  (sign in: %s / %s)\n' "$MODE" "$WEB" "$EMAIL" "$PASSWORD"
printf '  Inputs: samples/demo/   Failure injection: scripts/demo_chaos.sh   Stop: make stop   Reset: make reset-demo   Logs: logs/demo/\n'
if [ -z "${HMAP_DEMO_NO_OPEN:-}" ] && command -v open >/dev/null; then open "$WEB" >/dev/null 2>&1 || true; fi
