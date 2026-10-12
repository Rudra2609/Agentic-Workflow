"""Fixtures for the Postgres integration tests (every module here is marked ``integration``).

- ``pg_url``: ``$HMAP_TEST_DATABASE_URL`` (default: the ``hmap_test`` database of ``make infra-up``). If it cannot be
  reached, every test that needs it is SKIPPED with the reason.
- ``pg_schema``: once per test run, the migrations are applied (``alembic upgrade head``) into a fresh, uniquely
  named schema, dropped again at the end — runs never see each other's data and never touch ``public``.
- ``db``: a ``Database`` bound to that schema, all tables truncated (identities restarted) before each test.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest

from hmap.core.bus.base import Bus
from hmap.core.bus.memory import InMemoryBus
from hmap.db import Database, conninfo, upgrade
from hmap.db.tables import ALL_TABLES
from tests.core.bus._helpers import MAX_ATTEMPTS, RETRY_DELAYS_S

DEFAULT_TEST_URL = "postgresql+psycopg://hmap:hmap@127.0.0.1:5433/hmap_test"


def database_url_for_tests() -> str:
    return os.environ.get("HMAP_TEST_DATABASE_URL") or DEFAULT_TEST_URL


def _redacted(url: str) -> str:
    head, sep, tail = url.rpartition("@")
    return f"{head.split(':')[0]}:...@{tail}" if sep else url


def _unreachable_reason(url: str) -> str | None:
    try:
        psycopg.connect(conninfo(url), connect_timeout=3).close()
    except psycopg.Error as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        hint = (" Another Postgres server (e.g. a Homebrew one) may be listening on that port instead of the Docker "
                "container." if "does not exist" in first else "")
        return (f"Postgres test database not usable at {_redacted(url)} ({first}).{hint} Start it with "
                f"`make infra-up` or point HMAP_TEST_DATABASE_URL at a reachable database.")
    return None


def drop_schema(url: str, schema: str) -> None:
    with psycopg.connect(conninfo(url), autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = database_url_for_tests()
    reason = _unreachable_reason(url)
    if reason:
        pytest.skip(reason)
    return url


@pytest.fixture(scope="session")
def pg_schema(pg_url: str) -> Iterator[str]:
    schema = f"hmap_t_{uuid.uuid4().hex[:12]}"
    try:
        upgrade(pg_url, schema=schema)
        yield schema
    finally:
        drop_schema(pg_url, schema)


@pytest.fixture
async def db(pg_url: str, pg_schema: str) -> AsyncIterator[Database]:
    database = Database(pg_url, schema=pg_schema, max_size=20)
    async with database.connection() as conn:
        await conn.execute(f"TRUNCATE {', '.join(ALL_TABLES)} RESTART IDENTITY")
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def bus() -> AsyncIterator[Bus]:
    b = InMemoryBus(max_attempts=MAX_ATTEMPTS, retry_delays_s=RETRY_DELAYS_S)
    await b.start()
    try:
        yield b
    finally:
        await b.close()
