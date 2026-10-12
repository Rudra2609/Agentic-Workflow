import pytest
from pydantic import BaseModel

from hmap.core.llm import LLMResponse, LLMUsage, Message, StructuredOutputError, generate_structured
from hmap.core.llm.structured import extract_json, inline_refs


class Plan(BaseModel):
    steps: list[str]


class Outer(BaseModel):
    plan: Plan
    note: str


def scripted(*texts: str) -> tuple[list[list[Message]], object]:
    seen: list[list[Message]] = []

    async def call(messages: list[Message]) -> LLMResponse:
        seen.append(list(messages))
        text = texts[min(len(seen) - 1, len(texts) - 1)]
        return LLMResponse(text=text, usage=LLMUsage(input_tokens=10, output_tokens=5, latency_s=0.5))

    return seen, call


async def test_repair_succeeds_on_second_try() -> None:
    seen, call = scripted('{"steps": "oops"}', '{"steps": ["a", "b"]}')
    resp = await generate_structured(call, [Message(role="user", content="plan")], Plan)  # type: ignore[arg-type]
    assert resp.parsed == Plan(steps=["a", "b"])
    assert len(seen) == 2
    repair = seen[1]
    assert [m.role for m in repair] == ["user", "assistant", "user"]
    assert repair[1].content == '{"steps": "oops"}'
    assert "Validation error" in repair[2].content and "steps" in repair[2].content
    assert resp.usage.input_tokens == 20 and resp.usage.output_tokens == 10 and resp.usage.latency_s == 1.0


async def test_fails_after_three_bad_answers() -> None:
    seen, call = scripted("nope", "still nope", "{}", '{"steps": []}')
    with pytest.raises(StructuredOutputError) as info:
        await generate_structured(call, [Message(role="user", content="plan")], Plan)  # type: ignore[arg-type]
    assert len(seen) == 3
    assert info.value.details["attempts"] == 3
    assert not info.value.retryable


def test_extract_json_handles_fences_think_and_prose() -> None:
    assert extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('<think>hmm {no}</think>{"a": 1}') == '{"a": 1}'
    assert extract_json('Sure! Here it is: {"a": [1]} hope that helps') == '{"a": [1]}'


def test_inline_refs_flattens_defs() -> None:
    flat = inline_refs(Outer.model_json_schema())
    assert "$defs" not in flat
    assert flat["properties"]["plan"]["properties"]["steps"]["type"] == "array"


def test_inline_refs_leaves_recursive_schema_alone() -> None:
    class Node(BaseModel):
        children: list["Node"] = []

    schema = Node.model_json_schema()
    assert inline_refs(schema) == schema
