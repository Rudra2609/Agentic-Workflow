"""OpenAI-compatible cloud provider, e.g. Groq or Gemini (doc 02 §2.5). Disabled by default and never required.

Two ways to use it:
- :meth:`OpenAICompatProvider.send` — ONE request with a caller-supplied key and model, no retries, no sleeping.
  The team key pool (:mod:`hmap.core.llm.cloud`) uses this and handles 429/auth/5xx itself.
- :meth:`OpenAICompatProvider.chat` — the deprecated single-key path (``HMAP_CLOUD_BASE_URL``/``HMAP_CLOUD_API_KEY``):
  honours ``retry-after`` (seconds or HTTP date) with bounded retries; if the wait is too long or retries run out,
  raises :class:`CloudRateLimited` so the gateway falls back to the local model.

The API key is only placed in the ``Authorization`` header — never logged, never put in errors or return values.
"""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx

from hmap.core.errors import ErrorCode, ModelTransientError
from hmap.core.llm.base import LLMResponse, LLMUsage
from hmap.core.llm.errors import CloudRateLimited, LLMProviderError
from hmap.core.llm.providers.base import ChatRequest
from hmap.core.tracing import get_logger

log = get_logger("hmap.llm.cloud")

JsonMode = Literal["json_schema", "json_object", "none"]
# A base URL that already ends in an API version (``/v1``, ``/v1beta``) or in ``/openai`` only needs the route.
_VERSIONED = re.compile(r"/(v\d+[a-z0-9]*|openai)$", re.IGNORECASE)
DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=5.0)


def chat_completions_url(base_url: str) -> str:
    """``https://api.groq.com/openai/v1`` -> ``.../openai/v1/chat/completions``;
    ``https://generativelanguage.googleapis.com/v1beta/openai`` -> ``.../v1beta/openai/chat/completions``;
    an unversioned host (``https://h``) -> ``https://h/v1/chat/completions``."""
    base = base_url.rstrip("/")
    return f"{base}/chat/completions" if _VERSIONED.search(base) else f"{base}/v1/chat/completions"


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """``retry-after`` as seconds (``"2"``, ``"1.5"``) or an HTTP date; ``None`` when absent/unparseable."""
    if value is None or not value.strip():
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


