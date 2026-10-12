"""Helpers for LLM tests: an ``httpx.MockTransport`` fake of Ollama. No real network, no real Ollama."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from hmap.core.config import Settings
from hmap.core.llm import OllamaProvider


class FakeOllamaServer:
    """Records every request; answers ``/api/chat`` from a reply queue (last repeats) or a callable."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.replies: list[str] = ["hello"]
        self.chat_handler: Callable[[dict[str, Any]], httpx.Response] | None = None

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        path = request.url.path
        if path == "/api/chat":
            if self.chat_handler is not None:
                return self.chat_handler(body)
            n_chat = sum(1 for r in self.requests if r.url.path == "/api/chat")
            text = self.replies[min(n_chat - 1, len(self.replies) - 1)]
            return httpx.Response(200, json={
                "model": body["model"], "message": {"role": "assistant", "content": text}, "done": True,
                "prompt_eval_count": 11, "eval_count": 7, "total_duration": 2_000_000_000,
                "load_duration": 1_000_000, "eval_duration": 500_000_000})
        if path == "/api/embed":
            return httpx.Response(200, json={"model": body["model"],
                                             "embeddings": [[0.1, 0.2, 0.3] for _ in body["input"]]})
        if path == "/api/generate":
            return httpx.Response(200, json={"model": body["model"], "done": True, "done_reason": "unload"})
        return httpx.Response(404, json={"error": "not found"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def server() -> FakeOllamaServer:
    return FakeOllamaServer()


@pytest.fixture
def ollama(server: FakeOllamaServer) -> OllamaProvider:
    return OllamaProvider("http://ollama.test:11434", server.client())


@pytest.fixture
def settings(tmp_path: Any) -> Settings:
    return Settings(llm_mode="live", llm_cache_dir=tmp_path / "llm_cache",
                    role_map={"reasoner": "qwen3:8b", "embed": "nomic-embed-text"},
                    ollama_base_url="http://ollama.test:11434")
