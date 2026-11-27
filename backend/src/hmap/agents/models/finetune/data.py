"""Dataset builder (item 11.9) for the chosen skill: **Member 6's claim-vs-passages judge** (plan D10, Q5).

Source: every recorded ``judge`` call that uses Member 6's entailment prompt (``hmap.agents.verify.entail``) in
``samples/llm_cache/`` (verify and review plug-ins). The answers are the cloud judge's (Groq / Gemini), so this is
distillation: a small local model learns to answer like the cloud judge.

Filters, in order (each drop is counted in ``stats.json``):
1. **validator**: the answer parses as Member 6's ``EntailAnswer`` (the schema the agent enforces);
2. **contamination** (trap T15): any claim of the evaluation sets — the M6 benchmark (``samples/verify/
   benchmark.jsonl``, the held-out test here) and the bake-off verify items (the regression set) — is dropped,
   compared after normalising case and punctuation;
3. **dedupe**: the same (claim, passages) prompt once (the given-order and swapped-order prompts are different
   prompts and both kept, but always in the same split);
4. **split by claim**, not by example (80 / 10 / 10, seeded): the swapped twin or a re-ask of one claim never sits
   in train and test at once.

Output (MLX-LM chat format): ``samples/models/finetune/data/{train,valid,test}.jsonl`` + ``stats.json``.

    uv run python -m hmap.agents.models.finetune.data
"""

import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from hmap.agents.models.bench.common import ROOT, SAMPLES

CACHE = ROOT / "samples" / "llm_cache"
OUT = SAMPLES / "finetune" / "data"
BENCHMARK = ROOT / "samples" / "verify" / "benchmark.jsonl"
BAKEOFF_VERIFY = ROOT / "samples" / "model_bakeoff" / "verify" / "items.json"
SYSTEM_PREFIX = "You are a strict fact checker. Decide whether the quoted source passages support a claim."
VERDICTS = ("supports", "refutes", "not_enough")
MIN_TRAIN = 100          # below this the experiment switches to the fallback skill (plan D10)


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def claim_of(user: str) -> str | None:
    m = re.search(r"Claim: (.*?)\n", user + "\n")
    return m.group(1).strip() if m else None


def eval_claims() -> set[str]:
    claims = {norm(json.loads(line)["claim"]) for line in BENCHMARK.read_text(encoding="utf-8").splitlines()
              if line.strip()}
    if BAKEOFF_VERIFY.exists():
        claims |= {norm(i["claim"]) for i in json.loads(BAKEOFF_VERIFY.read_text(encoding="utf-8"))["items"]}
    return claims


def harvest(cache: Path = CACHE) -> tuple[list[dict[str, Any]], Counter[str]]:
    held_out = eval_claims()
    drops: Counter[str] = Counter()
    seen: set[str] = set()
    out = []
    for path in sorted(cache.rglob("*.json")):
        if "models" in path.relative_to(cache).parts[:1]:
            continue                                    # the benchmark's own recordings
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        msgs = (rec.get("request") or {}).get("messages") or []
        if rec.get("role") != "judge" or len(msgs) < 2 or not str(msgs[0].get("content", "")).startswith(
                SYSTEM_PREFIX):
            continue
        user = str(msgs[-1]["content"])
        claim = claim_of(user)
        if claim is None:
            drops["no claim line"] += 1
            continue
        try:
            answer = json.loads(rec["response"]["text"])
            verdict = answer["verdict"]
            assert verdict in VERDICTS
        except (KeyError, ValueError, AssertionError, TypeError):
            drops["validator: not a valid EntailAnswer"] += 1
            continue
        if norm(claim) in held_out:
            drops["contamination: an evaluation claim"] += 1
            continue
        key = hashlib.sha256(user.encode()).hexdigest()
        if key in seen:
            drops["duplicate prompt"] += 1
            continue
        seen.add(key)
        target = json.dumps({"rationale": str(answer.get("rationale", ""))[:300], "verdict": verdict},
                            ensure_ascii=False)
        out.append({"claim": norm(claim), "verdict": verdict, "source": path.relative_to(cache).parts[0],
                    "messages": [{"role": "system", "content": msgs[0]["content"]}, {"role": "user", "content": user},
                                 {"role": "assistant", "content": target}]})
    return out, drops


def split(examples: list[dict[str, Any]], seed: int = 42) -> dict[str, list[dict[str, Any]]]:
    claims = sorted({e["claim"] for e in examples})
    random.Random(seed).shuffle(claims)
    n = len(claims)
    cut1, cut2 = int(n * 0.8), int(n * 0.9)
    part = {c: ("train" if i < cut1 else "valid" if i < cut2 else "test") for i, c in enumerate(claims)}
    out: dict[str, list[dict[str, Any]]] = {"train": [], "valid": [], "test": []}
    for e in examples:
        out[part[e["claim"]]].append(e)
    return out


def build(out_dir: Path = OUT, cache: Path = CACHE) -> dict[str, Any]:
    examples, drops = harvest(cache)
    parts = split(examples)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in parts.items():
        (out_dir / f"{name}.jsonl").write_text("".join(json.dumps({"messages": r["messages"]}, ensure_ascii=False)
                                                       + "\n" for r in rows), encoding="utf-8")
    stats = {"skill": "verify judge (claim vs passages)", "examples": len(examples),
             "claims": len({e["claim"] for e in examples}), "drops": dict(drops),
             "splits": {k: {"examples": len(v), "claims": len({e["claim"] for e in v}),
                            "verdicts": dict(Counter(e["verdict"] for e in v))} for k, v in parts.items()},
             "sources": dict(Counter(e["source"] for e in examples)),
             "enough": len(parts["train"]) >= MIN_TRAIN}
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    return stats


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
