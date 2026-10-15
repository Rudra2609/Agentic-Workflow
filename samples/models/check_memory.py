#!/usr/bin/env python3
"""Predicted vs measured model memory, and the laptop sizing table (Member 11, prepared ahead of Sprint 11 items
11.2 / 11.14). Plain Python 3.11, reads only ``data/``.

    python3 samples/models/check_memory.py

Passes if the prediction (weights + KV cache at the bake-off's 8192-token context, no fitted constants) is within
0.35 GB on average of the memory Ollama reported, and the hybrid-aware KV formula has a lower average error than
the naive one (KV cache in every layer).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory import (DATA, DEMO_STACK_GB, GB, HEADROOM_GB, OS_AND_APPS_GB, kv_bytes_per_token,  # noqa: E402
                    model_budget_gb, predict_gb, specs)

CTX = 8192  # num_ctx used in the bake-off


def main() -> int:
    s = specs()
    measured = {m: v["resident_gb"] for m, v in json.loads((DATA / "speed.json").read_text(encoding="utf-8")).items()}
    print(f"{'model':18s} {'quant':7s} {'weights':>7s} {'KV/1k tok':>9s} {'predicted':>9s} {'naive':>6s} "
          f"{'measured':>8s} {'error':>6s}")
    errors, naive_all, naive_errors = [], [], {}
    for name, m in measured.items():
        spec = s[name]
        pred, naive = predict_gb(spec, CTX), predict_gb(spec, CTX, naive=True)
        errors.append(pred - m)
        naive_all.append(naive - m)
        if spec.get("full_attention_interval"):
            naive_errors[name] = (abs(naive - m), abs(pred - m))
        print(f"{name:18s} {spec['quant']:7s} {spec['file_bytes'] / GB:7.2f} "
              f"{kv_bytes_per_token(spec) * 1000 / GB:9.3f} {pred:9.2f} "
              f"{naive if spec.get('full_attention_interval') else pred:6.2f} {m:8.2f} {pred - m:+6.2f}")
    mae = sum(abs(e) for e in errors) / len(errors)
    print(f"\nmean absolute error {mae:.2f} GB over {len(errors)} models (no fitted constants); worst "
          f"{max(errors, key=abs):+.2f} GB")
    naive_mae = sum(abs(e) for e in naive_all) / len(naive_all)
    print(f"naive formula (KV cache in every layer): mean absolute error {naive_mae:.2f} GB")
    for name, (naive_err, err) in naive_errors.items():
        print(f"  {name}: hybrid-aware error {err:.2f} GB vs naive {naive_err:.2f} GB")
    print("  open question: qwen3.5:4b is ~0.5 GB above weights + KV. It is not the vision projector (0.68 GB, and the\n"
          "  9b shows no such gap). Sprint 11 measures /api/ps at 2-3 context lengths to split fixed from per-token cost.")

    print(f"\nSizing (assumed: OS + apps {OS_AND_APPS_GB} GB, demo stack {DEMO_STACK_GB} GB, headroom {HEADROOM_GB} GB;"
          f" + nomic-embed-text {s['nomic-embed-text:latest']['file_bytes'] / GB:.2f} GB resident)")
    embed = s["nomic-embed-text:latest"]["file_bytes"] / GB
    sizes = [("qwen3.5:4b", 8192), ("qwen3.5:9b", 8192), ("qwen3.5:9b", 32768), ("qwen3:8b", 32768),
             ("qwen3.5:9b + qwen3.5:4b", 8192)]
    print(f"{'laptop':>7s} {'budget':>7s}  " + "  ".join(f"{n.replace('qwen', 'q')}@{c // 1024}k" for n, c in sizes))
    for ram in (8, 16, 24, 32):
        budget = model_budget_gb(ram)
        cells = []
        for name, ctx in sizes:
            need = sum(predict_gb(s[n.strip()], ctx) for n in name.split("+")) + embed
            label = f"{n.replace('qwen', 'q')}@{ctx // 1024}k" if (n := name) else ""
            cells.append(f"{'fits' if need <= budget else 'no':>{len(label)}s}")
        print(f"{ram:5d}GB {budget:6.1f}G  " + "  ".join(cells))

    hybrid_better = mae < naive_mae
    ok = mae <= 0.35 and hybrid_better
    print("\nOK" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
