"""``read_images`` (role ``vision``, Sprint-2 OCR support): cloud only, cached by image hash, clear fallback signal."""

import base64
import json
from pathlib import Path

import pytest

from hmap.core.config import Settings
from hmap.core.llm import CloudRouter, FakeLLM, Gateway, OllamaProvider, VisionUnavailable
from hmap.core.llm.providers.openai_compat import with_images

from .conftest import FakeOllamaServer
from .test_key_pool import GEMINI_KEYS, GEMINI_URL, FakeClock, FakeCloud

PNG = b"\x89PNG\r\n\x1a\nfake-page-1"
JPEG = b"\xff\xd8\xff\xe0fake-photo"


@pytest.fixture
def cloud() -> FakeCloud:
    return FakeCloud()


@pytest.fixture
def vision_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={
        "gemini_api_keys": Settings(gemini_api_keys=GEMINI_KEYS).gemini_api_keys,
        "cloud_role_map": {"vision": [("gemini", "gemini-x")]}})


def gateway(s: Settings, cloud: FakeCloud, server: FakeOllamaServer) -> Gateway:
    router = CloudRouter.from_settings(s, client=cloud.client(), clock=FakeClock())
    return Gateway(s, local=OllamaProvider(s.ollama_base_url, server.client()), cloud_router=router)


def test_with_images_builds_openai_content_parts() -> None:
    b64_png, b64_jpg = base64.b64encode(PNG).decode(), base64.b64encode(JPEG).decode()
    msgs = with_images([{"role": "system", "content": "s"}, {"role": "user", "content": "read"}], [b64_png, b64_jpg])
    assert msgs[0] == {"role": "system", "content": "s"}
    parts = msgs[1]["content"]
    assert parts[0] == {"type": "text", "text": "read"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_read_images_goes_to_the_vision_route_with_the_image(vision_settings: Settings, cloud: FakeCloud,
                                                                   server: FakeOllamaServer) -> None:
    resp = await gateway(vision_settings, cloud, server).read_images("Transcribe this page.", [PNG])
    assert resp.usage.provider == "gemini" and cloud.urls == [GEMINI_URL]
    body = json.loads(cloud.requests[0].content)
    assert body["model"] == "gemini-x"
    assert body["messages"][-1]["content"][1]["image_url"]["url"] == (
        "data:image/png;base64," + base64.b64encode(PNG).decode())
    assert server.requests == []  # never the local model


async def test_read_images_unavailable_without_route_or_permission(vision_settings: Settings, cloud: FakeCloud,
                                                                   server: FakeOllamaServer) -> None:
    no_route = vision_settings.model_copy(update={"cloud_role_map": {"coder": [("gemini", "g")]}})
    with pytest.raises(VisionUnavailable):
        await gateway(no_route, cloud, server).read_images("read", [PNG])
    with pytest.raises(VisionUnavailable):  # a "Keep on this computer" project
        await gateway(vision_settings, cloud, server).local_only().read_images("read", [PNG])
    with pytest.raises(VisionUnavailable):
        await gateway(vision_settings.model_copy(update={"cloud_ok": False}), cloud, server).read_images("r", [PNG])
    assert cloud.requests == [] and server.requests == []


async def test_read_images_all_keys_failing_raises(vision_settings: Settings, cloud: FakeCloud,
                                                   server: FakeOllamaServer) -> None:
    cloud.script[GEMINI_KEYS[0]] = [503]
    with pytest.raises(VisionUnavailable):
        await gateway(vision_settings, cloud, server).read_images("read", [PNG])
    assert server.requests == []


async def test_record_then_replay_keys_on_image_hash(vision_settings: Settings, cloud: FakeCloud,
                                                     server: FakeOllamaServer) -> None:
    rec = vision_settings.model_copy(update={"llm_mode": "record"})
    first = await gateway(rec, cloud, server).for_plugin("doc_intel").read_images("read", [PNG])
    raw = next(Path(rec.llm_cache_dir).rglob("*.json")).read_text(encoding="utf-8")
    assert base64.b64encode(PNG).decode() not in raw and GEMINI_KEYS[0] not in raw  # hash only, no key
    replay = Gateway(rec.model_copy(update={"llm_mode": "replay"})).for_plugin("doc_intel")
    assert (await replay.read_images("read", [PNG])).text == first.text
    with pytest.raises(Exception, match="replay"):
        await replay.read_images("read", [JPEG])  # another image is another key


async def test_fake_llm_vision_is_scripted_or_unavailable() -> None:
    fake = FakeLLM()
    with pytest.raises(VisionUnavailable):
        await fake.read_images("read", [PNG])
    fake.on_vision("page one text", lambda prompt, images: f"{len(images)} images")
    assert (await fake.read_images("read", [PNG])).text == "page one text"
    assert (await fake.read_images("read", [PNG, JPEG])).text == "2 images"
    assert fake.vision_calls == [("read", 1), ("read", 1), ("read", 2)]
    gw = Gateway(Settings(llm_mode="fake"), fake=fake)
    assert (await gw.read_images("read", [PNG])).text == "1 images"  # the last scripted reply repeats
