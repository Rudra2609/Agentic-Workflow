"""Speed (item 11.5): time to first token, generation and prefill tokens/s, cold load, resident memory.

Local models: Ollama directly (streaming, so TTFT is measured, not estimated), after unloading every model so the
cold load is real; fixed prompts, temperature 0, seed 42, ``think`` off; the median of ``runs``. Cloud models:
latency and output tokens/s through the key pool (no TTFT: the gateway does not stream), rate-limited calls counted,
not timed.

A machine with swap in use gives slow, noisy numbers: every result records the swap in use, and the docs mark
results taken over 1 GB of swap as "under swap" (``model-choice.md``: the bake-off speeds were).
"""

import asyncio
import json
import statistics
import time
from typing import Any

import httpx

from hmap.agents.models.bench.common import gateway_for, is_cloud
from hmap.agents.models.hardware import profile
from hmap.core.config import Settings
from hmap.core.errors import HmapError

PROMPTS = {
    "short_json": ('Return JSON {"title": string, "tags": [string]} for: "A TCP chat server where several clients '
                   'talk at once; nicknames are unique."'),
    "long_text": "Explain in about 250 words how a thread-per-client TCP server differs from an asyncio one.",
}


async def _unload_all(c: httpx.AsyncClient, base: str) -> None:
    ps = (await c.get(f"{base}/api/ps")).json().get("models", [])
    for m in ps:
        await c.post(f"{base}/api/generate", json={"model": m["name"], "keep_alive": 0})


async def local_speed(model: str, base_url: str, *, runs: int = 3) -> dict[str, Any]:
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=5.0)) as c:
        await _unload_all(c, base)
        started = time.perf_counter()
        r = await c.post(f"{base}/api/generate", json={"model": model, "keep_alive": "10m"})
        r.raise_for_status()
        cold = time.perf_counter() - started
        samples: dict[str, list[dict[str, float]]] = {k: [] for k in PROMPTS}
        for _ in range(runs):
            for name, prompt in PROMPTS.items():
                body = {"model": model, "stream": True, "think": False, "keep_alive": "10m",
                        "messages": [{"role": "user", "content": prompt}],
                        "options": {"temperature": 0, "seed": 42, "num_predict": 400, "num_ctx": 8192}}
                t0 = time.perf_counter()
                first = None
                final: dict[str, Any] = {}
                async with c.stream("POST", f"{base}/api/chat", json=body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if first is None and chunk.get("message", {}).get("content"):
                            first = time.perf_counter() - t0
                        if chunk.get("done"):
                            final = chunk
                ev, evd = final.get("eval_count", 0), final.get("eval_duration", 0) or 1
                pe, ped = final.get("prompt_eval_count", 0), final.get("prompt_eval_duration", 0) or 1
                samples[name].append({"ttft_s": first or 0.0, "tok_s": ev / evd * 1e9, "prefill_tok_s": pe / ped * 1e9,
                                      "out_tokens": ev})
        ps = (await c.get(f"{base}/api/ps")).json().get("models", [])
    resident = next((m.get("size", 0) / 1e9 for m in ps if m.get("name") == model), None)

    def med(name: str, key: str) -> float:
        return round(statistics.median(s[key] for s in samples[name]), 2)

    return {"model": model, "backend": "ollama", "cold_load_s": round(cold, 2), "resident_gb":
            round(resident, 2) if resident else None, "ttft_s": med("short_json", "ttft_s"),
            "tok_s": med("long_text", "tok_s"), "json_tok_s": med("short_json", "tok_s"),
            "prefill_tok_s": med("long_text", "prefill_tok_s"), "runs": runs}


async def cloud_speed(model: str, base: Settings, *, runs: int = 3) -> dict[str, Any]:
    gw = gateway_for(model, base, "live")
    rows, limited = [], 0
    for _ in range(runs):
        for prompt in PROMPTS.values():
            try:
                resp = await gw.generate("reasoner", [{"role": "user", "content": prompt}], temperature=0.0, seed=42,
                                         max_tokens=400)
            except HmapError:
                limited += 1
                continue
            u = resp.usage
            rows.append({"latency_s": u.latency_s, "tok_s": u.output_tokens / u.latency_s if u.latency_s else 0.0})
    await gw.aclose()
    if not rows:
        return {"model": model, "backend": "cloud", "answered": 0, "rate_limited_or_failed": limited}
    return {"model": model, "backend": "cloud", "answered": len(rows), "rate_limited_or_failed": limited,
            "latency_s": round(statistics.median(r["latency_s"] for r in rows), 2),
            "tok_s": round(statistics.median(r["tok_s"] for r in rows), 1), "runs": runs}


async def measure(models: list[str], base: Settings, *, runs: int = 3) -> dict[str, Any]:
    hw = await asyncio.to_thread(profile, base.ollama_base_url, docker=False)
    out: dict[str, Any] = {"_machine": {"chip": hw.chip, "total_gb": round(hw.total_gb, 1),
                                        "swap_used_gb": round(hw.swap_used_gb, 2),
                                        "under_swap": hw.swap_used_gb > 1.0, "at": time.strftime("%Y-%m-%dT%H:%M")}}
    for model in models:
        out[model] = (await cloud_speed(model, base, runs=runs) if is_cloud(model)
                      else await local_speed(model, base.ollama_base_url, runs=runs))
        print(model, out[model], flush=True)
    return out
