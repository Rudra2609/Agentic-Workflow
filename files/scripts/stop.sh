#!/usr/bin/env bash
# `make stop` (Sprint 6 item 6.21): stop what `make demo` started — dashboard, agents, API, then Postgres + RabbitMQ
# (and Colima if make demo started it). Safe to run twice.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
state="$root/data/demo"
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE=docker-compose; fi
for name in web agents api; do
  f="$state/$name.pid"
  [ -f "$f" ] || continue
  pid=$(cat "$f")
  pkill -TERM -P "$pid" 2>/dev/null; kill -TERM "$pid" 2>/dev/null
  rm -f "$f"
done
sleep 2
for p in 3000 8000; do lsof -ti "tcp:$p" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null; done
pkill -f "hmap-agents run --all" 2>/dev/null
if grep -qx infra "$state/started" 2>/dev/null; then $COMPOSE -f infra/docker-compose.yml stop >/dev/null 2>&1; fi
if grep -qx colima "$state/started" 2>/dev/null; then colima stop >/dev/null 2>&1; fi
rm -f "$state/started"
echo "stopped"
