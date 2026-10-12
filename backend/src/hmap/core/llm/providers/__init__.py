"""LLM providers used by the gateway: local Ollama and an optional OpenAI-compatible cloud API."""

from hmap.core.llm.providers.base import ChatProvider, ChatRequest, EmbedProvider, LocalProvider
from hmap.core.llm.providers.ollama import OllamaProvider, default_is_heavy
from hmap.core.llm.providers.openai_compat import (
    OpenAICompatProvider,
    chat_completions_url,
    parse_retry_after,
)

__all__ = [
    "ChatProvider",
    "ChatRequest",
    "EmbedProvider",
    "LocalProvider",
    "OllamaProvider",
    "OpenAICompatProvider",
    "chat_completions_url",
    "default_is_heavy",
    "parse_retry_after",
]
