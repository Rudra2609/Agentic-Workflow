#!/usr/bin/env bash
# `make reset-demo` (Sprint 9 item 9.17): back to the demo state. Stops the demo, empties the database (schema
# dropped, migrations re-run) and wipes the artifacts and the demo caches; the next `make demo` / `make demo-replay`
# seeds the demo account and project again. Never touches .env, samples/, the Ollama models or Docker images.
#   scripts/reset_demo.sh          # asks first
#   scripts/reset_demo.sh --yes
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE=docker-compose; fi
db_url="${HMAP_DATABASE_URL:-postgresql+psycopg://hmap:hmap@127.0.0.1:5433/hmap}"
db="${db_url##*/}"; db="${db%%\?*}"                # the database of HMAP_DATABASE_URL (default hmap)
[[ "$db" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "refusing: odd database name $db"; exit 2; }
artifacts="${HMAP_ARTIFACT_ROOT:-$root/data/artifacts}"
case "$artifacts" in /*) ;; *) artifacts="$root/$artifacts" ;; esac
demo_state="$root/data/demo"
for p in "$artifacts" "$demo_state"; do              # guard: only folders inside this copy's data/
  case "$(cd "$(dirname "$p")" 2>/dev/null && pwd)/$(basename "$p")" in
    "$root"/data/*) ;;
    *) echo "refusing: $p is not inside $root/data"; exit 2 ;;
  esac
done
if [ "${1:-}" != "--yes" ]; then
  printf 'This deletes every project, account and artifact of the local demo (database %s, %s). Continue? [y/N] ' \
    "$db" "${artifacts#"$root"/}"
  read -r answer
  case "$answer" in y|Y|yes) ;; *) echo "nothing changed"; exit 0 ;; esac
fi
scripts/stop.sh >/dev/null 2>&1
started_colima=0
if ! docker info >/dev/null 2>&1; then colima start >/dev/null 2>&1 || { echo "Docker is not running"; exit 1; }; started_colima=1; fi
was_up=$(docker ps -q --filter name=hmap-postgres-1 --filter status=running 2>/dev/null)
$COMPOSE -f infra/docker-compose.yml up -d --wait >/dev/null 2>&1 || { echo "postgres did not start"; exit 1; }
docker exec -i hmap-postgres-1 psql -U hmap -d postgres -tAq -c "SELECT 1 FROM pg_database WHERE datname='$db'" \
  | grep -q 1 || docker exec -i hmap-postgres-1 psql -U hmap -d postgres -q -c "CREATE DATABASE $db OWNER hmap" >/dev/null
docker exec -i hmap-postgres-1 psql -v ON_ERROR_STOP=1 -U hmap -d "$db" -q \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION hmap; CREATE EXTENSION IF NOT EXISTS vector;" \
  || { echo "could not empty the database"; exit 1; }
(cd backend && uv run --frozen python -c "from hmap.db.migrate import upgrade; upgrade()") >/dev/null \
  || { echo "migrations failed"; exit 1; }
rm -rf "${artifacts:?}" "${demo_state:?}"
mkdir -p "$artifacts"
[ -n "$was_up" ] || $COMPOSE -f infra/docker-compose.yml stop >/dev/null 2>&1
[ "$started_colima" = 1 ] && colima stop >/dev/null 2>&1
echo "reset: empty database (migrated), no artifacts. make demo (or make demo-replay) seeds the demo state again."
