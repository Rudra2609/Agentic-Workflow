# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-lm>=0.28", "httpx>=0.27", "pydantic>=2.7", "pytest>=8"]
# ///
"""Fine-tune TRIAL (process rehearsal for Sprint 11): LoRA on a small model with test-verified data.

Pipeline:
  1. uv run scripts/model_bakeoff.py gen-data --model qwen3.5:4b --samples 8
       -> samples/model_bakeoff/finetune/accepted_<model>.jsonl  (local-model solutions that pass hidden tests)
  2. uv run scripts/finetune_trial.py prepare
  3. uv run scripts/finetune_trial.py train
  4. uv run scripts/finetune_trial.py eval        # base vs base+LoRA on held-out AND train tasks

Training targets are only the local model's own solutions that passed the tests (rejection-sampling fine-tuning).
Held-out tasks (coding/split.json) are never trained on. Expect little or no gain from ~15 tasks: this proves the
process, it is not meant to improve the model.
"""
import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_bakeoff as mb  # noqa: E402

FT = mb.DATA / "finetune"
DATA_DIR = FT / "data"
ADAPTER = FT / "adapter"
BASE = "mlx-community/Qwen3.5-4B-MLX-4bit"   # same family/size as the Ollama 'lite' model qwen3.5:4b
os.environ.setdefault("HF_HOME", "/Volumes/Tirth_SSD/hf_cache")  # keep the ~3 GB weights off the internal disk


def unload_ollama() -> None:
    """Free RAM before MLX work: ask Ollama to unload every resident model."""
    try:
        for m in httpx.get(f"{mb.OLLAMA}/api/ps", timeout=10).json().get("models", []):
            httpx.post(f"{mb.OLLAMA}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)
    except httpx.HTTPError:
        pass


def cmd_prepare(args) -> None:
    src = FT / f"accepted_{mb.safe(args.source_model)}.jsonl"
    rows = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
    heldout = set(json.loads((mb.DATA / "coding" / "split.json").read_text())["heldout"])
    assert not any(r["task"] in heldout for r in rows), "held-out task leaked into training data"
    random.Random(0).shuffle(rows)
    n_val = max(1, len(rows) // 10)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, part in (("valid", rows[:n_val]), ("train", rows[n_val:])):
        with (DATA_DIR / f"{name}.jsonl").open("w") as f:
            for r in part:
                f.write(json.dumps({"messages": r["messages"]}) + "\n")
    print(f"train={len(rows) - n_val} valid={n_val} examples from {len({r['task'] for r in rows})} tasks")


def cmd_train(args) -> None:
    unload_ollama()
    n_train = sum(1 for _ in (DATA_DIR / "train.jsonl").open())
    iters = args.iters or max(50, min(400, n_train * 3))   # ~3 epochs, bounded
    cmd = [sys.executable, "-m", "mlx_lm", "lora", "--model", BASE, "--train", "--data", str(DATA_DIR),
           "--adapter-path", str(ADAPTER), "--iters", str(iters), "--batch-size", "1",
           "--num-layers", str(args.num_layers), "--learning-rate", str(args.lr), "--mask-prompt",
           "--max-seq-length", str(args.max_seq), "--steps-per-eval", "25", "--val-batches", str(args.val_batches),
           "--grad-checkpoint"]
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def cmd_eval(args) -> None:
    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    unload_ollama()
    split = json.loads((mb.DATA / "coding" / "split.json").read_text())
    sampler = make_sampler(temp=0.0)
    results = {}
    for label, adapter in (("base", None), ("lora", str(ADAPTER))):
        model, tok = load(BASE, adapter_path=adapter)
        for part in ("heldout", "train"):
            for tid in split[part]:
                tdir = mb.DATA / "coding" / tid
                msgs = [{"role": "system", "content": mb.CODE_SYS},
                        {"role": "user", "content": mb.code_user((tdir / "task.md").read_text())}]
                try:
                    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False,
                                                     enable_thinking=False)
                except TypeError:
                    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
                text = generate(model, tok, prompt=prompt, max_tokens=1536, sampler=sampler)
                r = mb.run_tests(tdir, mb.extract_code(text), FT / "eval_work" / label / tid)
                results.setdefault(label, {}).setdefault(part, {})[tid] = r
                print(f"  {label:4s} {part:7s} {tid:24s} pass={r['passed_all']} ({r['tests_passed']}/{r['tests_total']})",
                      flush=True)
        del model
    summary = {}
    for label, parts in results.items():
        for part, rs in parts.items():
            summary[f"{label}_{part}_pass@1"] = round(sum(r["passed_all"] for r in rs.values()) / len(rs), 3)
            summary[f"{label}_{part}_test_fraction"] = round(sum(r["test_fraction"] for r in rs.values()) / len(rs), 3)
    (FT / "eval_results.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(json.dumps(summary, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source-model", default="qwen3.5:4b")
    t = sub.add_parser("train")
    t.add_argument("--iters", type=int, default=0)
    t.add_argument("--num-layers", type=int, default=8)
    t.add_argument("--lr", type=float, default=1e-5)
    t.add_argument("--max-seq", type=int, default=2048, help="tokens per example; lower it if Metal runs out of memory")
    t.add_argument("--val-batches", type=int, default=-1)
    sub.add_parser("eval")
    args = ap.parse_args()
    {"prepare": cmd_prepare, "train": cmd_train, "eval": cmd_eval}[args.cmd](args)


if __name__ == "__main__":
    main()
