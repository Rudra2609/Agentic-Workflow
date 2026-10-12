from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from hmap.core.llm import ClassifyQuestion, FakeCall, FakeLLM, FakeLLMError, StructuredOutputError
from hmap.core.llm.providers import parse_retry_after


class Plan(BaseModel):
    steps: list[str]


async def test_scripted_by_role_schema_and_callable() -> None:
    fake = FakeLLM(handler=lambda call: f"echo:{call.messages[-1].content}")
    fake.on_role("fast", "one", "two")
    fake.on_schema(Plan, {"steps": ["a"]})
    msgs = [{"role": "user", "content": "hi"}]
    assert (await fake.generate("fast", msgs)).text == "one"
    assert (await fake.generate("fast", msgs)).text == "two"
    assert (await fake.generate("fast", msgs)).text == "two"  # last repeats
    assert (await fake.generate("judge", msgs)).text == "echo:hi"
    resp = await fake.generate("fast", msgs, schema=Plan)  # schema match wins over role
    assert resp.parsed == Plan(steps=["a"])
    assert [c.role for c in fake.calls] == ["fast", "fast", "fast", "judge", "fast"]
    assert fake.calls[-1].schema is Plan and fake.calls[-1].attempts == 1


async def test_fake_runs_the_repair_loop() -> None:
    fake = FakeLLM().on_schema(Plan, "nope", Plan(steps=["x"]))
    resp = await fake.generate("reasoner", [{"role": "user", "content": "p"}], schema=Plan)
    assert resp.parsed == Plan(steps=["x"]) and fake.calls[0].attempts == 2

    bad = FakeLLM().on_schema(Plan, "nope")
    with pytest.raises(StructuredOutputError):
        await bad.generate("reasoner", [{"role": "user", "content": "p"}], schema=Plan)
    assert bad.calls[0].attempts == 3


async def test_fake_defaults_and_errors() -> None:
    fake = FakeLLM()
    assert (await fake.generate("reasoner", [{"role": "user", "content": "x"}])).text == "fake response"
    with pytest.raises(FakeLLMError, match="on_schema"):
        await fake.generate("reasoner", [{"role": "user", "content": "x"}], schema=Plan)
    with pytest.raises(FakeLLMError):
        await FakeLLM(default=None).generate("reasoner", [{"role": "user", "content": "x"}])


async def test_fake_embed_and_classify_are_deterministic() -> None:
    a, b = FakeLLM(embed_dim=40), FakeLLM(embed_dim=40)
    va = await a.embed(["x", "y"])
    assert va == await b.embed(["x", "y"]) and len(va[0]) == 40 and va[0] != va[1]
    assert all(-1.0 <= x <= 1.0 for x in va[0])
    fake = FakeLLM().on_classify("route", "code")
    answers = await fake.classify("s", [ClassifyQuestion(name="route", kind="choice", options=["docs", "code"]),
                                        ClassifyQuestion(name="ok", kind="bool")])
    assert [(x.name, x.answer) for x in answers] == [("route", "code"), ("ok", "yes")]


async def test_reset_rewinds_scripts() -> None:
    fake = FakeLLM().on_role("fast", "1", "2")
    await fake.generate("fast", [])
    fake.reset()
    assert not fake.calls
    assert (await fake.generate("fast", [])).text == "1"


def test_fake_call_is_inspectable() -> None:
    call = FakeCall(role="fast", messages=[])
    assert call.attempts == 0 and call.schema is None


def test_parse_retry_after() -> None:
    now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert parse_retry_after("2") == 2.0
    assert parse_retry_after("0.5") == 0.5
    assert parse_retry_after(None) is None and parse_retry_after("soon") is None
    assert parse_retry_after("Thu, 01 Jan 2026 00:00:30 GMT", now=now) == 30.0
