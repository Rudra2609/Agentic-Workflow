"""Fine-tune evaluation (item 11.11): base vs base + LoRA, both on MLX with greedy decoding (same engine, so the
adapter is the only difference).

- **held-out skill test**: the M6 benchmark (``samples/verify/benchmark.jsonl``, never trained on; trap T15) as
  Member 6's own entailment prompt (``hmap.agents.verify.entail.messages``). Gold: a clean / natural claim the
  benchmark marks VERIFIED → ``supports``; ``wrong_number`` / ``unsupported_claim`` → ``not_enough``. Fake quotes
  and contradictions are left out: they are caught by other layers (L1 quote check, counter-evidence), not by
  this judgement alone. Plus the in-distribution test split (``data/test.jsonl``, the cloud judge's answers).
- **regression check on unrelated tasks**: the bake-off's critique items and the first 5 extraction documents,
  scored by the bake-off's code.

Both arms get the JSON schema as the same system hint the gateway sends to a server without schema-constrained
decoding (``OpenAICompatProvider``, ``json_mode="none"``): without it the untrained model answers in a JSON shape of
its own (``"supported": true``), which the platform never sees, and the comparison would only measure the format.

Honest by construction: a null or negative result is written as it is (plan D10).

    uv run python -m hmap.agents.models.finetune.eval --adapter samples/models/finetune/adapters/<run>
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hmap.agents.models.bench.common import ROOT, SAMPLES, bakeoff
from hmap.agents.models.finetune.data import BENCHMARK
from hmap.agents.models.finetune.data import OUT as DATA_DIR
from hmap.agents.models.finetune.train import BASE, HF_HOME, MLX
from hmap.agents.verify.entail import EntailAnswer
from hmap.agents.verify.entail import messages as entail_messages

CHILD = Path(__file__).with_name("mlx_generate.py")
RESULTS = SAMPLES / "finetune"
HINT = "Respond with a single JSON object that matches this JSON Schema, and nothing else:\n"


def with_schema(messages: list[dict[str, str]], schema: Any) -> list[dict[str, str]]:
    """The gateway's schema hint (``json_mode="none"``), first. Qwen's chat template takes one system message, so the
    hint opens the existing one."""
    hint = HINT + json.dumps(schema.model_json_schema(), sort_keys=True)
    if messages and messages[0]["role"] == "system":
        return [{"role": "system", "content": f"{hint}\n\n{messages[0]['content']}"}, *messages[1:]]
    return [{"role": "system", "content": hint}, *messages]


GOLD = {"clean": "supports", "wrong_number": "not_enough", "unsupported_claim": "not_enough"}


def heldout_items() -> list[dict[str, Any]]:
    items = []
    for line in BENCHMARK.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        kind = row["kind"]
        gold = GOLD.get(kind)
        if kind == "natural":
            gold = "supports" if row["expected"]["verdict"] == "VERIFIED" else "not_enough"
        if gold is None:
            continue
        passages = [(e.get("url", ""), e["quote"]) for e in row["evidence"]]
        items.append({"id": row["id"], "gold": gold, "kind": kind,
                      "messages": with_schema(entail_messages(row["claim"], passages), EntailAnswer)})
    return items


def split_items(name: str = "test") -> list[dict[str, Any]]:
    out = []
    for i, line in enumerate((DATA_DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()):
        msgs = json.loads(line)["messages"]
        out.append({"id": f"{name}{i:03d}", "gold": json.loads(msgs[-1]["content"])["verdict"],
                    "messages": with_schema(msgs[:-1], EntailAnswer)})
    return out


def regression_items(mb: Any) -> list[dict[str, Any]]:
    out = []
    for item in mb.load_items("critique"):
        user = f"TASK:\n{item['context']}\n\nOUTPUT TO REVIEW:\n{item['artifact']}"
        out.append({"id": item["id"], "suite": "critique", "item": item,
                    "messages": with_schema([{"role": "system", "content": mb.CRITIC_SYS},
                                             {"role": "user", "content": user}], mb.Critique)})
    for item in mb.load_items("extraction")[:5]:
        out.append({"id": item["id"], "suite": "extraction", "item": item,
                    "messages": with_schema([{"role": "system", "content": mb.EXTRACT_SYS},
                                             {"role": "user", "content": item["doc"]}], mb.Extraction)})
    return out


def generate(items: list[dict[str, Any]], adapter: str | None, max_tokens: int, work: Path) -> dict[str, str]:
    prompts, answers = work / "prompts.jsonl", work / f"answers_{'lora' if adapter else 'base'}.jsonl"
    prompts.write_text("".join(json.dumps({"id": i["id"], "messages": i["messages"]}) + "\n" for i in items))
    subprocess.run([*MLX, str(CHILD), BASE, adapter or "-", str(prompts), str(answers), str(max_tokens)],
                   check=True, env={**os.environ, "HF_HOME": HF_HOME, "TOKENIZERS_PARALLELISM": "false"})
    return {r["id"]: r["text"] for r in map(json.loads, answers.read_text().splitlines())}


def verdict_of(text: str) -> str | None:
    m = re.search(r'"verdict"\s*:\s*"(supports|refutes|not_enough)"', text)
    return m.group(1) if m else None


def score_judge(items: list[dict[str, Any]], answers: dict[str, str]) -> dict[str, Any]:
    """``accuracy`` = supported vs not supported, the platform's measure: Member 6's aggregator turns both
    ``refutes`` and ``not_enough`` into UNSUPPORTED (rule R3), so which of the two a model picks does not change the
    verdict. ``strict`` = the 3-way label (a changed number answered ``refutes`` counts wrong there).
    ``wrongly_accepted`` = an unsupported claim judged supported: the costly error."""
    preds = [verdict_of(answers.get(i["id"], "")) for i in items]
    n = len(items)
    binary = sum((p == "supports") == (i["gold"] == "supports") for p, i in zip(preds, items, strict=True))
    strict = sum(p == i["gold"] for p, i in zip(preds, items, strict=True))
    return {"n": n, "accuracy": round(binary / n, 3) if n else None, "strict": round(strict / n, 3) if n else None,
            "wrongly_accepted": sum(p == "supports" and i["gold"] != "supports"
                                    for p, i in zip(preds, items, strict=True)),
            "invalid": sum(p is None for p in preds)}


def score_regression(mb: Any, items: list[dict[str, Any]], answers: dict[str, str]) -> dict[str, Any]:
    by: dict[str, list[float]] = {}
    for i in items:
        schema = mb.Critique if i["suite"] == "critique" else mb.Extraction
        text = answers.get(i["id"], "")
        m = re.search(r"\{.*\}", text, re.S)
        obj, _ = mb.parse(m.group(0), schema) if m else (None, "no json")
        if obj is None:
            sc = 0.0
        elif i["suite"] == "critique":
            sc = mb.score_critique(i["item"], obj)["score"]
        else:
            sc = mb.score_extraction(i["item"]["doc"], i["item"]["gold"], obj)["score"]
        by.setdefault(i["suite"], []).append(float(sc))
    return {k: round(sum(v) / len(v), 3) for k, v in by.items()}


def evaluate(adapter: str) -> dict[str, Any]:
    mb = bakeoff()
    held, test, reg = heldout_items(), split_items("test"), regression_items(mb)
    out: dict[str, Any] = {"adapter": adapter, "base": BASE, "heldout_n": len(held), "test_n": len(test)}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for arm, ad in (("base", None), ("lora", str(ROOT / adapter))):
            judge = generate(held + test, ad, 200, work)
            regr = generate(reg, ad, 1024, work)
            out[arm] = {"heldout_m6": score_judge(held, judge), "test_split": score_judge(test, judge),
                        "regression": score_regression(mb, reg, regr)}
    d = out["lora"]["heldout_m6"]["accuracy"] - out["base"]["heldout_m6"]["accuracy"]
    out["delta_heldout"] = round(d, 3)
    base_acc, lora_acc = out["base"]["heldout_m6"]["accuracy"], out["lora"]["heldout_m6"]["accuracy"]
    out["verdict"] = (("better" if d > 0.03 else "worse" if d < -0.03 else "no clear change")
                      + f" on the held-out M6 set ({base_acc} -> {lora_acc}, n={len(held)}; ±0.03 is within noise)")
    (RESULTS / "eval_result.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", required=True, help="adapter folder, relative to the repo root")
    print(json.dumps(evaluate(ap.parse_args().adapter), indent=1))
