"""Taxonomy accuracy (item 4.7) on ``samples/refine/taxonomy_gold.jsonl`` (80 labelled issues: 30 from the critics'
recorded runs, 50 written by hand; all 10 categories).

    uv run python -m tests.refine.eval.taxonomy_eval                 # replay (recorded classify answers)
    HMAP_LLM_RECORD_MISSING=refine uv run python -m tests.refine.eval.taxonomy_eval   # record missing answers

The rules were revised once, looking only at the even-numbered items ("dev"); the odd-numbered half ("test") is
held out, so its numbers are the fair ones. Reports: rules alone (how many they label, and how many of those
right), the model alone (``classify`` on every item), the combination the library uses (rules first, ``classify``
for the rest) and, for the critics' own issues, the label the critic gave.
Results: ``samples/refine/eval_results/taxonomy.json``.
"""

import argparse
import asyncio
import json
from collections import Counter
from typing import Any

from hmap.agents.refine.core import RefineContext
from hmap.agents.refine.taxonomy import question, rule_label
from hmap.core.config import REPO_ROOT
from hmap.core.llm.base import LLMClient
from tests.refine.eval.run_eval import RESULTS, gateway

GOLD = REPO_ROOT / "samples" / "refine" / "taxonomy_gold.jsonl"


def load() -> list[dict[str, Any]]:
    return [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]


def rules_only(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fired = right = 0
    for r in rows:
        label, _ = rule_label(r["text"], r.get("code"))
        if label is not None:
            fired += 1
            right += label == r["label"]
    return {"labelled": fired, "right": right, "coverage": round(fired / len(rows), 3),
            "precision": round(right / max(1, fired), 3), "accuracy_all": round(right / len(rows), 3)}


async def model_labels(rows: list[dict[str, Any]], llm: LLMClient) -> list[str | None]:
    ctx = RefineContext(llm=llm)
    out: list[str | None] = []
    for r in rows:
        try:
            [answer] = await ctx.classify(r["text"][:600], [question()])
            out.append(answer.answer)
        except Exception:
            out.append(None)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=("replay", "live"), default="replay")
    args = ap.parse_args()
    rows = load()
    llm = gateway(args.mode, "refine")
    rules = rules_only(rows)
    model = await model_labels(rows, llm)
    model_right = sum(m == r["label"] for m, r in zip(model, rows, strict=True))
    combined = []
    for m, r in zip(model, rows, strict=True):
        label, _ = rule_label(r["text"], r.get("code"))
        combined.append(label if label is not None else m)
    combined_right = sum(c == r["label"] for c, r in zip(combined, rows, strict=True))
    critic_rows = [r for r in rows if r["source"] == "llm"]
    critic_right = sum(r["critic_label"] == r["label"] for r in critic_rows)
    lib_on_critic = sum(c == r["label"] for c, r in zip(combined, rows, strict=True) if r["source"] == "llm")
    confusion = Counter((r["label"], c) for c, r in zip(combined, rows, strict=True) if c != r["label"])
    per_label = {lab: f"{sum(1 for c, r in zip(combined, rows, strict=True) if r['label'] == lab and c == lab)}/"
                      f"{sum(1 for r in rows if r['label'] == lab)}" for lab in sorted({r["label"] for r in rows})}
    split = {name: rules_only([r for n, r in enumerate(rows) if n % 2 == half])
             for half, name in ((0, "dev"), (1, "test"))}
    pairs = list(enumerate(zip(combined, rows, strict=True)))
    split_combined = {name: round(sum(c == r["label"] for n, (c, r) in pairs if n % 2 == half) / (len(rows) // 2), 3)
                      for half, name in ((0, "dev"), (1, "test"))}
    out = {"items": len(rows), "rules": rules, "rules_by_half": split, "rules_then_model_by_half": split_combined,
           "model": {"right": model_right, "accuracy": round(model_right / len(rows), 3),
                     "failed": sum(m is None for m in model)},
           "rules_then_model": {"right": combined_right, "accuracy": round(combined_right / len(rows), 3),
                                "per_label": per_label,
                                "confusions": {f"{a} -> {b}": n for (a, b), n in confusion.most_common()}},
           "critic_issues": {"items": len(critic_rows), "critic_label_right": critic_right,
                             "library_label_right": lib_on_critic}}
    print(json.dumps(out, indent=1))
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "taxonomy.json").write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
