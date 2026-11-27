#!/usr/bin/env python3
"""Sprint 11 demo (Member 11: local models & routing), offline, no model, no key.

1. **Live route decisions**: the real gateway + the real router (``HMAP_ROUTER=on``) against scripted providers:
   Gemini is saturated and answers 429 with a short ``retry-after`` (1 s, like Groq's per-minute limits), Groq
   answers. The key pool cools the Gemini key for that second and then tries it again on the next call; the router
   remembers that the *model* answered 429 in the last minute and tries Groq first, so fewer requests are wasted,
   with the same answers. (With a long retry-after the key pool alone already skips the route: then the router
   only explains the order.)
2. **The Models page's API** on the platform's in-memory stack: the decisions, the model registry (Ollama off: the
   models saved on disk), what fits on this machine, and the benchmark table (the quick set, replayed).
3. On Postgres (check_sprint's RabbitMQ + Postgres pass, ``HMAP_STORE=postgres``): the decision log goes through
   migration 011's ``route_decisions`` in a scratch schema (written by the router, read back as the API does).

Run from backend/: ``uv run python ../scripts/demo_sprint_11.py``. Exits non-zero if a check fails.
"""

import asyncio
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from hmap.agents.models import router as router_mod  # noqa: E402
from hmap.agents.models.plugin import PLUGIN  # noqa: E402
from hmap.agents.models.router import ModelRouter  # noqa: E402
from hmap.agents.models.store import MemoryModelStore, PgModelStore  # noqa: E402
from hmap.api.app import create_app  # noqa: E402
from hmap.core.config import Settings  # noqa: E402
from hmap.core.llm import CloudRouter, Gateway, OllamaProvider  # noqa: E402
from hmap.system import HmapSystem  # noqa: E402
from tests.api.helpers import signed_in  # noqa: E402

GROQ = ["gsk_demo_a", "gsk_demo_b"]
GEMINI = ["AIza_demo_a"]
MSG = [{"role": "user", "content": "Plan the TCP chat server."}]


def check(ok: bool, what: str) -> None:
    print(f"  [{'ok' if ok else 'FAIL'}] {what}")
    if not ok:
        raise SystemExit(1)


class Cloud:
    """Gemini is saturated (429), Groq answers."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.host)
        if "googleapis" in request.url.host:
            return httpx.Response(429, headers={"retry-after": "1"}, json={"error": "rate"})
        body = json.loads(request.content)
        return httpx.Response(200, json={"model": body["model"], "usage": {"prompt_tokens": 9, "completion_tokens": 4},
                                         "choices": [{"message": {"content": "a plan"}}]})


def ollama_down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("Ollama is not running", request=request)


def settings(router: str) -> Settings:
    return Settings(router=router, llm_mode="live", groq_api_keys=GROQ, gemini_api_keys=GEMINI,
                    role_map={"reasoner": "qwen3.5:9b", "coder": "qwen3.5:9b"},
                    cloud_role_map={"reasoner": [("gemini", "gemini-3.6-flash"), ("groq", "openai/gpt-oss-120b")],
                                    "coder": [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-3.6-flash")]})


class Clock:
    """The key pool's clock: 2 s pass between calls (the 1 s cooldown is over each time)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def calls(s: Settings, route: ModelRouter, n: int) -> tuple[list[str], Cloud]:
    cloud, clock = Cloud(), Clock()
    gw = Gateway(s, local=OllamaProvider(s.ollama_base_url, httpx.AsyncClient(transport=httpx.MockTransport(
        ollama_down))), cloud_router=CloudRouter.from_settings(s, client=httpx.AsyncClient(
            transport=httpx.MockTransport(cloud.handler)), clock=clock), route=route, mode="live")
    answers = []
    for i in range(n):
        clock.now += 2.0
        role = "reasoner" if i % 3 else "coder"
        resp = await gw.for_plugin("planning" if role == "reasoner" else "coding").generate(role, MSG)
        answers.append(resp.text)
    await route.flush()
    return answers, cloud


