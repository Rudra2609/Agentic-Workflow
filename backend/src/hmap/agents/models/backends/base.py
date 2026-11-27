"""One interface for every place a model can run (item 11.3).

A backend answers the gateway's :class:`~hmap.core.llm.providers.base.ChatRequest` (so it can be handed to the
gateway as the router's local provider, ``RoutePlan.local``), reports its health (cached 10 s) and the models it
serves. The same request (with a JSON schema) works on each one; the gateway validates and repairs JSON for all of
them, so a backend without native schema support only gets the schema as a system hint.
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from hmap.core.config import Settings
from hmap.core.llm.base import LLMResponse
from hmap.core.llm.providers.base import ChatRequest

if TYPE_CHECKING:
    from hmap.core.llm.cloud import CloudRouter

HEALTH_TTL_S = 10.0


@dataclass
class Health:
    ok: bool
    detail: str = ""
    models: list[str] = field(default_factory=list)
    checked_at: float = field(default_factory=time.monotonic)


class Backend(Protocol):
    name: str          # ollama / mlx / llamacpp / cloud
    kind: str

    async def health(self, *, fresh: bool = False) -> Health: ...

    async def chat(self, request: ChatRequest) -> LLMResponse: ...

    async def aclose(self) -> None: ...


class CachedHealth:
    """Mixin: ``health()`` re-probes at most every ``HEALTH_TTL_S``."""

    _health: Health | None = None

    async def _probe(self) -> Health:
        raise NotImplementedError

    async def health(self, *, fresh: bool = False) -> Health:
        if fresh or self._health is None or time.monotonic() - self._health.checked_at > HEALTH_TTL_S:
            self._health = await self._probe()
        return self._health


def build_backends(settings: Settings, *, cloud_router: "CloudRouter | None" = None,
                   client: Any = None) -> dict[str, Backend]:
    """Every configured backend: Ollama always (it may be down), MLX / llama.cpp when their URL is set, the cloud
    pool when keys exist."""
    from hmap.agents.models.backends.cloud import CloudPoolBackend
    from hmap.agents.models.backends.local import OllamaBackend, OpenAILocalBackend

    out: dict[str, Backend] = {"ollama": OllamaBackend(settings.ollama_base_url, num_ctx=settings.ollama_num_ctx,
                                                       client=client)}
    if settings.mlx_base_url:
        out["mlx"] = OpenAILocalBackend("mlx", settings.mlx_base_url, client=client)
    if settings.llamacpp_base_url:
        out["llamacpp"] = OpenAILocalBackend("llamacpp", settings.llamacpp_base_url, client=client)
    if cloud_router is not None:
        out["cloud"] = CloudPoolBackend(cloud_router)
    return out
