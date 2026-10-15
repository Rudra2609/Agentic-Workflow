#!/usr/bin/env python3
"""Memory feasibility calculator (Member 11, prepared ahead of Sprint 11 items 11.2 / 11.14). Plain Python 3.11.

    memory = weights (the GGUF file) + KV cache (grows with the context length)

KV cache per token = 2 (K and V) x layers that have attention x KV heads x head size x bytes per value (f16 = 2).
**Hybrid models** such as Qwen 3.5 (``full_attention_interval`` = 4) keep a KV cache in only every 4th layer; the
other layers carry a small fixed-size recurrent state. The usual formula (every layer) overestimates them.

    python3 samples/models/memory.py qwen3.5:9b 32768         # one model at one context length
"""

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
GB = 1e9

# Laptop budget assumptions for the sizing table; Sprint 11 item 11.17 replaces them with measurements.
OS_AND_APPS_GB = 4.5  # macOS + browser + terminal, other heavy apps closed
DEMO_STACK_GB = 3.0  # Docker infra (Postgres, broker) + API + agent host + Next.js
HEADROOM_GB = 1.0  # stay out of swap


def specs() -> dict[str, dict]:
    return json.loads((DATA / "model_specs.json").read_text(encoding="utf-8"))


def kv_bytes_per_token(spec: dict, naive: bool = False, bytes_per_value: int = 2) -> int:
    layers = spec["block_count"]
    if spec.get("full_attention_interval") and not naive:
        layers //= spec["full_attention_interval"]
    head_dim = spec.get("attention.key_length") or spec["embedding_length"] // spec["attention.head_count"]
    kv_heads = spec.get("attention.head_count_kv") or spec["attention.head_count"]
    return 2 * layers * kv_heads * head_dim * bytes_per_value


def predict_gb(spec: dict, ctx: int = 8192, naive: bool = False) -> float:
    return (spec["file_bytes"] + kv_bytes_per_token(spec, naive) * ctx) / GB


def model_budget_gb(ram_gb: float) -> float:
    return ram_gb - OS_AND_APPS_GB - DEMO_STACK_GB - HEADROOM_GB


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    s = specs()[sys.argv[1]]
    ctx = int(sys.argv[2]) if len(sys.argv) > 2 else 8192
    print(f"{sys.argv[1]} at {ctx} tokens: weights {s['file_bytes'] / GB:.2f} GB + KV "
          f"{kv_bytes_per_token(s) * ctx / GB:.2f} GB = {predict_gb(s, ctx):.2f} GB")
