"""Artifact metadata in Postgres (Sprint 1 item 1.11, research §15/§18): the ``artifacts`` table, unique
``(artifact_id, version)``. Independent of ``LocalFSArtifactStore`` (which keeps ``meta.json`` next to the bytes);
a later store can write the bytes as today and record/lookup the ``ArtifactRef`` here.

Project scope: ``project_id`` = ``ArtifactRef.access_scope``; lookups for another project return ``None`` / empty.
"""

import builtins
from typing import Any

from psycopg import errors as pg_errors

from hmap.core.contracts import ArtifactRef
from hmap.core.errors import ArtifactConflict
from hmap.db.database import Database

_COLUMNS = ("artifact_id, version, project_id, artifact_type, media_type, size_bytes, sha256, uri, created_by,"
            " created_at, supersedes")


def _ref(row: dict[str, Any]) -> ArtifactRef:
    return ArtifactRef(artifact_id=row["artifact_id"], artifact_type=row["artifact_type"], version=row["version"],
                       uri=row["uri"], sha256=row["sha256"], media_type=row["media_type"],
                       size_bytes=row["size_bytes"], created_by=row["created_by"], created_at=row["created_at"],
                       access_scope=row["project_id"], supersedes=row["supersedes"])


class PgArtifactMetadata:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(self, ref: ArtifactRef) -> ArtifactRef:
        """Insert the metadata row; an existing ``(artifact_id, version)`` -> ``ArtifactConflict`` (write-once)."""
        try:
            await self.db.fetch(
                f"INSERT INTO artifacts ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " RETURNING artifact_id",
                (ref.artifact_id, ref.version, ref.access_scope, ref.artifact_type, ref.media_type, ref.size_bytes,
                 ref.sha256, ref.uri, ref.created_by, ref.created_at, ref.supersedes))
        except pg_errors.UniqueViolation as exc:
            raise ArtifactConflict(f"artifact {ref.artifact_id}@{ref.version} already exists") from exc
        return ref

    async def get(self, artifact_id: str, version: int, *, project_id: str) -> ArtifactRef | None:
        rows = await self.db.fetch(
            f"SELECT {_COLUMNS} FROM artifacts WHERE artifact_id = %s AND version = %s AND project_id = %s",
            (artifact_id, version, project_id))
        return _ref(rows[0]) if rows else None

    async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None:
        rows = await self.db.fetch(
            f"SELECT {_COLUMNS} FROM artifacts WHERE artifact_id = %s AND project_id = %s"
            " ORDER BY version DESC LIMIT 1", (artifact_id, project_id))
        return _ref(rows[0]) if rows else None

    async def next_version(self, artifact_id: str) -> int:
        """1 + the highest recorded version (0 rows -> 1). Racy by itself; ``record`` is the arbiter."""
        rows = await self.db.fetch("SELECT coalesce(max(version), 0) + 1 AS v FROM artifacts WHERE artifact_id = %s",
                                   (artifact_id,))
        return int(rows[0]["v"])

    async def list(self, project_id: str) -> builtins.list[ArtifactRef]:
        """Same order as the stores: ``(created_at, artifact_id, version)``."""
        rows = await self.db.fetch(
            f'SELECT {_COLUMNS} FROM artifacts WHERE project_id = %s ORDER BY created_at, artifact_id COLLATE "C",'
            " version", (project_id,))
        return [_ref(r) for r in rows]
