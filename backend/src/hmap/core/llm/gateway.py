"""The LLM gateway (doc 01 §4, doc 02 §2): the only ``LLMClient`` implementation agents get.

Modes (``HMAP_LLM_MODE``):
- ``live``   — provider only.
- ``record`` — provider, and every raw request/response is written to the replay cache (overwriting).
- ``replay`` — cache only; no provider is constructed, zero network; a miss raises :class:`ReplayMissError`.
  Exception (Sprint 4): plug-ins listed in ``HMAP_LLM_RECORD_MISSING`` fetch a *missing* answer live and record it
  (existing recordings are never overwritten) — for filling in one plug-in's recordings while the rest replays.
- ``fake``   — every call is delegated to a :class:`FakeLLM`.

Role -> model comes from ``settings.role_map`` (all roles may alias one model). A missing role falls back to
``reasoner`` (``classify`` tries ``fast`` first), then errors. Heavy local chat calls run under
``asyncio.Semaphore(llm_max_concurrency)``.

Cloud (doc 02 §2.5, never required):
- **Team key pool** (:class:`~hmap.core.llm.cloud.CloudRouter`): roles listed in ``HMAP_CLOUD_ROLE_MAP`` try their
  ``provider:model`` routes in order, rotating each provider's keys; when every key is cooling/disabled/failing the
  call falls back to the local model. Built only in ``live``/``record`` mode and only when some mapped provider has
  keys. With no map configured, ``DEFAULT_CLOUD_ROLE_MAP`` sends every chat role cloud-first. Roles not in the map
  (and ``embed``) always stay local.
- **Legacy single provider** (deprecated ``HMAP_CLOUD_BASE_URL`` + ``HMAP_CLOUD_API_KEY``, or ``cloud=``): opt-in per
  call (``allow_cloud=True``) or per client (``cloud_ok=True``) for roles in ``cloud_roles``; any failure -> local.

Telemetry (Sprint 4): every ``generate`` / ``embed`` / ``read_images`` call is a ``chat <role>`` (etc.) client span
with the model, provider, token counts and whether the cache answered — never the prompt or the answer — and feeds
the ``hmap_llm_*`` metrics (latency, tokens, calls by outcome).

Permission (both lanes): ``HMAP_CLOUD_OK=false`` or a client bound with ``cloud_ok=False`` (a local-only project) is a
hard "never call the cloud"; otherwise ``allow_cloud`` decides per call; when neither is given the key pool is used
for mapped roles, and the legacy provider is not.
"""

import asyncio
import base64
import copy
import hashlib
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from hmap.core.config import LLMMode, Settings
from hmap.core.errors import HmapError
from hmap.core.llm import classify as _classify
from hmap.core.llm.base import ClassifyAnswer, ClassifyQuestion, LLMResponse, LLMUsage, Message, Role
from hmap.core.llm.cache import (
    ReplayCache,
    cache_key,
    embed_key_ingredients,
    key_ingredients,
    validate_plugin_name,
)
from hmap.core.llm.cloud import CloudRouter
from hmap.core.llm.errors import LLMConfigError, ReplayMissError, VisionUnavailable
from hmap.core.llm.fake import FakeLLM
from hmap.core.llm.providers.base import ChatProvider, ChatRequest, LocalProvider
from hmap.core.llm.providers.ollama import OllamaProvider
from hmap.core.llm.providers.openai_compat import OpenAICompatProvider
from hmap.core.llm.structured import MAX_REPAIRS, generate_structured, inline_refs
from hmap.core.tracing import get_logger
from hmap.obs import metrics as obs_metrics
from hmap.obs import telemetry

log = get_logger("hmap.llm")

T = TypeVar("T", bound=BaseModel)

_FALLBACKS: dict[str, tuple[str, ...]] = {"classify": ("classify", "fast", "reasoner")}
CHAT_ROLES: frozenset[str] = frozenset({"fast", "reasoner", "coder", "judge", "classify"})


def resolve_model(role_map: dict[str, str], role: str) -> str:
    """``role`` -> model via ``HMAP_ROLE_MAP``; missing role -> ``reasoner`` (``classify`` -> ``fast`` first)."""
    chain = _FALLBACKS.get(role, (role, "reasoner"))
    for candidate in chain:
        if model := role_map.get(candidate):
            return model
    raise LLMConfigError(f"no model configured for role {role!r} (tried {', '.join(chain)}); set HMAP_ROLE_MAP, "
                         f"e.g. HMAP_ROLE_MAP=reasoner=qwen3:8b,embed=nomic-embed-text",
                         details={"role": role, "role_map": dict(role_map)})


