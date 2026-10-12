"""Async Postgres access for the ``pg_*`` stores: URL helpers + a small psycopg 3 connection pool.

Why not ``sqlalchemy.ext.asyncio``? It needs the ``greenlet`` package, which is not installed (SQLAlchemy 2.1 made
it an opt-in extra and the project pins no new dependencies). psycopg 3 is natively async, so the stores talk to
it directly with plain SQL; SQLAlchemy (sync) + Alembic are used for the schema and migrations only.

    db = Database("postgresql+psycopg://hmap:hmap@127.0.0.1:5433/hmap")   # or Database() -> $HMAP_DATABASE_URL
    async with db.transaction() as conn:      # BEGIN ... COMMIT (ROLLBACK on exception)
        await conn.execute("...")
    async with db.connection() as conn:       # autocommit: every statement commits on its own
        ...
    await db.close()                          # on shutdown

Every connection runs with ``TimeZone=UTC`` (timestamptz values come back as aware UTC datetimes) and, when
``schema`` is given, ``search_path=<schema>, public`` (tests migrate into a throw-away schema).
"""

import asyncio
import contextlib
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import psycopg
from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus
from psycopg.rows import DictRow, dict_row

DEFAULT_DATABASE_URL = "postgresql+psycopg://hmap:hmap@127.0.0.1:5433/hmap"
_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

Conn = AsyncConnection[DictRow]


def database_url(url: str | None = None) -> str:
    """``url`` or ``$HMAP_DATABASE_URL`` or the dev default, normalised to the ``postgresql+psycopg://`` form."""
    raw = url or os.environ.get("HMAP_DATABASE_URL") or DEFAULT_DATABASE_URL
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://", "postgresql://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    raise ValueError("database URL must start with postgresql:// or postgresql+psycopg://")


def conninfo(url: str | None = None) -> str:
    """The libpq form of :func:`database_url` (``postgresql://...``) for psycopg."""
    return "postgresql://" + database_url(url)[len("postgresql+psycopg://"):]


def check_schema_name(schema: str) -> str:
    if not _SCHEMA_RE.match(schema):
        raise ValueError(f"invalid schema name {schema!r} (lower-case letters, digits, underscore)")
    return schema


def session_options(schema: str | None = None) -> str:
    """libpq ``options`` used by every connection (async pool and Alembic alike)."""
    opts = "-c TimeZone=UTC"
    if schema:
        opts += f" -c search_path={check_schema_name(schema)},public"
    return opts


class PoolTimeout(psycopg.OperationalError):
    """No connection became free within ``acquire_timeout``."""


class Database:
    """A bounded pool of autocommit ``AsyncConnection``s (dict rows). Cheap to create; call :meth:`close` once.

    Connections are opened lazily (up to ``max_size``), reused LIFO, and dropped when broken. A connection that is
    released while still inside a transaction is rolled back first. Not shareable across event loops.
    """

    def __init__(self, url: str | None = None, *, schema: str | None = None, max_size: int = 10,
                 connect_timeout: float = 5.0, acquire_timeout: float = 30.0) -> None:
        if max_size < 1:
            raise ValueError("max_size must be >= 1")
        self.url = database_url(url)
        self.schema = check_schema_name(schema) if schema else None
        self.max_size = max_size
        self.connect_timeout = connect_timeout
        self.acquire_timeout = acquire_timeout
        self._conninfo = conninfo(self.url)
        self._idle: list[Conn] = []
        self._slots = asyncio.Semaphore(max_size)
        self._closed = False

    def __repr__(self) -> str:   # never print the password
        safe = re.sub(r"//([^:/@]+):[^@]*@", r"//\1:***@", self.url)
        return f"Database({safe!r}, schema={self.schema!r})"

    # ------------------------------------------------------------------ connections

    async def _open(self) -> Conn:
        return await AsyncConnection.connect(
            self._conninfo, autocommit=True, row_factory=dict_row,
            connect_timeout=max(1, round(self.connect_timeout)), options=session_options(self.schema))

    @contextlib.asynccontextmanager
    async def connection(self) -> AsyncIterator[Conn]:
        """Borrow an autocommit connection. Use ``conn.transaction()`` (or :meth:`transaction`) for a unit of work."""
        if self._closed:
            raise RuntimeError("Database is closed")
        try:
            await asyncio.wait_for(self._slots.acquire(), self.acquire_timeout)
        except TimeoutError as exc:
            raise PoolTimeout(f"no free connection within {self.acquire_timeout}s (max_size={self.max_size})") from exc
        conn: Conn | None = None
        try:
            while self._idle and conn is None:
                candidate = self._idle.pop()
                if candidate.closed or candidate.broken:
                    continue
                conn = candidate
            if conn is None:
                conn = await self._open()
            yield conn
        finally:
            try:
                if conn is not None:
                    await self._release(conn)
            finally:
                self._slots.release()

    async def _release(self, conn: Conn) -> None:
        if conn.closed or conn.broken:
            return
        try:
            if conn.info.transaction_status != TransactionStatus.IDLE:
                await conn.rollback()
        except psycopg.Error:
            await conn.close()
            return
        if self._closed:
            await conn.close()
        else:
            self._idle.append(conn)

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[Conn]:
        """One database transaction: COMMIT when the block exits normally, ROLLBACK on an exception."""
        async with self.connection() as conn, conn.transaction():
            yield conn

    # ------------------------------------------------------------------ helpers

    async def fetch(self, query: str, params: Any = None) -> list[DictRow]:
        async with self.connection() as conn:
            cur = await conn.execute(query, params)
            return await cur.fetchall()

    async def ping(self) -> bool:
        try:
            await self.fetch("SELECT 1")
        except psycopg.Error:
            return False
        return True

    async def close(self) -> None:
        """Close idle connections; connections still borrowed are closed when released."""
        self._closed = True
        idle, self._idle = self._idle, []
        for conn in idle:
            with contextlib.suppress(psycopg.Error):
                await conn.close()

    async def __aenter__(self) -> "Database":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
