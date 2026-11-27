"""Quantization study (item 11.6): ≥ 2 quants of one model and ≥ 2 sizes on the quick set, with speed and memory.

Recommendation rule (stated before the numbers): among the variants, the **smallest resident memory whose quality
is within ``NOISE`` of the best** (88 items: differences of ~0.01 are noise, samples/models/README.md); ties → the
faster one.
"""

from typing import Any

NOISE = 0.015


def report(quick: dict[str, dict[str, Any]], speed: dict[str, Any], variants: list[str]) -> dict[str, Any]:
    rows = []
    for model in variants:
        q = quick.get(model)
        sp = speed.get(model, {})
        rows.append({"model": model, "quality": q.get("quality") if q else None,
                     "suites": {k: v.get("score") for k, v in (q or {}).get("suites", {}).items()},
                     "resident_gb": sp.get("resident_gb"), "tok_s": sp.get("tok_s"), "ttft_s": sp.get("ttft_s"),
                     "cold_load_s": sp.get("cold_load_s"), "measured": q is not None})
    scored = [r for r in rows if r["quality"] is not None]
    rec = None
    if scored:
        best = max(r["quality"] for r in scored)
        near = [r for r in scored if r["quality"] >= best - NOISE]
        rec = min(near, key=lambda r: (r["resident_gb"] if r["resident_gb"] is not None else 99.0,
                                       -(r["tok_s"] or 0.0)))["model"]
    missing = [r["model"] for r in rows if not r["measured"]]
    return {"variants": rows, "recommendation": rec, "rule": f"smallest memory within {NOISE} of the best quality",
            "not_measured": missing}
