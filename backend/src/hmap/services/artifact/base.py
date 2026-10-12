"""Artifact store interface (research §15, Sprint 1 item 1.11). Implementation: ``LocalFSArtifactStore``
(write-once files under HMAP_ARTIFACT_ROOT, SHA-256 verified on read) + ``InMemoryArtifactStore`` for tests."""

from typing import Protocol

from hmap.core.contracts import ArtifactRef


class ArtifactStore(Protocol):
    async def put(self, data: bytes, *, project_id: str, artifact_type: str, media_type: str, created_by: str,
                  artifact_id: str | None = None) -> ArtifactRef:
        """Store bytes immutably. Same ``artifact_id`` => next version (``supersedes`` = previous)."""

    async def get(self, ref: ArtifactRef, *, project_id: str) -> bytes:
        """Return bytes after verifying SHA-256 (ArtifactIntegrityError) and scope (AuthorizationError)."""

    async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None: ...

    async def list(self, project_id: str) -> list[ArtifactRef]: ...

    async def delete_project(self, project_id: str) -> int:
        """Erase every artifact of a deleted project (the only way bytes ever leave the store); returns the number
        of versions removed."""
