"""Cloud routing over the team key pool (doc 02 §2.5, item 1.14b).

``HMAP_CLOUD_ROLE_MAP`` maps a role to an ordered list of ``provider:model`` routes. For a mapped role the router
tries the routes in order; inside a provider it takes the next usable key from that provider's :class:`KeyPool`:

- 429 -> that key cools down (``retry-after`` or exponential default) and the next key is tried at once (no sleep);
- 401/403 -> that key is disabled until restart and the next key is tried;
- 5xx / network / timeout -> the next key is tried once more, then the router moves on to the next provider;
- any other 4xx (unknown model, request too large, ...) -> the router moves on to the next provider;
- nothing left -> :meth:`CloudRouter.chat` returns ``None`` and the gateway answers with the local model.

Every HTTP attempt logs one ``llm.cloud.call`` event (provider, model, role, key fingerprint, tokens, latency,
outcome); a local fallback logs one more with ``outcome="fallback_local"``. Never the key, never message content.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from hmap.core.config import Settings
from hmap.core.errors import ErrorCode, HmapError, ModelTransientError
from hmap.core.llm.base import LLMResponse
from hmap.core.llm.errors import CloudRateLimited, LLMProviderError
from hmap.core.llm.key_pool import KeyLease, KeyPool
from hmap.core.llm.providers.base import ChatRequest
from hmap.core.llm.providers.openai_compat import DEFAULT_TIMEOUT, JsonMode, OpenAICompatProvider
from hmap.core.tracing import get_logger

log = get_logger("hmap.llm.cloud")

# How each provider is asked for JSON. Groq honours ``json_object``; Gemini's OpenAI-compatible endpoint gets the
# schema as a system hint only (its schema dialect rejects some JSON-Schema keywords); the gateway validates and
# repairs either way.
JSON_MODES: dict[str, JsonMode] = {"groq": "json_object", "gemini": "none", "cloud": "json_object"}
# Gemini's OpenAI-compatible endpoint answers 400 "Unknown name seed": without this every seeded call skipped Gemini
SEEDS: dict[str, bool] = {"groq": True, "gemini": False, "cloud": True}
# Gemini's thinking models count hidden reasoning against max_tokens: with think=False (the gateway default) ask for
# none, or the visible answer gets cut off (seen: 117 of 3000 tokens visible, JSON truncated)
# keyed by provider, then by model-name prefix ("" = every model). gpt-oss cannot switch reasoning off: "low" keeps
# it short (a 2.5K-token prompt with 20+ items ran out of tokens and Groq answered 400 json_validate_failed)
NO_THINK: dict[str, dict[str, dict[str, str]]] = {
    "gemini": {"": {"reasoning_effort": "none"}},
    "groq": {"openai/gpt-oss": {"reasoning_effort": "low"}},
}

Outcome = str  # ok | rate_limited | auth_error | rejected | error | fallback_local


@dataclass
class CloudBackend:
    """One cloud provider: a keyless OpenAI-compatible client plus its key pool."""

    provider: OpenAICompatProvider
    pool: KeyPool

    @property
    def name(self) -> str:
        return self.provider.name


class CloudRouter:
    def __init__(self, backends: Mapping[str, CloudBackend], role_map: Mapping[str, Sequence[tuple[str, str]]], *,
                 client: httpx.AsyncClient | None = None, owns_client: bool = False,
                 max_transient_retries: int = 1) -> None:
        """``role_map`` routes naming a provider without a backend are dropped (no keys for it)."""
        self.backends = dict(backends)
        self.role_map: dict[str, list[tuple[str, str]]] = {}
        for role, routes in role_map.items():
            usable = [(p, m) for p, m in routes if p in self.backends]
            if usable:
                self.role_map[role] = usable
        self.max_transient_retries = max_transient_retries
        self.local_fallbacks = 0
        self._client = client
        self._owns_client = owns_client

    def __repr__(self) -> str:
        pools = ", ".join(f"{name}={len(b.pool)} key(s)" for name, b in self.backends.items())
        return f"CloudRouter({pools}; roles={sorted(self.role_map)})"

    @classmethod
    def from_settings(cls, settings: Settings, *, client: httpx.AsyncClient | None = None,
                      clock: Callable[[], float] = time.monotonic) -> "CloudRouter | None":
        """A router for the providers named in ``settings.cloud_role_map`` that have keys; ``None`` when no mapped
        role can reach any keyed provider (then nothing is constructed and every call stays local)."""
        wanted = {p for routes in settings.cloud_role_map.values() for p, _ in routes}
        specs: list[tuple[str, str, list[str]]] = []
        for provider in sorted(wanted):
            keys = settings.cloud_keys(provider)
            base_url = settings.cloud_base_url_for(provider)
            if not keys or not base_url:
                log.info("llm.cloud.provider_skipped", provider=provider, reason="no keys configured")
                continue
            specs.append((provider, base_url, keys))
        if not specs:
            return None
        owns = client is None
        shared = client if client is not None else httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        backends = {
            provider: CloudBackend(
                OpenAICompatProvider(base_url, None, shared, name=provider,
                                     json_mode=JSON_MODES.get(provider, "json_object"),
                                     send_seed=SEEDS.get(provider, True), no_think=NO_THINK.get(provider)),
                KeyPool(provider, keys, clock=clock))
            for provider, base_url, keys in specs}
        router = cls(backends, settings.cloud_role_map, client=shared, owns_client=owns)
        log.info("llm.cloud.configured", providers={n: len(b.pool) for n, b in backends.items()},
                 roles={r: [f"{p}:{m}" for p, m in routes] for r, routes in router.role_map.items()})
        return router

    # ------------------------------------------------------------------ routing
    def handles(self, role: str) -> bool:
        return role in self.role_map

    async def chat(self, request: ChatRequest, *, plugin: str = "default") -> LLMResponse | None:
        """Answer from the cloud, or ``None`` when every route/key is cooling, disabled or failing."""
        attempts = 0
        for provider_name, model in self.role_map.get(request.role, []):
            backend = self.backends[provider_name]
            tried: set[str] = set()
            transient = 0
            while (lease := backend.pool.acquire(exclude=tried)) is not None:
                tried.add(lease.fingerprint)
                attempts += 1
                result, next_step = await self._attempt(backend, lease, request, model, plugin)
                if result is not None:
                    return result
                if next_step == "transient":
                    transient += 1
                    if transient > self.max_transient_retries:
                        break
                elif next_step == "next_provider":
                    break
        self.local_fallbacks += 1
        log.warning("llm.cloud.call", plugin=plugin, role=request.role, provider=None, model=None, key=None,
                    input_tokens=0, output_tokens=0, latency_s=0.0, outcome="fallback_local", attempts=attempts)
        return None

    async def _attempt(self, backend: CloudBackend, lease: KeyLease, request: ChatRequest, model: str,
                       plugin: str) -> tuple[LLMResponse | None, str]:
        """One HTTP call. Returns ``(response, "")`` on success, else ``(None, next_key|transient|next_provider)``."""
        pool = backend.pool
        fp = lease.fingerprint
        started = time.perf_counter()

        def emit(outcome: Outcome, level: str = "warning", **extra: Any) -> None:
            getattr(log, level)("llm.cloud.call", plugin=plugin, role=request.role, provider=backend.name,
                                model=model, key=fp, latency_s=round(time.perf_counter() - started, 4),
                                outcome=outcome, **extra)

        try:
            resp = await backend.provider.send(request, api_key=lease.secret(), model=model)
        except CloudRateLimited as exc:
            retry_after = exc.details.get("retry_after")
            cooldown = pool.mark_rate_limited(fp, retry_after if isinstance(retry_after, int | float) else None)
            emit("rate_limited", input_tokens=0, output_tokens=0, retry_after=retry_after, cooldown_s=cooldown)
            return None, "next_key"
        except LLMProviderError as exc:
            status = exc.details.get("status")
            if exc.code == ErrorCode.AUTHENTICATION:
                pool.mark_auth_error(fp)
                emit("auth_error", input_tokens=0, output_tokens=0, status=status)
                return None, "next_key"
            pool.mark_error(fp)
            emit("rejected", input_tokens=0, output_tokens=0, status=status)
            return None, "next_provider"
        except (ModelTransientError, httpx.HTTPError) as exc:
            pool.mark_error(fp)
            details = exc.details if isinstance(exc, HmapError) else {}
            emit("error", input_tokens=0, output_tokens=0, status=details.get("status"),
                 error_kind=details.get("kind") or type(exc).__name__)
            return None, "transient"
        except HmapError as exc:  # pragma: no cover - providers only raise the above
            pool.mark_error(fp)
            emit("error", input_tokens=0, output_tokens=0, error_kind=type(exc).__name__)
            return None, "next_provider"
        usage = resp.usage
        pool.mark_ok(fp, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
        emit("ok", level="info", input_tokens=usage.input_tokens, output_tokens=usage.output_tokens)
        return resp, ""

    # ------------------------------------------------------------------ introspection / lifecycle
    def usage(self) -> dict[str, dict[str, Any]]:
        """Per key fingerprint: provider, requests, ok, tokens in/out, rate_limited, auth_errors, errors,
        disabled, cooling_for_s. Safe to serve from an API (no secrets)."""
        out: dict[str, dict[str, Any]] = {}
        for backend in self.backends.values():
            out.update(backend.pool.usage())
        return out

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()


__all__ = ["JSON_MODES", "NO_THINK", "SEEDS", "CloudBackend", "CloudRouter"]
