import httpx
import pytest

from hmap.core.errors import ModelTransientError, is_retryable
from hmap.core.llm import ChatRequest, LLMProviderError, OllamaProvider

from .conftest import FakeOllamaServer

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


async def test_chat_request_shape(server: FakeOllamaServer, ollama: OllamaProvider) -> None:
    resp = await ollama.chat(ChatRequest(model="qwen3:8b", messages=[{"role": "user", "content": "hi"}],
                                         json_schema=SCHEMA, max_tokens=99, temperature=0.1, seed=7))
    req = server.requests[0]
    assert req.method == "POST" and str(req.url) == "http://ollama.test:11434/api/chat"
    body = server.bodies[0]
    assert body["model"] == "qwen3:8b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["format"] == SCHEMA
    assert body["options"] == {"temperature": 0.1, "num_predict": 99, "seed": 7}
    assert "keep_alive" not in body
    assert resp.text == "hello"
    assert resp.usage.input_tokens == 11 and resp.usage.output_tokens == 7
    assert resp.usage.provider == "ollama" and resp.usage.model == "qwen3:8b"


async def test_optional_fields_num_ctx_keep_alive_and_think_opt_in(server: FakeOllamaServer) -> None:
    provider = OllamaProvider("http://ollama.test:11434/", server.client(), keep_alive="10m", num_ctx=8192)
    await provider.chat(ChatRequest(model="m", messages=[], think=True))
    body = server.bodies[0]
    assert body["think"] is True
    assert body["keep_alive"] == "10m"
    assert body["options"]["num_ctx"] == 8192
    assert "format" not in body and "seed" not in body["options"]


async def test_think_400_falls_back_without_think(server: FakeOllamaServer, ollama: OllamaProvider) -> None:
    def chat(body: dict[str, object]) -> httpx.Response:
        if "think" in body:
            return httpx.Response(400, json={"error": '"llama3.1:8b" does not support thinking'})
        return httpx.Response(200, json={"model": "llama3.1:8b", "message": {"content": "ok"}})

    server.chat_handler = chat
    resp = await ollama.chat(ChatRequest(model="llama3.1:8b", messages=[{"role": "user", "content": "x"}]))
    assert resp.text == "ok"
    assert ["think" in b for b in server.bodies] == [True, False]
    # remembered: the next call skips the field straight away
    await ollama.chat(ChatRequest(model="llama3.1:8b", messages=[]))
    assert "think" not in server.bodies[-1] and len(server.requests) == 3


async def test_other_400_is_not_retried(server: FakeOllamaServer, ollama: OllamaProvider) -> None:
    server.chat_handler = lambda body: httpx.Response(400, json={"error": "invalid format schema"})
    with pytest.raises(LLMProviderError):
        await ollama.chat(ChatRequest(model="m", messages=[]))
    assert len(server.requests) == 1


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"),
                                 httpx.RemoteProtocolError("eof")])
async def test_transport_errors_map_to_model_transient(exc: Exception) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise exc

    provider = OllamaProvider("http://ollama.test:11434", httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    with pytest.raises(ModelTransientError) as info:
        await provider.chat(ChatRequest(model="m", messages=[]))
    assert info.value.retryable and is_retryable(info.value.code)


async def test_5xx_is_transient_and_404_is_not(server: FakeOllamaServer, ollama: OllamaProvider) -> None:
    server.chat_handler = lambda body: httpx.Response(503, text="loading")
    with pytest.raises(ModelTransientError):
        await ollama.chat(ChatRequest(model="m", messages=[]))
    server.chat_handler = lambda body: httpx.Response(404, json={"error": "model 'm' not found"})
    with pytest.raises(LLMProviderError) as info:
        await ollama.chat(ChatRequest(model="m", messages=[]))
    assert not info.value.retryable and "ollama pull m" in str(info.value)


async def test_embed_request_shape(server: FakeOllamaServer, ollama: OllamaProvider) -> None:
    vectors = await ollama.embed("nomic-embed-text", ["a", "b"])
    assert vectors == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    assert server.paths() == ["/api/embed"]
    assert server.bodies[0] == {"model": "nomic-embed-text", "input": ["a", "b"]}


async def test_unload_guard_when_switching_heavy_models(server: FakeOllamaServer, ollama: OllamaProvider) -> None:
    await ollama.chat(ChatRequest(model="qwen3:8b", messages=[]))
    await ollama.chat(ChatRequest(model="qwen3:8b", messages=[]))  # same model: no unload
    await ollama.embed("nomic-embed-text", ["x"])  # embedding: never triggers or counts as a switch
    await ollama.chat(ChatRequest(model="llama3.1:8b", messages=[]))
    assert server.paths() == ["/api/chat", "/api/chat", "/api/embed", "/api/generate", "/api/chat"]
    assert server.bodies[3] == {"model": "qwen3:8b", "keep_alive": 0}


async def test_unload_guard_respects_heaviness_and_can_be_disabled(server: FakeOllamaServer) -> None:
    light = {"llama3.2:3b"}
    provider = OllamaProvider("http://h", server.client(), is_heavy=lambda m: m not in light)
    await provider.chat(ChatRequest(model="qwen3:8b", messages=[]))
    await provider.chat(ChatRequest(model="llama3.2:3b", messages=[]))
    assert "/api/generate" not in server.paths()

    disabled = OllamaProvider("http://h", server.client(), is_heavy=None)
    await disabled.chat(ChatRequest(model="a", messages=[]))
    await disabled.chat(ChatRequest(model="b", messages=[]))
    assert "/api/generate" not in server.paths()


async def test_unload_failure_does_not_break_the_call(server: FakeOllamaServer) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/generate":
            raise httpx.ConnectError("gone")
        return server.handler(request)

    provider = OllamaProvider("http://h", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await provider.chat(ChatRequest(model="a", messages=[]))
    resp = await provider.chat(ChatRequest(model="b", messages=[]))
    assert resp.text == "hello"
