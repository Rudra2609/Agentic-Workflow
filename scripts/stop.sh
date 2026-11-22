#!/usr/bin/env bash
# `make stop` (Sprint 6 item 6.21, Sprint 9 item 9.15): stop what `make demo` / `make demo-replay` started —
# dashboard, agents, API, the seeding script, then Postgres + RabbitMQ, Ollama and Colima (each only if make demo
# started it). Safe to run twice.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
state="$root/data/demo"
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE=docker-compose; fi
pkill -f "scripts/seed.py" 2>/dev/null
for name in web agents api; do
  f="$state/$name.pid"
  [ -f "$f" ] || continue
  pid=$(cat "$f")
  pkill -TERM -P "$pid" 2>/dev/null; kill -TERM "$pid" 2>/dev/null
  rm -f "$f"
done
# uvicorn closes its port first and then waits for open connections (a browser's live event stream): give everything
# a few seconds to finish cleanly, then force what is left of the demo's own processes
for _ in $(seq 8); do
  pgrep -f "uvicorn hmap.api.app|hmap-agents run --all|next-server|next start .*3000" >/dev/null || break
  sleep 1
done
for p in 3000 8000; do lsof -ti "tcp:$p" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null; done
pkill -9 -f "uvicorn hmap.api.app" 2>/dev/null
pkill -9 -f "hmap-agents run --all" 2>/dev/null
pkill -9 -f "next start .*--port 3000" 2>/dev/null
pkill -9 -f "next-server" 2>/dev/null
if grep -qx infra "$state/started" 2>/dev/null; then $COMPOSE -f infra/docker-compose.yml stop >/dev/null 2>&1; fi
if grep -qx ollama "$state/started" 2>/dev/null; then
  [ -f "$state/ollama.pid" ] && kill -TERM "$(cat "$state/ollama.pid")" 2>/dev/null
  rm -f "$state/ollama.pid"
fi
if grep -qx colima "$state/started" 2>/dev/null; then colima stop >/dev/null 2>&1; fi
rm -f "$state/started"
echo "stopped"
