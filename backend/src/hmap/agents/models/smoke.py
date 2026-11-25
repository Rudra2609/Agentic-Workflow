"""Live smoke test through the gateway **as the platform builds it** (``make_llm`` with the discovered plug-ins, so
the ``llm_provider`` slot is in it): free text (``fast``), schema JSON (``reasoner``), ``classify``, ``embed``.
Used by the release matrix (item 11.19) for the live-smoke and tier-1 cells, with ``HMAP_ROUTER`` on and off.

    uv run python -m hmap.agents.models.smoke            # exit 0 = every call answered
"""

import asyncio
import json
import sys
import time

from pydantic import BaseModel

from hmap.agents.models.router import ModelRouter
from hmap.core.config import Settings
from hmap.core.llm import ClassifyQuestion
from hmap.core.runtime.discovery import discover
from hmap.core.runtime.host import make_llm


class Title(BaseModel):
    title: str


async def run(settings: Settings) -> dict[str, object]:
    llm = make_llm(settings, discover(settings.enabled_plugins())).for_plugin("smoke")  # type: ignore[attr-defined]
    out: dict[str, object] = {"router": settings.router, "mode": settings.llm_mode}
    started = time.perf_counter()
    try:
        a = await llm.generate("fast", [{"role": "user", "content": "Say OK."}], max_tokens=20)
        out["fast"] = f"{a.usage.provider}:{a.usage.model}"
        b = await llm.generate("reasoner", [{"role": "user", "content": "A title for a TCP chat server lab."}],
                               schema=Title, max_tokens=200)
        out["reasoner"] = f"{b.usage.provider}:{b.usage.model}"
        c = await llm.classify("A test failed with ConnectionResetError.",
                               [ClassifyQuestion(name="kind", kind="choice", options=["network", "logic"])])
        out["classify"] = c[0].answer
        out["embed_dims"] = len((await llm.embed(["hello"]))[0])
        out["ok"] = True
    except Exception as exc:  # the matrix reports the cell as red with the reason
        out["ok"], out["error"] = False, f"{type(exc).__name__}: {str(exc)[:200]}"
    route = getattr(llm, "route", None)
    if isinstance(route, ModelRouter):
        out["decisions"] = route.decisions
        await route.aclose()
    out["seconds"] = round(time.perf_counter() - started, 1)
    await llm.aclose()
    return out


if __name__ == "__main__":
    res = asyncio.run(run(Settings.from_env()))
    print(json.dumps(res, indent=1))
    sys.exit(0 if res.get("ok") else 1)
