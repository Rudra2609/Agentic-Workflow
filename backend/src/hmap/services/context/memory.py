"""In-memory ``ContextStore`` (Sprint 1 item 1.10, research §13-14). Postgres ``contexts`` table in Phase B.

Contexts are immutable snapshots ``CTX-42@1, @2, ...``; each records its parent version, author, a SHA-256 of the
canonical JSON content and a change summary. Assignments pin a version (``ContextRef``); ``is_stale`` tells an agent
that a newer version exists so it must request a rebase (``NEEDS_REBASE``). Content is deep-copied on the way in and
out, so callers can never mutate a stored snapshot.
"""

import asyncio
import copy
import hashlib
import json
from typing import Any

from hmap.core.contracts import ContextRef
from hmap.core.errors import AuthorizationError, ErrorCode, HmapError
from hmap.core.ids import new_context_id
from hmap.services.context.base import ContextSnapshot


class ContextNotFound(HmapError):
    code = ErrorCode.MISSING_CONTEXT


def content_sha256(content: dict[str, Any]) -> str:
    """Hash of the canonical JSON form (sorted keys, no whitespace); raises TypeError for non-JSON content."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class InMemoryContextStore:
    def __init__(self) -> None:
        self._snapshots: dict[str, list[ContextSnapshot]] = {}
        self._lock = asyncio.Lock()

    async def create(self, project_id: str, content: dict[str, Any], *, author: str,
                     context_id: str | None = None, change_summary: str = "") -> ContextRef:
        digest = content_sha256(content)
        frozen = copy.deepcopy(content)
        async with self._lock:
            cid = context_id or new_context_id()
            history = self._snapshots.setdefault(cid, [])
            parent = history[-1] if history else None
            if parent is not None and parent.project_id != project_id:
                raise AuthorizationError(f"context {cid} belongs to project {parent.project_id}, not {project_id}")
            snap = ContextSnapshot(
                context_id=cid, version=(parent.version + 1) if parent else 1,
                parent_version=parent.version if parent else None, project_id=project_id, author=author,
                content=frozen, content_sha256=digest,
                change_summary=change_summary or ("initial" if parent is None else ""),
            )
            history.append(snap)
            return ContextRef(context_id=cid, version=snap.version)

    async def get(self, ref: ContextRef) -> ContextSnapshot:
        history = self._snapshots.get(ref.context_id)
        if not history or ref.version > len(history):
            raise ContextNotFound(f"context {ref.context_id}@{ref.version} not found")
        return history[ref.version - 1].model_copy(deep=True)

    async def latest(self, context_id: str) -> ContextRef:
        history = self._snapshots.get(context_id)
        if not history:
            raise ContextNotFound(f"context {context_id} not found")
        return ContextRef(context_id=context_id, version=history[-1].version)

    async def is_stale(self, ref: ContextRef) -> bool:
        return (await self.latest(ref.context_id)).version > ref.version

    async def history(self, context_id: str) -> list[ContextSnapshot]:
        """All versions, oldest first (UI / audit)."""
        return [s.model_copy(deep=True) for s in self._snapshots.get(context_id, [])]
