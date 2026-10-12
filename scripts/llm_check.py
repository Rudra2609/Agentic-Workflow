#!/usr/bin/env python3
"""LLM gateway smoke test (Sprint 1 DoD: "answers in live and replay modes").

1. ``record`` mode against the running Ollama: free text (role ``fast``), schema-constrained JSON (role ``reasoner``),
   ``classify`` and ``embed``. Record mode calls the model and writes each answer to the replay cache.
2. ``replay`` mode with Ollama pointed at a dead port: every answer must come back identical from the cache.

The cache goes to a temporary folder (never into samples/). Needs Ollama running with the models from HMAP_ROLE_MAP:
    OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama OLLAMA_MAX_LOADED_MODELS=2 ollama serve
Run: scripts/llm_check.sh        Exit 0 = pass.
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

from pydantic import BaseModel

from hmap.core.config import Settings
from hmap.core.llm import ClassifyQuestion
from hmap.core.llm.gateway import Gateway


class Verdict(BaseModel):
    language: str
    needs_network: bool
    components: list[str]


PROMPT = [{"role": "user", "content": "A student must write a multi-client TCP chat server in Python. "
           "Answer as JSON: the language, whether it needs networking, and 2-4 main components."}]
QUESTION = ClassifyQuestion(name="testable", kind="bool",
                            criteria={"true": "the requirement can be checked by an automated test"})


async def run(settings: Settings, mode: str) -> dict:
    gw = Gateway(settings, mode=mode, plugin="llm_check", cloud_ok=False)   # local only: no key is ever used
    out: dict = {}
    t = time.perf_counter()
    out["fast"] = (await gw.generate("fast", [{"role": "user", "content": "Reply with exactly the word: pong"}],
                                     max_tokens=16, seed=1)).text.strip()
    out["reasoner"] = (await gw.generate("reasoner", PROMPT, schema=Verdict, seed=1)).parsed.model_dump()
    out["classify"] = [a.answer for a in await gw.classify("The server must accept 10 clients at once.",
                                                           [QUESTION])]
    vecs = await gw.embed(["multi-client chat server"])
    out["embed_dim"] = len(vecs[0])
    out["seconds"] = round(time.perf_counter() - t, 1)
    return out


def main() -> int:
    base = Settings.from_env()
    cache = Path(tempfile.mkdtemp(prefix="hmap_llm_check_"))
    live = base.model_copy(update={"llm_cache_dir": cache})
    try:
        rec = asyncio.run(run(live, "record"))
    except Exception as e:  # report any provider failure plainly
        print(f"FAIL live/record: {type(e).__name__}: {e}\n(is Ollama running at {base.ollama_base_url}?)")
        return 1
    print(f"live   ({rec.pop('seconds')} s): {rec}")
    dead = live.model_copy(update={"ollama_base_url": "http://127.0.0.1:9"})   # proves replay never calls Ollama
    rep = asyncio.run(run(dead, "replay"))
    print(f"replay ({rep.pop('seconds')} s): {rep}")
    ok = rec == rep and rec["fast"] and rec["embed_dim"] > 0
    print(f"cache: {cache} ({sum(1 for _ in cache.rglob('*.json'))} files)")
    print("LLM CHECK PASS" if ok else "LLM CHECK FAIL: replay differs from live")
    return 0 if ok else 1


if __name__ == "__main__":
    os.environ.setdefault("HMAP_CLOUD_OK", "false")
    sys.exit(main())
