"""Ollama provider (doc 02 §2.1): native ``/api/chat`` and ``/api/embed``, thinking off by default, JSON-Schema
``format``, and the heavy-model unload guard (``keep_alive: 0`` on the previous heavy model before switching)."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from hmap.core.errors import ModelTransientError
from hmap.core.llm.base import LLMResponse, LLMUsage
from hmap.core.llm.errors import LLMProviderError
from hmap.core.llm.providers.base import ChatRequest
from hmap.core.tracing import get_logger

log = get_logger("hmap.llm.ollama")

DEFAULT_TIMEOUT = httpx.Timeout(600.0, connect=5.0)


def default_is_heavy(model: str) -> bool:
    """Default heaviness test: every model except embedding models (name contains ``embed``)."""
    return "embed" not in model.lower()


def _snippet(text: str, limit: int = 300) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "..."


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434", client: httpx.AsyncClient | None = None, *,
                 keep_alive: str | int | None = None, num_ctx: int | None = None,
                 is_heavy: Callable[[str], bool] | None = default_is_heavy,
                 timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> None:
        """``keep_alive`` / ``num_ctx`` are sent only when set (else Ollama's server defaults apply).
        ``is_heavy=None`` disables the unload guard."""
        self.base_url = base_url.rstrip("/")
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self.keep_alive = keep_alive
        self.num_ctx = num_ctx
        self._is_heavy = is_heavy
        self._last_chat_model: str | None = None
        self._no_think: set[str] = set()  # models that rejected the ``think`` field

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------ chat
    def chat_body(self, request: ChatRequest, *, think: bool = True) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": request.temperature, "num_predict": request.max_tokens}
        if request.seed is not None:
            options["seed"] = request.seed
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        body: dict[str, Any] = {"model": request.model, "messages": request.messages, "stream": False,
                                "options": options}
        if think:
            body["think"] = request.think
        if request.json_schema is not None:
            body["format"] = request.json_schema
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        return body

    async def chat(self, request: ChatRequest) -> LLMResponse:
        await self._maybe_unload(request.model)
        send_think = request.model not in self._no_think
        body = self.chat_body(request, think=send_think)
        started = time.perf_counter()
        resp = await self._post("/api/chat", body)
        self._last_chat_model = request.model
        if resp.status_code == 400 and send_think and "think" in resp.text.lower():
            # Models without a thinking switch reject the field: remember and retry once without it.
            log.info("llm.ollama.think_unsupported", model=request.model)
            self._no_think.add(request.model)
            body.pop("think", None)
            resp = await self._post("/api/chat", body)
        self._check(resp, "/api/chat", request.model)
        data = self._json(resp, "/api/chat")
        message = data.get("message") or {}
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise LLMProviderError("ollama /api/chat returned no message content", details={"model": request.model})
        latency = time.perf_counter() - started
        usage = LLMUsage(input_tokens=int(data.get("prompt_eval_count") or 0),
                         output_tokens=int(data.get("eval_count") or 0), latency_s=round(latency, 4),
                         model=str(data.get("model") or request.model), provider=self.name)
        log.debug("llm.ollama.chat", model=usage.model, input_tokens=usage.input_tokens,
                  output_tokens=usage.output_tokens, latency_s=usage.latency_s,
                  total_duration_s=_ns(data.get("total_duration")), load_duration_s=_ns(data.get("load_duration")),
                  eval_duration_s=_ns(data.get("eval_duration")))
        return LLMResponse(text=text, usage=usage)

    # ------------------------------------------------------------------ embed
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        body: dict[str, Any] = {"model": model, "input": texts}
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        resp = await self._post("/api/embed", body)
        self._check(resp, "/api/embed", model)
        data = self._json(resp, "/api/embed")
        vectors = data.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise LLMProviderError("ollama /api/embed returned an unexpected payload", details={"model": model})
        return [[float(x) for x in vec] for vec in vectors]

    # ------------------------------------------------------------------ unload guard (doc 02 §2.1)
    async def _maybe_unload(self, model: str) -> None:
        prev = self._last_chat_model
        if self._is_heavy is None or prev is None or prev == model:
            return
        if not (self._is_heavy(prev) and self._is_heavy(model)):
            return
        log.info("llm.ollama.unload", previous=prev, next=model)
        try:
            resp = await self._client.post(self._url("/api/generate"), json={"model": prev, "keep_alive": 0})
            if resp.status_code >= 400:
                log.warning("llm.ollama.unload_failed", model=prev, status=resp.status_code)
        except httpx.TransportError as exc:
            log.warning("llm.ollama.unload_failed", model=prev, error=type(exc).__name__)
        self._last_chat_model = None

    # ------------------------------------------------------------------ http helpers
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    async def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        try:
            return await self._client.post(self._url(path), json=body)
        except httpx.TimeoutException as exc:
            raise ModelTransientError(f"ollama {path} timed out ({type(exc).__name__})",
                                      details={"base_url": self.base_url, "kind": "timeout"}) from exc
        except httpx.TransportError as exc:
            raise ModelTransientError(f"ollama {path} unreachable at {self.base_url} ({type(exc).__name__})",
                                      details={"base_url": self.base_url, "kind": "connection"}) from exc

    def _check(self, resp: httpx.Response, path: str, model: str) -> None:
        status = resp.status_code
        if status < 400:
            return
        details = {"status": status, "model": model, "body": _snippet(resp.text)}
        if status >= 500:
            raise ModelTransientError(f"ollama {path} server error {status}", details=details)
        if status == 404:
            raise LLMProviderError(f"ollama model {model!r} not found (run `ollama pull {model}` or fix "
                                   f"HMAP_ROLE_MAP)", details=details)
        raise LLMProviderError(f"ollama {path} rejected the request ({status}): {details['body']}", details=details)

    @staticmethod
    def _json(resp: httpx.Response, path: str) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError as exc:
            raise ModelTransientError(f"ollama {path} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise LLMProviderError(f"ollama {path} returned a non-object payload")
        return data


def _ns(value: Any) -> float | None:
    return round(value / 1e9, 4) if isinstance(value, int | float) else None
