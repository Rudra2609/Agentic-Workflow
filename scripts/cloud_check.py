#!/usr/bin/env python3
"""Cloud key-pool check (doc 02 §2.5): does every cloud route in the role map still answer, and which keys work?

1. Keys: one ``GET /models`` per key (no tokens used). Prints only the key fingerprint, never the key.
2. Routes: one small JSON chat per ``role -> provider:model`` route, each tested on its own (no fallback), so a
   renamed or overloaded model shows up here instead of silently falling back to the local model during a demo.

Reads the keys and HMAP_CLOUD_ROLE_MAP from .env (empty map = the built-in DEFAULT_CLOUD_ROLE_MAP). Needs no Ollama.
Run: scripts/cloud_check.sh        Exit 0 = every role has at least one working cloud route.
"""

import asyncio
import json
import sys
import time

import httpx

from hmap.core.config import Settings
from hmap.core.llm.cloud import CloudRouter
from hmap.core.llm.key_pool import fingerprint
from hmap.core.llm.providers.base import ChatRequest
from hmap.core.llm.structured import extract_json

PROMPT = [{"role": "user", "content": 'Name 2 parts of a TCP chat server. Reply only with JSON {"parts": [...]}'}]


def _is_json(text: str) -> bool:
    try:
        json.loads(extract_json(text))
    except ValueError:
        return False
    return True


async def check_keys(settings: Settings, client: httpx.AsyncClient) -> None:
    for provider in ("groq", "gemini"):
        keys = settings.cloud_keys(provider)
        base = settings.cloud_base_url_for(provider)
        if not keys or not base:
            print(f"  {provider:7s} no keys configured")
            continue
        for key in keys:
            try:
                r = await client.get(f"{base.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"})
                status = "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
            except httpx.HTTPError as e:
                status = type(e).__name__
            print(f"  {fingerprint(provider, key):18s} {status}")


async def check_routes(settings: Settings, client: httpx.AsyncClient) -> bool:
    all_roles_ok = True
    for role, routes in settings.cloud_role_map.items():
        role_ok = False
        for provider, model in routes:
            one = settings.model_copy(update={"cloud_role_map": {role: [(provider, model)]}})
            router = CloudRouter.from_settings(one, client=client)
            if router is None:
                print(f"  {role:9s} {provider + ':' + model:36s} skipped (no {provider} keys)")
                continue
            t = time.perf_counter()
            resp = await router.chat(ChatRequest(model="-", messages=PROMPT, role=role, max_tokens=1024,
                                                 json_schema={"type": "object"}), plugin="cloud_check")
            secs = time.perf_counter() - t
            if resp is None:
                print(f"  {role:9s} {provider + ':' + model:36s} FAIL ({secs:.1f} s, every key failed; see log above)")
                continue
            parsed = _is_json(resp.text)
            role_ok = role_ok or parsed
            print(f"  {role:9s} {provider + ':' + model:36s} {'ok ' if parsed else 'BAD'} {secs:5.1f} s"
                  f"{'' if parsed else '  (answer was not JSON)'}")
        all_roles_ok = all_roles_ok and role_ok
    return all_roles_ok


async def main() -> int:
    settings = Settings.from_env()
    if not settings.cloud_ok:
        print("HMAP_CLOUD_OK=false: the cloud is switched off, nothing to check")
        return 0
    if not settings.cloud_role_map:
        print("HMAP_CLOUD_ROLE_MAP=none: every role is local, nothing to check")
        return 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        print("keys:")
        await check_keys(settings, client)
        print("routes (each on its own, no fallback):")
        ok = await check_routes(settings, client)
    print("CLOUD CHECK PASS" if ok else "CLOUD CHECK FAIL: some role has no working cloud route (it will run locally)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
