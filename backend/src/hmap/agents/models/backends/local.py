"""Local backends: Ollama (the existing provider) and OpenAI-compatible local servers (``mlx_lm.server``,
llama.cpp ``llama-server``). Both chat through the gateway's request type, so the router can hand them to the
gateway as ``RoutePlan.local``."""

import dataclasses
import json
from typing import Any

import httpx

from hmap.agents.models.backends.base import CachedHealth, Health
from hmap.core.errors import HmapError
from hmap.core.llm.base import LLMResponse
from hmap.core.llm.providers.base import ChatRequest
from hmap.core.llm.providers.ollama import OllamaProvider
from hmap.core.llm.providers.openai_compat import OpenAICompatProvider


class OllamaBackend(CachedHealth):
    kind = "ollama"

    def __init__(self, base_url: str, *, num_ctx: int | None = 8192, client: httpx.AsyncClient | None = None,
                 keep_alive: str | None = "30m") -> None:
        self.name = "ollama"
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0))
        self._owns = client is None
        self.provider = OllamaProvider(self.base_url, self._client, num_ctx=num_ctx, keep_alive=keep_alive)

    async def _probe(self) -> Health:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=3.0)
            resp.raise_for_status()
            return Health(True, "answering", [str(m["name"]) for m in resp.json().get("models", [])])
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return Health(False, f"not answering at {self.base_url} ({type(exc).__name__})")

    async def chat(self, request: ChatRequest) -> LLMResponse:
        return await self.provider.chat(request)

    async def resident(self) -> dict[str, float]:
        try:
            resp = await self._client.get(f"{self.base_url}/api/ps", timeout=3.0)
            return {str(m["name"]): float(m.get("size", 0)) / 1e9 for m in resp.json().get("models", [])}
        except (httpx.HTTPError, ValueError, KeyError):
            return {}

    async def preload(self, model: str, *, keep_alive: str = "30m") -> float:
        """Load ``model`` without generating (warm-up, item 11.18); returns seconds."""
        import time

        started = time.perf_counter()
        path = "/api/embed" if "embed" in model else "/api/generate"
        body: dict[str, Any] = {"model": model, "keep_alive": keep_alive}
        if path == "/api/embed":
            body["input"] = "warm-up"
        resp = await self._client.post(f"{self.base_url}{path}", json=body, timeout=180.0)
        resp.raise_for_status()
        return time.perf_counter() - started

    async def unload(self, model: str) -> None:
        await self._client.post(f"{self.base_url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=30.0)

    async def aclose(self) -> None:
        if self._owns:
            await self._client.aclose()


SCHEMA_HINT = "Respond with a single JSON object that matches this JSON Schema, and nothing else:\n"


def one_system_message(request: ChatRequest) -> ChatRequest:
    """Qwen's chat template accepts one system message, first (``mlx_lm.server`` answers "System message must be
    at the beginning"). The OpenAI-compatible provider adds the JSON-schema hint as a second system message, so the
    hint goes into the request's own system message here (the same words) and the schema is not sent again; the
    gateway still validates the answer against the schema."""
    if request.json_schema is None:
        return request
    hint = SCHEMA_HINT + json.dumps(request.json_schema, sort_keys=True)
    msgs = list(request.messages)
    if msgs and msgs[0].get("role") == "system":
        msgs[0] = {"role": "system", "content": f"{hint}\n\n{msgs[0]['content']}"}
    else:
        msgs.insert(0, {"role": "system", "content": hint})
    return dataclasses.replace(request, messages=msgs, json_schema=None)


class OpenAILocalBackend(CachedHealth):
    """``mlx_lm.server`` / ``llama-server``: OpenAI-compatible, no key. Model ids in the registry are
    ``<backend>:<server model id>``; the prefix is removed before the call."""

    def __init__(self, name: str, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self.name = self.kind = name
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=5.0))
        self._owns = client is None
        # mlx_lm.server / llama-server do not all honour response_format: the schema goes as a system hint and the
        # gateway validates (and repairs) the answer, as for Gemini
        # Qwen 3.5 thinks by default under mlx_lm.server / llama-server: with the gateway's think=False the template
        # is told so (else the answer budget goes to hidden reasoning and the content comes back empty)
        self.provider = OpenAICompatProvider(self.base_url, None, self._client, name=name, json_mode="none",
                                             send_seed=True,
                                             no_think={"": {"chat_template_kwargs": {"enable_thinking": False}}})

    async def _probe(self) -> Health:
        try:
            resp = await self._client.get(f"{self.base_url}/models", timeout=3.0)
            resp.raise_for_status()
            return Health(True, "answering", [f"{self.name}:{m['id']}" for m in resp.json().get("data", [])])
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            return Health(False, f"not answering at {self.base_url} ({type(exc).__name__})")

    async def chat(self, request: ChatRequest) -> LLMResponse:
        model = request.model.removeprefix(f"{self.name}:")
        try:
            resp = await self.provider.send(one_system_message(request), api_key="local", model=model)
        except HmapError:
            raise
        return resp.model_copy(update={"usage": resp.usage.model_copy(update={"provider": self.name})})

    async def aclose(self) -> None:
        if self._owns:
            await self._client.aclose()
