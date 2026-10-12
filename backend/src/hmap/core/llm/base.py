"""LLM gateway interface (doc 01 §4 "LLM Gateway contract", doc 02 §2). Agents only ever use ``LLMClient``;
they never name a model. Implementation: ``hmap.core.llm.gateway.Gateway`` (modes live|record|replay|fake)."""

from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from hmap.core.contracts.common import Contract

Role = Literal["fast", "reasoner", "coder", "judge", "embed", "classify"]
T = TypeVar("T", bound=BaseModel)


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMUsage(Contract):
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    model: str = ""
    provider: str = ""
    cached: bool = False


class LLMResponse(Contract):
    text: str
    parsed: Any = Field(default=None, description="validated schema instance when a schema was given")
    usage: LLMUsage = Field(default_factory=LLMUsage)


class ClassifyQuestion(Contract):
    """A typed decision for ``classify`` (bool / choice / score). ``criteria`` explains each option."""

    name: str
    kind: Literal["bool", "choice", "score"]
    options: list[str] = Field(default_factory=list, description="choice labels, or score levels as strings")
    criteria: dict[str, str] = Field(default_factory=dict)


class ClassifyAnswer(Contract):
    name: str
    answer: str
    probabilities: dict[str, float] = Field(default_factory=dict)


class LLMClient(Protocol):
    async def generate(self, role: Role, messages: list[Message] | list[dict[str, str]], *,
                       schema: type[T] | None = None, max_tokens: int = 1024, temperature: float = 0.2,
                       think: bool = False, seed: int | None = None) -> LLMResponse:
        """With ``schema``: JSON-schema constrained output, validated, up to 2 repair retries; ``parsed`` is set."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]:
        """Short typed decisions (doc 02 §2.2 ``classify`` role). Sprint 1: an enum-schema ``generate`` call."""