class OpenAICompatProvider:
    def __init__(self, base_url: str, api_key: str | None, client: httpx.AsyncClient | None = None, *,
                 name: str = "cloud",
                 model_map: Mapping[str, str] | None = None, default_model: str | None = None,
                 max_retries: int = 2, max_retry_wait_s: float = 30.0, backoff_s: float = 2.0,
                 json_mode: JsonMode = "json_object",
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> None:
        """``model_map``: role -> cloud model name (cloud names differ from Ollama tags); falls back to
        ``default_model``, then to the locally resolved name. ``api_key=None`` makes a keyless provider whose
        :meth:`send` gets the key per call (the key pool)."""
        self.name = name
        self.url = chat_completions_url(base_url)
        self.__api_key = api_key or ""
        self._client = client if client is not None else httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self.model_map = dict(model_map or {})
        self.default_model = default_model
        self.max_retries = max_retries
        self.max_retry_wait_s = max_retry_wait_s
        self.backoff_s = backoff_s
        self.json_mode = json_mode
        self._sleep = sleep

    def __repr__(self) -> str:  # never show the key
        return f"OpenAICompatProvider(name={self.name!r}, url={self.url!r}, api_key=***)"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def model_for(self, request: ChatRequest) -> str:
        return self.model_map.get(request.role) or self.default_model or request.model

    def chat_body(self, request: ChatRequest, model: str | None = None) -> dict[str, Any]:
        messages: list[dict[str, str]] = list(request.messages)
        body: dict[str, Any] = {"model": model or self.model_for(request), "temperature": request.temperature,
                                "max_tokens": request.max_tokens}
        if request.seed is not None:
            body["seed"] = request.seed
        if request.json_schema is not None:
            if self.json_mode == "json_schema":
                body["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": str(request.json_schema.get("title") or "output"), "schema": request.json_schema}}
            else:
                hint = ("Respond with a single JSON object that matches this JSON Schema, and nothing else:\n"
                        + json.dumps(request.json_schema, sort_keys=True))
                messages = [{"role": "system", "content": hint}, *messages]
                if self.json_mode == "json_object":
                    body["response_format"] = {"type": "json_object"}
        body["messages"] = messages
        return body

    async def send(self, request: ChatRequest, *, api_key: str, model: str) -> LLMResponse:
        """ONE request with ``api_key`` for ``model``; no retries, no sleeping, no logging (the caller logs).

        Raises :class:`CloudRateLimited` (``details["retry_after"]`` = seconds or ``None``) on 429,
        :class:`LLMProviderError` with ``code=AUTHENTICATION`` on 401/403 (or a 400 that says the key is invalid),
        :class:`LLMProviderError` on other 4xx, :class:`ModelTransientError` on 5xx/network/timeout."""
        body = self.chat_body(request, model=model)
        started = time.perf_counter()
        resp = await self._post(body, api_key)
        if resp.status_code == 429:
            wait = parse_retry_after(resp.headers.get("retry-after"))
            raise CloudRateLimited(f"{self.name} rate limited (429)", details={"retry_after": wait})
        return self._parse(resp, model, started, 0, api_key=api_key, log_usage=False)

    async def _post(self, body: dict[str, Any], api_key: str) -> httpx.Response:
        try:
            return await self._client.post(self.url, json=body, headers={"Authorization": f"Bearer {api_key}"})
        except httpx.TimeoutException as exc:
            raise ModelTransientError(f"{self.name} provider timed out ({type(exc).__name__})",
                                      details={"kind": "timeout"}) from exc
        except httpx.TransportError as exc:
            raise ModelTransientError(f"{self.name} provider unreachable ({type(exc).__name__})",
                                      details={"kind": "connection"}) from exc

    async def chat(self, request: ChatRequest) -> LLMResponse:
        """Deprecated single-key path (legacy ``HMAP_CLOUD_*``): bounded 429 retries honouring ``retry-after``."""
        body = self.chat_body(request)
        started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            resp = await self._post(body, self.__api_key)
            if resp.status_code == 429:
                wait = parse_retry_after(resp.headers.get("retry-after"))
                log.warning("llm.cloud.rate_limited", model=body["model"], attempt=attempt, retry_after=wait)
                if attempt < self.max_retries and (wait is None or wait <= self.max_retry_wait_s):
                    await self._sleep(wait if wait is not None else self.backoff_s * (2 ** attempt))
                    continue
                raise CloudRateLimited("cloud provider rate limited (429)",
                                       details={"retry_after": wait, "attempts": attempt + 1})
            return self._parse(resp, body["model"], started, attempt, api_key=self.__api_key)
        raise CloudRateLimited("cloud provider rate limited (429)")  # pragma: no cover - loop always returns/raises

    def _parse(self, resp: httpx.Response, model: str, started: float, attempt: int, *, api_key: str,
               log_usage: bool = True) -> LLMResponse:
        status = resp.status_code
        if status >= 500:
            raise ModelTransientError(f"cloud provider server error {status}", details={"status": status})
        if status in (401, 403) or (status == 400 and "api key" in resp.text.lower()):
            raise LLMProviderError(f"cloud provider refused the credentials ({status})",
                                   code=ErrorCode.AUTHENTICATION, details={"status": status})
        if status >= 400:
            raise LLMProviderError(f"cloud provider rejected the request ({status})",
                                   details={"status": status, "model": model,
                                            "body": _scrub(resp.text, api_key)[:300]})
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage_raw = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("cloud provider returned an unexpected payload", details={"model": model}) from exc
        if not isinstance(text, str):
            raise LLMProviderError("cloud provider returned no text", details={"model": model})
        usage = LLMUsage(input_tokens=int(usage_raw.get("prompt_tokens") or 0),
                         output_tokens=int(usage_raw.get("completion_tokens") or 0),
                         latency_s=round(time.perf_counter() - started, 4),
                         model=str(data.get("model") or model), provider=self.name)
        if log_usage:
            log.info("llm.cloud.usage", model=usage.model, input_tokens=usage.input_tokens,
                     output_tokens=usage.output_tokens, latency_s=usage.latency_s, retries=attempt)
        return LLMResponse(text=text, usage=usage)
