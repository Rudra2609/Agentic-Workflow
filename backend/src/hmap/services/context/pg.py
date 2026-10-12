"""Postgres ``ContextStore`` (Sprint 1 item 1.10; research §13-14) on the ``contexts`` table (PK
``(context_id, version)``). Same behaviour as ``InMemoryContextStore``: immutable versioned snapshots, SHA-256 of the
canonical JSON content, cross-project writes refused, ``ContextNotFound`` for unknown ids/versions.

New versions of one context are serialised with a transaction-scoped advisory lock on the context id, so concurrent
writers get consecutive versions instead of a unique-key error.
"""

import copy
from typing import Any

from psycopg.types.json import Jsonb

from hmap.core.contracts import ContextRef
from hmap.core.errors import AuthorizationError
from hmap.core.ids import new_context_id
from hmap.db.database import Database
from hmap.services.context.base import ContextSnapshot
from hmap.services.context.memory import ContextNotFound, content_sha256

_COLUMNS = "context_id, version, parent_version, project_id, author, content, content_sha256, change_summary"


def _snapshot(row: dict[str, Any]) -> ContextSnapshot:
    return ContextSnapshot(**{k: row[k] for k in ContextSnapshot.model_fields})


class PostgresContextStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, project_id: str, content: dict[str, Any], *, author: str,
                     context_id: str | None = None, change_summary: str = "") -> ContextRef:
        digest = content_sha256(content)              # TypeError for non-JSON content, before touching the DB
        frozen = copy.deepcopy(content)
        cid = context_id or new_context_id()
        async with self.db.transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"hmap.context:{cid}",))
            cur = await conn.execute(
                "SELECT version, project_id FROM contexts WHERE context_id = %s ORDER BY version DESC LIMIT 1",
                (cid,))
            parent = await cur.fetchone()
            if parent is not None and parent["project_id"] != project_id:
                raise AuthorizationError(f"context {cid} belongs to project {parent['project_id']}, not {project_id}")
            parent_version: int | None = parent["version"] if parent else None
            version = (parent_version or 0) + 1
            await conn.execute(
                f"INSERT INTO contexts ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (cid, version, parent_version, project_id, author, Jsonb(frozen), digest,
                 change_summary or ("initial" if parent is None else "")))
        return ContextRef(context_id=cid, version=version)

    async def get(self, ref: ContextRef) -> ContextSnapshot:
        rows = await self.db.fetch(f"SELECT {_COLUMNS} FROM contexts WHERE context_id = %s AND version = %s",
                                   (ref.context_id, ref.version))
        if not rows:
            raise ContextNotFound(f"context {ref.context_id}@{ref.version} not found")
        return _snapshot(rows[0])

    async def latest(self, context_id: str) -> ContextRef:
        rows = await self.db.fetch("SELECT max(version) AS v FROM contexts WHERE context_id = %s", (context_id,))
        if not rows or rows[0]["v"] is None:
            raise ContextNotFound(f"context {context_id} not found")
        return ContextRef(context_id=context_id, version=rows[0]["v"])

    async def is_stale(self, ref: ContextRef) -> bool:
        return (await self.latest(ref.context_id)).version > ref.version

    async def history(self, context_id: str) -> list[ContextSnapshot]:
        """All versions, oldest first (UI / audit)."""
        rows = await self.db.fetch(f"SELECT {_COLUMNS} FROM contexts WHERE context_id = %s ORDER BY version",
                                   (context_id,))
        return [_snapshot(r) for r in rows]
