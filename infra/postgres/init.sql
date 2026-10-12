-- Idempotent setup, run by `make infra-up` via scripts/infra_init.sh (docker exec, works from any disk).
-- Schema itself is managed by Alembic (backend/alembic); this only creates the test database and extensions.
SELECT 'CREATE DATABASE hmap_test OWNER hmap' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'hmap_test')\gexec
\connect hmap
CREATE EXTENSION IF NOT EXISTS vector;
\connect hmap_test
CREATE EXTENSION IF NOT EXISTS vector;
