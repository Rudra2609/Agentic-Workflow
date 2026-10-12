"""Context service interface (research §13-14, Sprint 1 item 1.10). Immutable versioned snapshots; assignments
pin ``CTX@v``. Selective/token-budgeted views are Sprint-1 stretch (doc: sprint-01 §3.4)."""

from typing import Any, Protocol

from hmap.core.contracts import ContextRef
from hmap.core.contracts.common import Contract


class ContextSnapshot(Contract):
    context_id: str
    version: int
    parent_version: int | None
    project_id: str
    author: str
    content: dict[str, Any]
    content_sha256: str
    change_summary: str = ""


class ContextStore(Protocol):
    async def create(self, project_id: str, content: dict[str, Any], *, author: str,
                     context_id: str | None = None, change_summary: str = "") -> ContextRef:
        """New context (version 1) or, with an existing ``context_id``, the next version."""

    async def get(self, ref: ContextRef) -> ContextSnapshot: ...

    async def latest(self, context_id: str) -> ContextRef: ...

    async def is_stale(self, ref: ContextRef) -> bool:
        """True if a newer version exists (agent must request a rebase: NEEDS_REBASE)."""
