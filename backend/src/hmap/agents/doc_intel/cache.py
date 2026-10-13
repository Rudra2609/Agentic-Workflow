"""Small key -> text cache for expensive steps (vision OCR of a page, LLM extraction of a chunk), so a redelivered task
or a re-run on the same document does no model work twice. The agent backs it with the project's artifact store;
tests and the eval harness use :class:`MemoryCache`."""

import hashlib
from typing import Protocol


class ResultCache(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def put(self, key: str, value: str) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def put(self, key: str, value: str) -> None:
        self.data[key] = value


def cache_key(kind: str, *parts: str | bytes) -> str:
    """``<kind>-<sha256 prefix>``: only ``[a-z0-9-]``, safe as an artifact id."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part if isinstance(part, bytes) else part.encode())
        h.update(b"\x00")
    return f"{kind}-{h.hexdigest()[:40]}"