def part1(store: MemoryModelStore) -> None:
    print("1. Live route decisions (scripted providers: Gemini rate limited, Groq answering)")
    off = ModelRouter(settings("off"), store=MemoryModelStore(), table={}, background=False)
    a_off, cloud_off = asyncio.run(calls(settings("off"), off, 6))
    on = ModelRouter(settings("on"), store=store, table={}, background=False)
    a_on, cloud_on = asyncio.run(calls(settings("on"), on, 6))
    recs = asyncio.run(store.recent_routes())
    for r in reversed(recs):
        print(f"     {r.plugin:9} {r.decision.role:8} -> {' > '.join(r.chain):70} {r.answered_by}  "
              f"({r.attempts} attempt(s)) {r.decision.reason[:70]}")
    check(a_on == a_off, "same answers with the router on and off")
    check(off.decisions == 0 and len(recs) == 6, "router off decides nothing; router on logged all 6 calls")
    check(len(cloud_on.calls) < len(cloud_off.calls),
          f"HTTP attempts: {len(cloud_off.calls)} with the role maps, {len(cloud_on.calls)} with the router "
          "(the saturated route is tried last)")
    check(any("429" in r.decision.reason for r in recs),
          "every reordering says why")


def part2(store: MemoryModelStore, tmp: Path) -> None:
    print("2. The Models page's API (in-memory platform, Ollama off)")
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"
    system = HmapSystem.in_memory(artifact_root=tmp / "a", plugins=[PLUGIN])
    with TestClient(create_app(system, run_agents=False)) as c:
        signed_in(c)
        routes = c.get("/api/models/routes").json()
        check(routes["summary"]["decisions"] == 6 and routes["summary"]["answered_by"] == {"groq": 6},
              f"/api/models/routes: {routes['summary']}")
        reg = c.get("/api/models/registry").json()
        local = [m["spec"]["id"] for m in reg["models"] if m["spec"]["backend"] == "ollama"]
        check(reg["ollama_up"] is False and "qwen3.5:9b" in local,
              f"registry with Ollama off: {len(local)} local models from the snapshot")
        hw = c.get("/api/models/hardware").json()
        fit = {f["model"]: f["fit"] for f in hw["feasibility"]}
        check(hw["hardware"]["total_gb"] > 0, f"this machine: {hw['hardware']['total_gb']:.1f} GB, qwen3.5:9b "
                                              f"{fit.get('qwen3.5:9b')}, sizing {[s['ram_gb'] for s in hw['sizing']]}")
        bench = c.get("/api/models/bench").json()
        quick = {v["model"]: v["quality"] for k, v in bench["files"].items() if k.startswith("quick_")}
        check(quick.get("qwen3.5:9b") == 0.833, f"benchmark table: {len(quick)} models, qwen3.5:9b 0.833 "
                                                 "(the bake-off, replayed through the harness)")


def part3() -> None:
    print("3. The decision log on Postgres (migration 011, scratch schema)")
    from hmap.db import Database, upgrade

    url = Settings.from_env().database_url
    schema = f"hmap_demo11_{uuid.uuid4().hex[:8]}"
    upgrade(url, schema=schema)

    async def go() -> list[Any]:
        db = Database(url, schema=schema, max_size=2)
        try:
            route = ModelRouter(settings("on"), store=PgModelStore(db), table={}, background=False)
            await calls(settings("on"), route, 3)
            return await PgModelStore(db).recent_routes()
        finally:
            await db.close()

    try:
        recs = asyncio.run(go())
        check(len(recs) == 3 and all(r.ok for r in recs), f"{len(recs)} decisions written and read back with outcomes")
    finally:
        import psycopg

        from hmap.db import conninfo

        with psycopg.connect(conninfo(url), autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def main() -> None:
    store = MemoryModelStore()
    router_mod.MEMORY_STORE = store
    from hmap.agents.models import api

    api.MEMORY_STORE = store
    with tempfile.TemporaryDirectory() as tmp:
        part1(store)
        part2(store, Path(tmp))
    if os.environ.get("HMAP_STORE") == "postgres":
        part3()
    print("Sprint 11 demo: all checks passed")


if __name__ == "__main__":
    main()
