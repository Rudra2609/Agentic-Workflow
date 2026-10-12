"""Migration 001: upgrade from an empty schema, downgrade, upgrade again; schema == ``hmap.db.tables`` metadata;
the §34 unique keys and the append-only ``events`` table are enforced by the database itself."""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, pool

from hmap.db import conninfo, current_revision, database_url, downgrade, upgrade
from hmap.db.database import session_options
from hmap.db.tables import ALL_TABLES, metadata
from tests.db.conftest import drop_schema

pytestmark = pytest.mark.integration


@pytest.fixture
def scratch_schema(pg_url: str) -> Iterator[str]:
    schema = f"hmap_m_{uuid.uuid4().hex[:12]}"
    try:
        yield schema
    finally:
        drop_schema(pg_url, schema)


def _tables(url: str, schema: str) -> set[str]:
    with psycopg.connect(conninfo(url)) as conn:
        rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                            (schema,)).fetchall()
    return {r[0] for r in rows}


def test_upgrade_downgrade_upgrade(pg_url: str, scratch_schema: str) -> None:
    assert current_revision(pg_url, schema=scratch_schema) is None
    upgrade(pg_url, schema=scratch_schema)
    assert current_revision(pg_url, schema=scratch_schema) == "001b"
    assert _tables(pg_url, scratch_schema) == {*ALL_TABLES, "alembic_version"}
    upgrade(pg_url, schema=scratch_schema)                       # idempotent at head
    downgrade(pg_url, schema=scratch_schema)
    assert current_revision(pg_url, schema=scratch_schema) is None
    assert _tables(pg_url, scratch_schema) <= {"alembic_version"}
    upgrade(pg_url, schema=scratch_schema)
    assert current_revision(pg_url, schema=scratch_schema) == "001b"
    assert _tables(pg_url, scratch_schema) == {*ALL_TABLES, "alembic_version"}


def test_migrated_schema_matches_table_models(pg_url: str, pg_schema: str) -> None:
    engine = create_engine(database_url(pg_url), poolclass=pool.NullPool,
                           connect_args={"options": session_options(pg_schema)})
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(ctx, metadata)
    finally:
        engine.dispose()
    assert diff == []


def _exec(url: str, schema: str, sql: str, params: tuple[object, ...] = ()) -> None:
    with psycopg.connect(conninfo(url), options=session_options(schema), autocommit=True) as conn:
        conn.execute(sql, params)  # type: ignore[arg-type]


@pytest.mark.parametrize(("setup", "duplicate"), [
    ("INSERT INTO inbox (consumer_id, message_id) VALUES ('c', 'm')",
     "INSERT INTO inbox (consumer_id, message_id) VALUES ('c', 'm')"),
    ("INSERT INTO executions (execution_id, task_id, attempt, status, created_at, updated_at)"
     " VALUES ('E-1', 'T-1', 1, 'PENDING', now(), now())",
     "INSERT INTO executions (execution_id, task_id, attempt, status, created_at, updated_at)"
     " VALUES ('E-2', 'T-1', 1, 'PENDING', now(), now())"),
    ("INSERT INTO contexts (context_id, version, project_id, author, content, content_sha256)"
     " VALUES ('CTX-1', 1, 'P', 'a', '{}', 'x')",
     "INSERT INTO contexts (context_id, version, project_id, author, content, content_sha256)"
     " VALUES ('CTX-1', 1, 'P', 'b', '{}', 'y')"),
    ("INSERT INTO artifacts (artifact_id, version, project_id, artifact_type, media_type, size_bytes, sha256, uri,"
     " created_by, created_at) VALUES ('A', 1, 'P', 't', 'm', 1, 's', 'u', 'c', now())",
     "INSERT INTO artifacts (artifact_id, version, project_id, artifact_type, media_type, size_bytes, sha256, uri,"
     " created_by, created_at) VALUES ('A', 1, 'P', 't', 'm', 2, 's2', 'u2', 'c', now())"),
], ids=["inbox", "task_attempt", "context_version", "artifact_version"])
def test_unique_keys_enforced(pg_url: str, scratch_schema: str, setup: str, duplicate: str) -> None:
    upgrade(pg_url, schema=scratch_schema)
    _exec(pg_url, scratch_schema, setup)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _exec(pg_url, scratch_schema, duplicate)


def test_events_are_append_only(pg_url: str, scratch_schema: str) -> None:
    upgrade(pg_url, schema=scratch_schema)
    _exec(pg_url, scratch_schema, "INSERT INTO events (event_id, event_type, aggregate_id, aggregate_version,"
                                  " occurred_at) VALUES ('ev-1', 'task.created', 'T-1', 1, now())")
    with pytest.raises(psycopg.errors.RestrictViolation):
        _exec(pg_url, scratch_schema, "UPDATE events SET event_type = 'x'")
    with pytest.raises(psycopg.errors.RestrictViolation):
        _exec(pg_url, scratch_schema, "DELETE FROM events")
