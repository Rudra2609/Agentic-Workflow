"""In-memory ``ArtifactStore`` (tests, Phase A) plus helpers shared with ``LocalFSArtifactStore``.

Both stores follow the same rules (research §15, Sprint 1 item 1.11):

- bytes are immutable; a second ``put`` with the same ``artifact_id`` creates the next version and sets
  ``supersedes`` to the previous version number;
- every ``get`` recomputes SHA-256 and compares it with the stored metadata **and** the caller's ref
  (``ArtifactIntegrityError`` on mismatch);
- reads are project-scoped: a ref whose ``access_scope`` is another project is refused (``AuthorizationError``).
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass, field

from hmap.core.contracts import ArtifactRef, utcnow
from hmap.core.errors import ArtifactIntegrityError, AuthorizationError, ErrorCode, HmapError
from hmap.core.ids import new_artifact_id

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class ArtifactNotFound(HmapError):
    """The artifact (or version) does not exist in the caller's project. Not retryable: the input is wrong."""

    code = ErrorCode.INVALID_TASK


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_id(kind: str, value: str) -> str:
    """Ids become path segments in the local store, so only ``[A-Za-z0-9._-]`` (no ``..``) is accepted."""
    if not _SAFE_ID.match(value) or ".." in value:
        raise HmapError(f"invalid {kind} {value!r}", code=ErrorCode.INVALID_TASK)
    return value


def check_scope(ref: ArtifactRef, project_id: str) -> None:
    if ref.access_scope != project_id:
        raise AuthorizationError(
            f"artifact {ref.artifact_id}@{ref.version} belongs to scope {ref.access_scope!r}, not {project_id!r}")


def verify(data: bytes, ref: ArtifactRef, stored: ArtifactRef) -> bytes:
    """Return ``data`` if its hash matches both the stored metadata and the caller's ref."""
    digest = sha256_hex(data)
    if digest != stored.sha256 or len(data) != stored.size_bytes:
        raise ArtifactIntegrityError(
            f"artifact {stored.artifact_id}@{stored.version} is corrupted: sha256 {digest} != {stored.sha256}")
    if ref.sha256 != stored.sha256:
        raise ArtifactIntegrityError(
            f"ref for {ref.artifact_id}@{ref.version} has sha256 {ref.sha256}, store has {stored.sha256}")
    return data


def make_ref(data: bytes, *, scheme: str, project_id: str, artifact_id: str, version: int, artifact_type: str,
             media_type: str, created_by: str, supersedes: int | None) -> ArtifactRef:
    digest = sha256_hex(data)
    return ArtifactRef(
        artifact_id=artifact_id, artifact_type=artifact_type, version=version,
        uri=f"{scheme}://{project_id}/{artifact_id}/v{version}/{digest}", sha256=digest, media_type=media_type,
        size_bytes=len(data), created_by=created_by, created_at=utcnow(), access_scope=project_id,
        supersedes=supersedes,
    )


@dataclass
class _Entry:
    ref: ArtifactRef
    data: bytes


@dataclass
class _Versions:
    entries: list[_Entry] = field(default_factory=list)


class InMemoryArtifactStore:
    """``ArtifactStore`` kept in a dict ``(project_id, artifact_id) -> versions``. Same semantics as the local store."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], _Versions] = {}
        self._lock = asyncio.Lock()

    async def delete_project(self, project_id: str) -> int:
        async with self._lock:
            keys = [k for k in self._items if k[0] == project_id]
            removed = sum(len(self._items[k].entries) for k in keys)
            for k in keys:
                del self._items[k]
        return removed

    async def put(self, data: bytes, *, project_id: str, artifact_type: str, media_type: str, created_by: str,
                  artifact_id: str | None = None) -> ArtifactRef:
        check_id("project_id", project_id)
        artifact_id = check_id("artifact_id", artifact_id or new_artifact_id())
        async with self._lock:
            versions = self._items.setdefault((project_id, artifact_id), _Versions())
            prev = versions.entries[-1].ref.version if versions.entries else None
            ref = make_ref(bytes(data), scheme="memory", project_id=project_id, artifact_id=artifact_id,
                           version=(prev or 0) + 1, artifact_type=artifact_type, media_type=media_type,
                           created_by=created_by, supersedes=prev)
            versions.entries.append(_Entry(ref=ref, data=bytes(data)))
            return ref.model_copy()

    async def get(self, ref: ArtifactRef, *, project_id: str) -> bytes:
        check_scope(ref, project_id)
        entry = self._entry(ref, project_id)
        return verify(entry.data, ref, entry.ref)

    async def latest(self, artifact_id: str, *, project_id: str) -> ArtifactRef | None:
        versions = self._items.get((project_id, artifact_id))
        return versions.entries[-1].ref.model_copy() if versions and versions.entries else None

    async def list(self, project_id: str) -> list[ArtifactRef]:
        refs = [e.ref.model_copy() for (pid, _), v in self._items.items() if pid == project_id for e in v.entries]
        return sorted(refs, key=lambda r: (r.created_at, r.artifact_id, r.version))

    # -- test hook: simulate a corrupted blob (the in-memory analogue of editing the file on disk)
    def _tamper(self, ref: ArtifactRef, data: bytes) -> None:
        self._entry(ref, ref.access_scope).data = data

    def _entry(self, ref: ArtifactRef, project_id: str) -> _Entry:
        versions = self._items.get((project_id, ref.artifact_id))
        for entry in versions.entries if versions else []:
            if entry.ref.version == ref.version:
                return entry
        raise ArtifactNotFound(f"artifact {ref.artifact_id}@{ref.version} not found in project {project_id}")
