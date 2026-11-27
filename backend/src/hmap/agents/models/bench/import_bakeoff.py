"""Turn the §0 bake-off's saved answers (``samples/model_bakeoff/results/<model>/*.jsonl``, every output kept) into
replay recordings for the quick set (``samples/llm_cache/models/<model>/bench/``).

The bake-off ran the same prompts with the same settings on the local models (2026-10-06 → 10-10), so its answers
*are* those models' answers: importing them makes the local half of the benchmark table reproducible offline, and
replaying them through :mod:`.quick` must give the bake-off's scores (a test checks it). The speeds are not imported
(taken under swap).

    uv run python -m hmap.agents.models.bench.import_bakeoff
"""

import json
from typing import Any

from hmap.agents.models.bench.common import CACHE, ROOT, bakeoff, slug
from hmap.agents.models.bench.quick import SUITE_ROLE, _prompt
from hmap.core.llm.base import Message
from hmap.core.llm.cache import ReplayCache, cache_key, key_ingredients
from hmap.core.llm.structured import inline_refs

BAKEOFF_RESULTS = ROOT / "samples" / "model_bakeoff" / "results"


def import_model(model: str) -> int:
    mb = bakeoff()
    src = BAKEOFF_RESULTS / model.replace(":", "_")
    cache = ReplayCache(CACHE / slug(model))
    n = 0
    for suite in SUITE_ROLE:
        path = src / f"{suite}.jsonl"
        if not path.exists():
            continue
        items = {i["id"]: i for i in mb.load_items(suite)}
        for line in path.read_text(encoding="utf-8").splitlines():
            row: dict[str, Any] = json.loads(line)
            item = items.get(row["id"])
            if item is None or "output" not in row:
                continue
            system, user, schema, num_predict = _prompt(mb, suite, item)
            msgs = [Message(role="system", content=system), Message(role="user", content=user)]
            schema_json = schema.model_json_schema() if schema is not None else None
            ing = key_ingredients(plugin="bench", role=SUITE_ROLE[suite], messages=msgs, schema=schema_json,
                                  temperature=0.0, max_tokens=num_predict, seed=42, think=False)
            cache.save("bench", cache_key(ing), {
                "role": SUITE_ROLE[suite], "prompt_version": "1", "key_ingredients": ing, "model": model,
                "model_digest": None, "provider": "ollama (imported from the bake-off)",
                "request": {"model": model, "messages": [m.model_dump() for m in msgs],
                            "format": inline_refs(schema_json) if schema_json else None},
                "response": {"text": row["output"], "usage": {"model": model, "provider": "ollama",
                                                              "input_tokens": row.get("in_tokens", 0),
                                                              "output_tokens": row.get("out_tokens", 0),
                                                              "latency_s": row.get("total_s", 0.0)}}})
            n += 1
    return n


if __name__ == "__main__":
    for d in sorted(p for p in BAKEOFF_RESULTS.iterdir() if p.is_dir() and not p.name.startswith("_")):
        meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {"model": d.name}
        print(meta["model"], import_model(meta["model"]))
