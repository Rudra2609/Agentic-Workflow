"""Fakes for the models tests: an Ollama server, an OpenAI-compatible local server, a memory-tracking backend."""

import asyncio
import json
from typing import Any

import httpx

from hmap.core.llm.base import LLMResponse, LLMUsage
from hmap.core.llm.errors import LLMProviderError
from hmap.core.llm.providers.base import ChatRequest

TAGS = {"models": [
    {"name": "qwen3.5:9b", "digest": "sha256:aaa", "size": 6_600_000_000,
     "details": {"family": "qwen35", "parameter_size": "9.0B", "quantization_level": "Q4_K_M"}},
    {"name": "qwen3.5:4b", "digest": "sha256:bbb", "size": 3_300_000_000,
     "details": {"family": "qwen35", "parameter_size": "4.2B", "quantization_level": "Q4_K_M"}},
    {"name": "nomic-embed-text:latest", "digest": "sha256:ccc", "size": 274_000_000,
     "details": {"family": "nomic-bert", "parameter_size": "137M", "quantization_level": "F16"}}]}


class FakeOllama:
    """``/api/tags`` ``/api/ps`` ``/api/show`` ``/api/chat`` ``/api/generate``; ``up=False`` refuses connections."""

    def __init__(self, resident: dict[str, int] | None = None) -> None:
        self.up = True
        self.resident = resident or {}
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("refused", request=request)
        body = json.loads(request.content) if request.content else {}
        self.requests.append((request.url.path, body))
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        if path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": n, "size": s} for n, s in self.resident.items()]})
        if path == "/api/show":
            return httpx.Response(200, json={"model_info": {"qwen35.context_length": 262144}})
        if path == "/api/generate":
            if body.get("keep_alive") == 0:
                self.resident.pop(body["model"], None)
            return httpx.Response(200, json={"done": True})
        if path == "/api/chat":
            return httpx.Response(200, json={"model": body["model"], "message": {"content": '{"value": "ollama"}'},
                                             "prompt_eval_count": 5, "eval_count": 3, "done": True})
        return httpx.Response(404, json={"error": "not found"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class FakeOpenAILocal:
    """An ``mlx_lm.server`` / ``llama-server`` stand-in."""

    def __init__(self, models: list[str]) -> None:
        self.models = models
        self.bodies: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
        body = json.loads(request.content)
        self.bodies.append(body)
        if any(m["role"] == "system" for m in body["messages"][1:]):
            return httpx.Response(404, json={"error": "System message must be at the beginning."})  # mlx_lm.server
        return httpx.Response(200, json={"model": body["model"], "usage": {"prompt_tokens": 4, "completion_tokens": 2},
                                         "choices": [{"message": {"content": '{"value": "local-server"}'}}]})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class MemoryBackend:
    """A local backend that 'loads' models into a fixed amount of memory and crashes (OOM) when they overflow it."""

    name = "ollama"

    def __init__(self, capacity_gb: float, sizes: dict[str, float], delay: float = 0.005) -> None:
        self.capacity = capacity_gb
        self.sizes = sizes
        self.loaded: dict[str, float] = {}
        self.delay = delay
        self.order: list[str] = []
        self.peak = 0.0
        self.oom = 0

    async def chat(self, request: ChatRequest) -> LLMResponse:
        if request.model not in self.loaded:
            self.loaded[request.model] = self.sizes[request.model]
            used = sum(self.loaded.values())
            self.peak = max(self.peak, used)
            if used > self.capacity:
                self.oom += 1
                raise LLMProviderError("out of memory")
        self.order.append(f"{request.role}:{request.model}")
        await asyncio.sleep(self.delay)
        return LLMResponse(text="ok", usage=LLMUsage(model=request.model, provider=self.name))

    async def unload(self, model: str) -> None:
        self.loaded.pop(model, None)