def normalize_messages(messages: list[Message] | list[dict[str, str]]) -> list[Message]:
    return [m if isinstance(m, Message) else Message.model_validate(m) for m in messages]


class _Shared:
    """State shared by a gateway and every client bound with ``for_plugin``."""

    def __init__(self, settings: Settings, mode: LLMMode, local: LocalProvider | None, cloud: ChatProvider | None,
                 fake: FakeLLM | None, cache: ReplayCache, cloud_roles: frozenset[str],
                 router: CloudRouter | None) -> None:
        self.settings = settings
        self.mode = mode
        self._local = local
        self.cloud = cloud
        self.router = router
        self.fake = fake if fake is not None else (FakeLLM() if mode == "fake" else None)
        self.cache = cache
        self.cloud_roles = cloud_roles
        self.semaphore = asyncio.Semaphore(max(1, settings.llm_max_concurrency))

    @property
    def local(self) -> LocalProvider:
        if self._local is None:  # built lazily so replay/fake never touch the network stack
            self._local = OllamaProvider(self.settings.ollama_base_url, num_ctx=self.settings.ollama_num_ctx)
        return self._local


class Gateway:
    def __init__(self, settings: Settings, *, local: LocalProvider | None = None, cloud: ChatProvider | None = None,
                 fake: FakeLLM | None = None, cache: ReplayCache | None = None, mode: LLMMode | None = None,
                 plugin: str = "default", preamble: str | None = None, prompt_version: str = "1",
                 cloud_ok: bool | None = None, cloud_roles: frozenset[str] | None = None,
                 cloud_router: CloudRouter | None = None, max_repairs: int = MAX_REPAIRS) -> None:
        """``cloud`` (deprecated legacy lane) defaults to an :class:`OpenAICompatProvider` when ``cloud_base_url``
        and ``cloud_api_key`` are both set. ``cloud_router`` (the team key pool) defaults to
        :meth:`CloudRouter.from_settings` — ``None`` when no keys/role map are configured. Neither is built in
        ``replay``/``fake`` mode. ``cloud_ok``: ``None`` = not specified, ``False`` = this client never uses the
        cloud, ``True`` = also opt in to the legacy lane. ``preamble`` is gateway-injected system text: sent to the
        model and stored in the cache file, but never part of the cache key."""
        resolved_mode: LLMMode = mode or settings.llm_mode
        networked = resolved_mode in ("live", "record") or (resolved_mode == "replay"
                                                             and bool(settings.llm_record_missing))
        if cloud is None and settings.cloud_base_url and settings.cloud_api_key and networked:
            cloud = OpenAICompatProvider(settings.cloud_base_url, settings.cloud_api_key)
        if cloud_router is None and networked:
            cloud_router = CloudRouter.from_settings(settings)
        self._shared = _Shared(settings, resolved_mode, local, cloud, fake,
                               cache if cache is not None else ReplayCache(settings.llm_cache_dir),
                               cloud_roles if cloud_roles is not None else CHAT_ROLES,
                               cloud_router if networked else None)
        self.plugin = validate_plugin_name(plugin)
        self.preamble = preamble
        self.prompt_version = prompt_version
        self.cloud_ok = cloud_ok
        self.max_repairs = max_repairs

    # ------------------------------------------------------------------ binding / introspection
    def for_plugin(self, name: str, *, prompt_version: str | None = None, cloud_ok: bool | None = None,
                   preamble: str | None = None) -> "Gateway":
        """A client bound to plug-in ``name`` (its cache folder); providers, cache and semaphore are shared."""
        bound = copy.copy(self)
        bound.plugin = validate_plugin_name(name)
        if prompt_version is not None:
            bound.prompt_version = prompt_version
        if cloud_ok is not None:
            bound.cloud_ok = cloud_ok
        if preamble is not None:
            bound.preamble = preamble
        return bound

    def local_only(self) -> "Gateway":
        """The same client, but never the cloud (a local-only project); providers, cache and semaphore are shared."""
        bound = copy.copy(self)
        bound.cloud_ok = False
        return bound

    @property
    def mode(self) -> LLMMode:
        return self._shared.mode

    @property
    def cache(self) -> ReplayCache:
        return self._shared.cache

    @property
    def fake(self) -> FakeLLM | None:
        return self._shared.fake

    def model_for(self, role: str) -> str:
        return resolve_model(self._shared.settings.role_map, role)

    @property
    def cloud_router(self) -> CloudRouter | None:
        return self._shared.router

    def cloud_usage(self) -> dict[str, dict[str, Any]]:
        """Per key fingerprint counters of the team key pool (for ``/api/llm/usage``); ``{}`` without a pool.
        Contains no secrets."""
        router = self._shared.router
        return router.usage() if router is not None else {}

    async def aclose(self) -> None:
        for provider in (self._shared._local, self._shared.cloud, self._shared.router):
            closer = getattr(provider, "aclose", None)
            if closer is not None:
                await closer()

    # ------------------------------------------------------------------ LLMClient
    async def generate(self, role: Role, messages: list[Message] | list[dict[str, str]], *,
                       schema: type[T] | None = None, max_tokens: int = 1024, temperature: float = 0.2,
                       think: bool = False, seed: int | None = None, allow_cloud: bool | None = None) -> LLMResponse:
        with telemetry.span(f"chat {role}", kind="client", attrs={
                "gen_ai.operation.name": "chat", "hmap.llm.role": role, "hmap.plugin": self.plugin,
                "hmap.llm.mode": self.mode, "hmap.llm.structured": schema is not None,
                "gen_ai.request.max_tokens": max_tokens, "gen_ai.request.temperature": temperature}) as span:
            try:
                resp = await self._generate(role, messages, schema=schema, max_tokens=max_tokens,
                                            temperature=temperature, think=think, seed=seed, allow_cloud=allow_cloud)
            except Exception as exc:
                obs_metrics.LLM_CALLS.labels(role, "none", "error").inc()
                span.error(exc, code=str(getattr(exc, "code", "")) or None)
                raise
            _span_usage(span, resp.usage)
            return resp

    async def _generate(self, role: Role, messages: list[Message] | list[dict[str, str]], *,
                        schema: type[T] | None, max_tokens: int, temperature: float, think: bool, seed: int | None,
                        allow_cloud: bool | None) -> LLMResponse:
        msgs = normalize_messages(messages)
        if self.mode == "fake":
            return await self._fake().generate(role, msgs, schema=schema, max_tokens=max_tokens,
                                               temperature=temperature, think=think, seed=seed)
        schema_json = schema.model_json_schema() if schema is not None else None
        send_format = inline_refs(schema_json) if schema_json is not None else None

        async def call(attempt_msgs: list[Message]) -> LLMResponse:
            return await self._complete(role, attempt_msgs, schema_json=schema_json, send_format=send_format,
                                        max_tokens=max_tokens, temperature=temperature, think=think, seed=seed,
                                        allow_cloud=allow_cloud)

        if schema is None:
            return await call(msgs)
        return await generate_structured(call, msgs, schema, max_repairs=self.max_repairs)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        with telemetry.span("embeddings", kind="client", attrs={
                "gen_ai.operation.name": "embeddings", "hmap.llm.role": "embed", "hmap.plugin": self.plugin,
                "hmap.llm.mode": self.mode, "hmap.llm.inputs": len(texts)}):
            return await self._embed(texts)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if self.mode == "fake":
            return await self._fake().embed(texts)
        ingredients = embed_key_ingredients(plugin=self.plugin, texts=texts)
        key = cache_key(ingredients)
        started = time.perf_counter()
        if self.mode == "replay":
            record = self._replay_record(key, ingredients)
            vectors = record.get("response", {}).get("embeddings")
            if not isinstance(vectors, list):
                raise ReplayMissError(f"LLM replay: cache entry for key {key} holds no embeddings")
            self._log("embed", str(record.get("model", "")), "cache", LLMUsage(cached=True), started, len(texts))
            return [[float(x) for x in v] for v in vectors]
        model = self.model_for("embed")
        vectors = await self._shared.local.embed(model, texts)
        if self.mode == "record":
            self.cache.save(self.plugin, key, {
                "role": "embed", "prompt_version": self.prompt_version, "key_ingredients": ingredients,
                "model": model, "model_digest": None, "provider": self._shared.local.name,
                "request": {"model": model, "input": texts}, "response": {"embeddings": vectors}})
        self._log("embed", model, self._shared.local.name, LLMUsage(), started, len(texts))
        return vectors

    async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]:
        if self.mode == "fake":
            return await self._fake().classify(state, questions)
        schema = _classify.build_schema(questions)
        # cloud reasoning models (gpt-oss, Gemini) think before answering: with a small budget they return nothing
        # (Groq: 400 json_validate_failed) and every call fell back to the local model (found in Sprint 4)
        resp = await self.generate("classify", _classify.build_messages(state, questions), schema=schema,
                                   temperature=0.0, max_tokens=320 + 64 * len(questions))
        return _classify.to_answers(resp.parsed, questions)

    async def read_images(self, prompt: str, images: list[bytes], *, max_tokens: int = 4096) -> LLMResponse:
        with telemetry.span("chat vision", kind="client", attrs={
                "gen_ai.operation.name": "chat", "hmap.llm.role": "vision", "hmap.plugin": self.plugin,
                "hmap.llm.mode": self.mode, "hmap.llm.images": len(images)}) as span:
            resp = await self._read_images(prompt, images, max_tokens=max_tokens)
            _span_usage(span, resp.usage)
            return resp

    async def _read_images(self, prompt: str, images: list[bytes], *, max_tokens: int = 4096) -> LLMResponse:
        """Role ``vision`` (cloud only, doc 02 §2.5): ``prompt`` plus PNG/JPEG ``images`` to a vision model. The replay
        cache key holds the images' SHA-256, never the bytes. Raises :class:`VisionUnavailable` when no vision route
        can answer (none configured, cloud not allowed for this client, every key failed)."""
        if self.mode == "fake":
            return await self._fake().read_images(prompt, images, max_tokens=max_tokens)
        msgs = [Message(role="user", content=prompt)]
        ingredients = key_ingredients(plugin=self.plugin, role="vision", messages=msgs, schema=None, temperature=0.0,
                                      max_tokens=max_tokens, seed=None, think=False)
        ingredients["images"] = [hashlib.sha256(img).hexdigest() for img in images]
        key = cache_key(ingredients)
        started = time.perf_counter()
        if self.mode == "replay":
            record = self._replay_record(key, ingredients)
            response = record.get("response") or {}
            usage = LLMUsage.model_validate(response.get("usage") or {}).model_copy(
                update={"cached": True, "provider": "cache", "latency_s": 0.0})
            self._log("vision", usage.model, "cache", usage, started)
            return LLMResponse(text=str(response.get("text", "")), usage=usage)
        router = self._shared.router
        if router is None or not router.handles("vision") or not self._cloud_permitted(None, legacy=False):
            raise VisionUnavailable("no vision model available (needs a vision route in the team key pool and a "
                                    "project that allows cloud models)")
        request = ChatRequest(model="-", messages=self._with_preamble(msgs), role="vision", max_tokens=max_tokens,
                              temperature=0.0, images=[base64.b64encode(img).decode() for img in images])
        resp = await router.chat(request, plugin=self.plugin)
        if resp is None:
            raise VisionUnavailable("every vision route failed or is rate limited")
        if self.mode == "record":
            self.cache.save(self.plugin, key, {
                "role": "vision", "prompt_version": self.prompt_version, "key_ingredients": ingredients,
                "model": resp.usage.model, "model_digest": None, "provider": resp.usage.provider,
                "request": {"messages": request.messages, "images": ingredients["images"],
                            "options": {"temperature": 0.0, "num_predict": max_tokens}},
                "response": {"text": resp.text, "usage": resp.usage.model_dump(mode="json")}})
        self._log("vision", resp.usage.model, resp.usage.provider, resp.usage, started)
        return resp

    # ------------------------------------------------------------------ internals
    def _fake(self) -> FakeLLM:
        fake = self._shared.fake
        if fake is None:  # pragma: no cover - _Shared always creates one in fake mode
            raise LLMConfigError("fake mode without a FakeLLM")
        return fake

    def _replay_record(self, key: str, ingredients: dict[str, Any]) -> dict[str, Any]:
        record = self.cache.load(self.plugin, key)
        recorded_version = None
        if record is not None:
            recorded_version = str(record.get("prompt_version", "1"))
            if recorded_version == self.prompt_version:
                return record
        raise ReplayMissError(self.cache.describe_miss(self.plugin, key, ingredients,
                                                       prompt_version=self.prompt_version,
                                                       recorded_version=recorded_version),
                              details={"key": key, "plugin": self.plugin, "role": ingredients.get("role")})

    def _with_preamble(self, msgs: list[Message]) -> list[dict[str, str]]:
        out = [{"role": m.role, "content": m.content} for m in msgs]
        if self.preamble:
            out.insert(0, {"role": "system", "content": self.preamble})
        return out

    async def _complete(self, role: str, msgs: list[Message], *, schema_json: dict[str, Any] | None,
                        send_format: dict[str, Any] | None, max_tokens: int, temperature: float, think: bool,
                        seed: int | None, allow_cloud: bool | None) -> LLMResponse:
        ingredients = key_ingredients(plugin=self.plugin, role=role, messages=msgs, schema=schema_json,
                                      temperature=temperature, max_tokens=max_tokens, seed=seed, think=think)
        key = cache_key(ingredients)
        started = time.perf_counter()
        if self.mode == "replay":
            try:
                record = self._replay_record(key, ingredients)
            except ReplayMissError:
                if not self._records_missing:
                    raise
            else:
                response = record.get("response") or {}
                usage = LLMUsage.model_validate(response.get("usage") or {}).model_copy(
                    update={"cached": True, "provider": "cache", "latency_s": 0.0})
                self._log(role, usage.model, "cache", usage, started)
                return LLMResponse(text=str(response.get("text", "")), usage=usage)

        request = ChatRequest(model=self.model_for(role), messages=self._with_preamble(msgs), role=role,
                              json_schema=send_format, max_tokens=max_tokens, temperature=temperature, seed=seed,
                              think=think)
        resp, provider = await self._dispatch(request, allow_cloud)
        if self.mode == "record" or (self.mode == "replay" and self._records_missing):
            self.cache.save(self.plugin, key, {
                "role": role, "prompt_version": self.prompt_version, "key_ingredients": ingredients,
                "model": resp.usage.model or request.model, "model_digest": None, "provider": provider,
                "request": {"model": request.model, "messages": request.messages, "format": send_format,
                            "options": {"temperature": temperature, "num_predict": max_tokens, "seed": seed},
                            "think": think},
                "response": {"text": resp.text, "usage": resp.usage.model_dump(mode="json")}})
        self._log(role, resp.usage.model or request.model, provider, resp.usage, started)
        return resp

    @property
    def _records_missing(self) -> bool:
        wanted = self._shared.settings.llm_record_missing
        return "all" in wanted or self.plugin in wanted

    def _cloud_permitted(self, allow_cloud: bool | None, *, legacy: bool) -> bool:
        if not self._shared.settings.cloud_ok or self.cloud_ok is False:
            return False  # global kill switch / local-only project: hard "no"
        if allow_cloud is not None:
            return allow_cloud
        return self.cloud_ok is True or not legacy

    def _cloud_allowed(self, role: str, allow_cloud: bool | None) -> bool:
        """Legacy single-provider lane (opt-in)."""
        if self._shared.cloud is None or role not in self._shared.cloud_roles:
            return False
        return self._cloud_permitted(allow_cloud, legacy=True)

    async def _dispatch(self, request: ChatRequest, allow_cloud: bool | None) -> tuple[LLMResponse, str]:
        router = self._shared.router
        if router is not None and router.handles(request.role):
            if self._cloud_permitted(allow_cloud, legacy=False):
                pooled = await router.chat(request, plugin=self.plugin)
                if pooled is not None:
                    return pooled, pooled.usage.provider
        elif (cloud := self._shared.cloud) is not None and self._cloud_allowed(request.role, allow_cloud):
            try:
                return await cloud.chat(request), cloud.name
            except (HmapError, httpx.HTTPError) as exc:
                log.warning("llm.cloud.fallback", plugin=self.plugin, role=request.role,
                            error_code=str(getattr(exc, "code", type(exc).__name__)), error=str(exc)[:200])
        local = self._shared.local
        async with self._shared.semaphore:
            return await local.chat(request), local.name

    def _log(self, role: str, model: str, provider: str, usage: LLMUsage, started: float, n_texts: int = 0) -> None:
        obs_metrics.llm_call(role, provider, time.perf_counter() - started, usage.input_tokens, usage.output_tokens)
        log.info("llm.call", plugin=self.plugin, mode=self.mode, role=role, model=model, provider=provider,
                 input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                 latency_s=round(time.perf_counter() - started, 4), cached=usage.cached,
                 **({"texts": n_texts} if n_texts else {}))


def _span_usage(span: telemetry.SpanHandle, usage: LLMUsage) -> None:
    span.update({"gen_ai.response.model": usage.model, "gen_ai.provider.name": usage.provider,
                 "gen_ai.usage.input_tokens": usage.input_tokens, "gen_ai.usage.output_tokens": usage.output_tokens,
                 "hmap.llm.cached": usage.cached, "hmap.llm.latency_s": round(usage.latency_s, 4)})


def build_llm(settings: Settings | None = None, plugin: str = "default", **kwargs: Any) -> Gateway:
    """Convenience: a gateway for ``settings`` (default: from the environment) bound to ``plugin``."""
    return Gateway(settings if settings is not None else Settings.from_env(), plugin=plugin, **kwargs)
