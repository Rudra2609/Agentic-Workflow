"""Warm-up on start (item 11.18): load the role map's local chat model(s) and the embedder before the first real
request, so the first step is not a 5-30 s cold load. ``make demo`` runs it in the background when Ollama is up
(``HMAP_WARMUP=false`` turns it off).

    uv run python -m hmap.agents.models.warmup              # preload, print seconds per model
    uv run python -m hmap.agents.models.warmup --measure    # first-call latency cold vs warm (eval.md)
"""

import argparse
import asyncio
import json
import time

import httpx

from hmap.agents.models.backends.local import OllamaBackend
from hmap.core.config import Settings


def models_to_load(settings: Settings) -> list[str]:
    chat = [m for r, m in settings.role_map.items() if r != "embed"]
    embed = settings.role_map.get("embed", "nomic-embed-text")
    return [*sorted(set(chat))[:1], embed]     # one heavy model (the 16 GB budget) + the embedder


async def warm(settings: Settings) -> dict[str, float]:
    backend = OllamaBackend(settings.ollama_base_url)
    out = {}
    try:
        for model in models_to_load(settings):
            try:
                out[model] = round(await backend.preload(model), 2)
            except httpx.HTTPError as exc:
                out[model] = -1.0
                print(f"warm-up {model}: {type(exc).__name__}")
    finally:
        await backend.aclose()
    return out


async def first_call(settings: Settings, model: str) -> float:
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.post(f"{settings.ollama_base_url.rstrip('/')}/api/chat", json={
            "model": model, "stream": False, "think": False, "messages": [{"role": "user", "content": "Say OK."}],
            "options": {"num_predict": 5}})
        r.raise_for_status()
    return round(time.perf_counter() - started, 2)


async def measure(settings: Settings) -> dict[str, float]:
    """First-call latency without warm-up (everything unloaded) and with it."""
    model = models_to_load(settings)[0]
    backend = OllamaBackend(settings.ollama_base_url)
    try:
        for loaded in (await backend.resident()):
            await backend.unload(loaded)
        cold = await first_call(settings, model)
        for loaded in (await backend.resident()):
            await backend.unload(loaded)
        warm_s = (await warm(settings)).get(model, -1.0)
        warmed = await first_call(settings, model)
    finally:
        await backend.aclose()
    return {"model": model, "first_call_cold_s": cold, "warm_up_s": warm_s,  # type: ignore[dict-item]
            "first_call_after_warm_up_s": warmed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--measure", action="store_true")
    s = Settings.from_env()
    print(json.dumps(asyncio.run(measure(s) if ap.parse_args().measure else warm(s)), indent=1))
