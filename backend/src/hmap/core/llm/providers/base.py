"""Provider-level interface (below the gateway). Providers know models; agents never see them."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from hmap.core.llm.base import LLMResponse


@dataclass(frozen=True)
class ChatRequest:
    """One raw chat completion. ``messages`` is the full list sent (incl. any gateway-injected preamble)."""

    model: str
    messages: list[dict[str, str]] = field(default_factory=list)
    role: str = "reasoner"
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 1024
    temperature: float = 0.2
    seed: int | None = None
    think: bool = False


class ChatProvider(Protocol):
    name: str

    async def chat(self, request: ChatRequest) -> LLMResponse:
        """Return text + usage. Raise ``ModelTransientError`` for retryable faults, ``LLMProviderError`` otherwise."""
        ...


class EmbedProvider(Protocol):
    name: str

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]: ...


class LocalProvider(ChatProvider, EmbedProvider, Protocol):
    """A provider that can both chat and embed (Ollama)."""
