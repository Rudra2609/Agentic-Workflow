"""LLM gateway (doc 01 §4, doc 02 §2). Agents depend only on :class:`LLMClient`; get one with
``build_llm(settings, plugin="<your plug-in>")`` (or ``gateway.for_plugin(name)``) and never name a model."""

from hmap.core.llm.base import ClassifyAnswer, ClassifyQuestion, LLMClient, LLMResponse, LLMUsage, Message, Role
from hmap.core.llm.cache import ReplayCache, cache_key, key_ingredients
from hmap.core.llm.cloud import CloudBackend, CloudRouter
from hmap.core.llm.errors import (
    CloudRateLimited,
    FakeLLMError,
    LLMConfigError,
    LLMError,
    LLMProviderError,
    ReplayMissError,
    StructuredOutputError,
)
from hmap.core.llm.fake import FakeCall, FakeLLM
from hmap.core.llm.gateway import Gateway, build_llm, resolve_model
from hmap.core.llm.key_pool import KeyLease, KeyPool, fingerprint
from hmap.core.llm.providers import ChatRequest, OllamaProvider, OpenAICompatProvider
from hmap.core.llm.structured import generate_structured

__all__ = [
    "ChatRequest",
    "ClassifyAnswer",
    "ClassifyQuestion",
    "CloudBackend",
    "CloudRateLimited",
    "CloudRouter",
    "FakeCall",
    "FakeLLM",
    "FakeLLMError",
    "Gateway",
    "KeyLease",
    "KeyPool",
    "LLMClient",
    "LLMConfigError",
    "LLMError",
    "LLMProviderError",
    "LLMResponse",
    "LLMUsage",
    "Message",
    "OllamaProvider",
    "OpenAICompatProvider",
    "ReplayCache",
    "ReplayMissError",
    "Role",
    "StructuredOutputError",
    "build_llm",
    "cache_key",
    "fingerprint",
    "generate_structured",
    "key_ingredients",
    "resolve_model",
]
