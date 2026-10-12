import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from hmap.core.config import Settings
from hmap.core.llm import (
    Gateway,
    LLMConfigError,
    Message,
    OllamaProvider,
    ReplayCache,
    ReplayMissError,
    cache_key,
    key_ingredients,
)
from hmap.core.llm.cache import validate_plugin_name

from .conftest import FakeOllamaServer


class Answer(BaseModel):
    value: str


class Other(BaseModel):
    value: int


MSGS = [Message(role="system", content="You extract things."), Message(role="user", content="doc text")]


def key(**overrides: Any) -> str:
    base: dict[str, Any] = {"plugin": "doc_intel", "role": "reasoner", "messages": MSGS,
                               "schema": Answer.model_json_schema(), "temperature": 0.2, "max_tokens": 1024,
                               "seed": None, "think": False}
    base.update(overrides)
    return cache_key(key_ingredients(**base))


def test_key_changes_with_each_ingredient() -> None:
    k = key()
    assert len(k) == 64
    assert key() == k
    assert key(messages=[*MSGS, Message(role="user", content="more")]) != k
    assert key(messages=[MSGS[0], Message(role="user", content="other doc")]) != k
    assert key(schema=Other.model_json_schema()) != k
    assert key(schema=None) != k
    assert key(temperature=0.0) != k
    assert key(max_tokens=10) != k
    assert key(seed=1) != k
    assert key(think=True) != k
    assert key(role="judge") != k
    assert key(plugin="research") != k
    assert key(temperature=0) == key(temperature=0.0)


def gateway(settings: Settings, server: FakeOllamaServer, **kwargs: Any) -> Gateway:
    return Gateway(settings, local=OllamaProvider(settings.ollama_base_url, server.client()), mode="record",
                   **kwargs)


async def test_key_ignores_preamble_and_model_name(settings: Settings, server: FakeOllamaServer,
                                                   tmp_path: Path) -> None:
    server.replies = ['{"value": "x"}']
    a = gateway(settings, server, preamble="SHARED PREAMBLE v1").for_plugin("doc_intel")
    await a.generate("reasoner", MSGS, schema=Answer)
    other_settings = settings.model_copy(update={"role_map": {"reasoner": "llama3.1:8b"}})
    b = gateway(other_settings, server, preamble="SHARED PREAMBLE v2 -- changed").for_plugin("doc_intel")
    await b.generate("reasoner", MSGS, schema=Answer)
    files = list((settings.llm_cache_dir / "doc_intel").glob("*/*.json"))
    assert len(files) == 1  # same key both times
    # the preamble was sent to the model and stored in the file, but is not part of the key
    assert server.bodies[0]["messages"][0] == {"role": "system", "content": "SHARED PREAMBLE v1"}
    assert server.bodies[1]["model"] == "llama3.1:8b"
    record = json.loads(files[0].read_text())
    assert record["request"]["messages"][0]["content"] == "SHARED PREAMBLE v2 -- changed"
    assert record["model"] == "llama3.1:8b"
    assert record["key"] == key()


async def test_file_layout(settings: Settings, server: FakeOllamaServer) -> None:
    gw = gateway(settings, server).for_plugin("doc_intel", prompt_version="3")
    await gw.generate("reasoner", MSGS)
    k = key(schema=None)
    path = settings.llm_cache_dir / "doc_intel" / k[:2] / f"{k}.json"
    assert path.is_file()
    record = json.loads(path.read_text())
    assert record["plugin"] == "doc_intel" and record["role"] == "reasoner"
    assert record["prompt_version"] == "3"
    assert record["response"]["text"] == "hello"
    assert record["response"]["usage"]["input_tokens"] == 11
    assert record["key_ingredients"]["messages"][1]["content"] == "doc text"
    assert not list(path.parent.glob(".tmp-*"))


async def test_replay_miss_lists_ingredients_and_closest_entry(settings: Settings, server: FakeOllamaServer) -> None:
    await gateway(settings, server).for_plugin("doc_intel").generate("reasoner", MSGS, temperature=0.2)
    replay = Gateway(settings, mode="replay").for_plugin("doc_intel")
    with pytest.raises(ReplayMissError) as info:
        await replay.generate("reasoner", MSGS, temperature=0.7)
    text = str(info.value)
    assert "LLM replay miss" in text
    assert "temperature = 0.7" in text and "role        = 'reasoner'" in text
    assert "plugin      = 'doc_intel'" in text and "doc text" in text
    assert "differs in: temperature" in text
    assert not info.value.retryable


async def test_prompt_version_bump_forces_rerecord(settings: Settings, server: FakeOllamaServer) -> None:
    await gateway(settings, server).for_plugin("doc_intel", prompt_version="1").generate("reasoner", MSGS)
    replay = Gateway(settings, mode="replay").for_plugin("doc_intel", prompt_version="2")
    with pytest.raises(ReplayMissError, match="prompt_version='1'"):
        await replay.generate("reasoner", MSGS)


def test_plugin_name_must_be_a_safe_folder(tmp_path: Path) -> None:
    assert validate_plugin_name("doc_intel") == "doc_intel"
    for bad in ("../x", "a/b", "", ".."):
        with pytest.raises(LLMConfigError):
            validate_plugin_name(bad)
    assert ReplayCache(tmp_path).path_for("p", "ab" + "0" * 62) == tmp_path / "p" / "ab" / ("ab" + "0" * 62 + ".json")
