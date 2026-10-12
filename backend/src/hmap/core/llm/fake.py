"""``FakeLLM``: a deterministic, scripted ``LLMClient`` for unit tests (doc 02 §2.4 mode ``fake``).

Replies are matched in this order: by schema class (``on_schema``), by role (``on_role``), the ``handler`` callable,
then ``default``. A reply is a ``str``, a ``dict``/``list`` (sent as JSON), a pydantic instance, or a callable taking
the :class:`FakeCall` and returning one of those. Passing several replies scripts a sequence (one per raw attempt,
the last one repeats) — handy to exercise the structured-output repair loop::

    fake = FakeLLM()
    fake.on_schema(Plan, "not json", Plan(steps=["a"]))   # first attempt invalid, repair succeeds
    fake.on_role("fast", "hello")
    fake.on_classify("relevant", "yes")
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from hmap.core.llm import classify as _classify
from hmap.core.llm.base import ClassifyAnswer, ClassifyQuestion, LLMResponse, LLMUsage, Message, Role
from hmap.core.llm.errors import FakeLLMError
from hmap.core.llm.structured import MAX_REPAIRS, generate_structured

T = TypeVar("T", bound=BaseModel)


@dataclass
class FakeCall:
    role: str
    messages: list[Message]
    schema: type[BaseModel] | None = None
    max_tokens: int = 1024
    temperature: float = 0.2
    think: bool = False
    seed: int | None = None
    attempts: int = 0  # raw attempts made for this call (>1 when a repair happened)


Reply = Any  # str | Mapping | list | BaseModel | Callable[[FakeCall], ...]


@dataclass
class _Script:
    replies: list[Reply]
    index: int = 0

    def next(self) -> Reply:
        reply = self.replies[min(self.index, len(self.replies) - 1)]
        self.index += 1
        return reply


@dataclass
class FakeLLM:
    default: str | None = "fake response"
    handler: Callable[[FakeCall], Reply] | None = None
    embed_dim: int = 8
    max_repairs: int = MAX_REPAIRS
    calls: list[FakeCall] = field(default_factory=list)
    embed_calls: list[list[str]] = field(default_factory=list)
    classify_calls: list[tuple[str, list[ClassifyQuestion]]] = field(default_factory=list)
    _by_role: dict[str, _Script] = field(default_factory=dict)
    _by_schema: dict[type[BaseModel], _Script] = field(default_factory=dict)
    _classify: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ scripting
    def on_role(self, role: str, *replies: Reply) -> "FakeLLM":
        self._by_role[role] = _Script(self._require(replies))
        return self

    def on_schema(self, schema: type[BaseModel], *replies: Reply) -> "FakeLLM":
        self._by_schema[schema] = _Script(self._require(replies))
        return self

    def on_classify(self, name: str, answer: str) -> "FakeLLM":
        self._classify[name] = answer
        return self

    @staticmethod
    def _require(replies: tuple[Reply, ...]) -> list[Reply]:
        if not replies:
            raise ValueError("script at least one reply")
        return list(replies)

    def reset(self) -> None:
        self.calls.clear()
        self.embed_calls.clear()
        self.classify_calls.clear()
        for script in (*self._by_role.values(), *self._by_schema.values()):
            script.index = 0

    # ------------------------------------------------------------------ LLMClient
    async def generate(self, role: Role, messages: list[Message] | list[dict[str, str]], *,
                       schema: type[T] | None = None, max_tokens: int = 1024, temperature: float = 0.2,
                       think: bool = False, seed: int | None = None) -> LLMResponse:
        msgs = [m if isinstance(m, Message) else Message.model_validate(m) for m in messages]
        call = FakeCall(role=role, messages=msgs, schema=schema, max_tokens=max_tokens, temperature=temperature,
                        think=think, seed=seed)
        self.calls.append(call)

        async def raw(attempt_msgs: list[Message]) -> LLMResponse:
            call.attempts += 1
            text = self._render(self._pick(call), call)
            usage = LLMUsage(input_tokens=sum(len(m.content.split()) for m in attempt_msgs),
                             output_tokens=len(text.split()), model="fake", provider="fake")
            return LLMResponse(text=text, usage=usage)

        if schema is None:
            return await raw(msgs)
        return await generate_structured(raw, msgs, schema, max_repairs=self.max_repairs)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [fake_vector(t, self.embed_dim) for t in texts]

    async def classify(self, state: str, questions: list[ClassifyQuestion]) -> list[ClassifyAnswer]:
        self.classify_calls.append((state, list(questions)))
        out: list[ClassifyAnswer] = []
        for q in questions:
            options = _classify.options_for(q)
            answer = self._classify.get(q.name, options[0])
            out.append(ClassifyAnswer(name=q.name, answer=answer, probabilities={answer: 1.0}))
        return out

    # ------------------------------------------------------------------ internals
    def _pick(self, call: FakeCall) -> Reply:
        if call.schema is not None and call.schema in self._by_schema:
            return self._by_schema[call.schema].next()
        if call.role in self._by_role:
            return self._by_role[call.role].next()
        if self.handler is not None:
            return self.handler(call)
        if self.default is None:
            raise FakeLLMError(f"FakeLLM has no scripted reply for role={call.role!r} "
                               f"schema={getattr(call.schema, '__name__', None)!r}")
        if call.schema is not None:
            raise FakeLLMError(f"FakeLLM has no scripted reply for schema {call.schema.__name__} "
                               f"(use fake.on_schema({call.schema.__name__}, ...))")
        return self.default

    def _render(self, reply: Reply, call: FakeCall) -> str:
        if callable(reply) and not isinstance(reply, BaseModel | type):
            reply = reply(call)
        if isinstance(reply, str):
            return reply
        if isinstance(reply, BaseModel):
            return reply.model_dump_json()
        if isinstance(reply, Mapping | list):
            return json.dumps(reply, sort_keys=True)
        raise FakeLLMError(f"unsupported FakeLLM reply type: {type(reply).__name__}")


def fake_vector(text: str, dim: int = 8) -> list[float]:
    """Deterministic pseudo-embedding in [-1, 1] derived from SHA-256 of the text."""
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        out.extend(b / 127.5 - 1.0 for b in digest)
        counter += 1
    return [round(x, 6) for x in out[:dim]]
