"""The Sprint-1 team key pool as a backend (per-key cooldown, auth disable, the ``cloud_ok`` flag stay in the
gateway / ``CloudRouter``). ``ChatRequest.model`` is ``provider:model``."""

from hmap.agents.models.backends.base import CachedHealth, Health
from hmap.core.llm.base import LLMResponse
from hmap.core.llm.cloud import CloudRouter
from hmap.core.llm.errors import LLMProviderError
from hmap.core.llm.providers.base import ChatRequest


class CloudPoolBackend(CachedHealth):
    kind = "cloud"

    def __init__(self, router: CloudRouter) -> None:
        self.name = "cloud"
        self.router = router

    async def _probe(self) -> Health:
        usable = self.router.available()
        routes = sorted({f"{p}:{m}" for rs in self.router.role_map.values() for p, m in rs})
        return Health(any(usable.values()), ", ".join(f"{p}: {n} key(s) usable" for p, n in usable.items()), routes)

    async def chat(self, request: ChatRequest) -> LLMResponse:
        provider, _, model = request.model.partition(":")
        resp = await self.router.chat(request, plugin="models", routes=[(provider, model)])
        if resp is None:
            raise LLMProviderError(f"every {provider} key is cooling down, disabled or failing")
        return resp

    async def aclose(self) -> None:
        return None
