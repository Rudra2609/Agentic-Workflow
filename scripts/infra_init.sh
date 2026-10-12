#!/usr/bin/env bash
# Idempotent DB setup inside the running Postgres container (test database + pgvector). Called by `make infra-up`.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
docker exec -i hmap-postgres-1 psql -v ON_ERROR_STOP=1 -U hmap -d postgres -q < "$here/../infra/postgres/init.sql"
echo "postgres ready: databases hmap + hmap_test, extension vector (host port 5433)"
