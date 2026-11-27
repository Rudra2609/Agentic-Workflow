"""LoRA training (item 11.10): MLX-LM on Apple Silicon, on a 4-bit base (QLoRA-style), so a 4B model trains in
16 GB. MLX is not a backend dependency (Apple only, heavy): it runs as ``uv run --with mlx-lm`` in a child process.

Before training every Ollama model is unloaded (the trial in model-choice.md hit a Metal out-of-memory error with
memory in use). The run's config, the loss curve and the outcome go to ``samples/models/finetune/runs/<run>.json``.

    uv run python -m hmap.agents.models.finetune.train --iters 200 --num-layers 4
"""

import argparse
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from hmap.agents.models.bench.common import SAMPLES
from hmap.agents.models.finetune.data import OUT as DATA_DIR

BASE = "mlx-community/Qwen3.5-4B-MLX-4bit"       # same family / size as the lite Ollama model qwen3.5:4b
HF_HOME = "/Volumes/Tirth_SSD/hf_cache"         # the ~3 GB weights stay off the internal disk
MLX = ("uv", "run", "--no-project", "--with", "mlx-lm>=0.28", "python")
RUNS = SAMPLES / "finetune" / "runs"
ADAPTERS = SAMPLES / "finetune" / "adapters"
LOSS_RE = re.compile(r"Iter (\d+): (Train|Val) loss ([\d.]+)")             # mlx-lm < 0.30
TABLE_VAL = re.compile(r"^\s*(\d+)\s+val\s+([\d.]+)", re.M)               # mlx-lm 0.30+ table
TABLE_TRAIN = re.compile(r"^\s*(\d+)\s+([\d.]+)\s+[▲▼=-]?\s+\d+", re.M)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def unload_ollama(base_url: str = "http://127.0.0.1:11434") -> list[str]:
    try:
        ps = httpx.get(f"{base_url}/api/ps", timeout=3).json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return []
    for m in ps:
        httpx.post(f"{base_url}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=30)
    return [m["name"] for m in ps]


def parse_losses(output: str) -> dict[str, list[tuple[int, float]]]:
    out: dict[str, list[tuple[int, float]]] = {"train": [], "val": []}
    for it, kind, loss in LOSS_RE.findall(output):
        out["train" if kind == "Train" else "val"].append((int(it), float(loss)))
    plain = ANSI.sub("", output)
    out["val"] += [(int(i), float(v)) for i, v in TABLE_VAL.findall(plain)]
    out["train"] += [(int(i), float(v)) for i, v in TABLE_TRAIN.findall(plain)]
    return out


def train(*, iters: int = 200, num_layers: int = 4, max_seq: int = 1536, lr: float = 1e-5, batch: int = 1,
          rank: int = 8, base: str = BASE, data: Path = DATA_DIR, timeout_s: float = 7200.0) -> dict[str, Any]:
    run_id = f"ft-{time.strftime('%Y%m%d-%H%M')}-{uuid.uuid4().hex[:4]}"
    adapter = ADAPTERS / run_id
    adapter.mkdir(parents=True, exist_ok=True)
    (adapter / "lora.yaml").write_text(f"lora_parameters:\n  rank: {rank}\n  scale: 20.0\n  dropout: 0.0\n")
    config = {"base": base, "iters": iters, "num_layers": num_layers, "max_seq_length": max_seq,
              "learning_rate": lr, "batch_size": batch, "rank": rank, "seed": 42, "data": str(data.relative_to(
                  SAMPLES.parents[1]))}
    cmd = [*MLX, "-m", "mlx_lm", "lora", "--model", base, "--train", "--data", str(data), "--adapter-path",
           str(adapter), "--iters", str(iters), "--num-layers", str(num_layers), "--batch-size", str(batch),
           "--max-seq-length", str(max_seq), "--learning-rate", str(lr), "--val-batches", "2",
           "--steps-per-eval", str(max(10, iters // 10)), "--steps-per-report", "10", "--seed", "42",
           "--grad-checkpoint", "-c", str(adapter / "lora.yaml")]
    unloaded = unload_ollama()
    started = time.monotonic()
    env = {**os.environ, "HF_HOME": HF_HOME, "TOKENIZERS_PARALLELISM": "false"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=env, check=False)
        output, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as exc:
        output, rc = str(exc.stdout or "") + str(exc.stderr or ""), -1
    seconds = round(time.monotonic() - started, 1)
    losses = parse_losses(output)
    oom = "out of memory" in output.lower() or ("metal" in output.lower() and "memory" in output.lower())
    status = "trained" if rc == 0 and (adapter / "adapters.safetensors").exists() else (
        "failed: out of memory" if oom else f"failed (exit {rc})")
    peak = re.findall(r"Peak mem ([\d.]+) GB", output)
    run = {"id": run_id, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "skill": "verify judge", "base": base,
           "status": status, "config": config, "seconds": seconds, "unloaded": unloaded,
           "adapter": str(adapter.relative_to(SAMPLES.parents[1])) if status == "trained" else None,
           "result": {"losses": losses, "peak_mem_gb": float(peak[-1]) if peak else None,
                      "log_tail": output[-2500:]}}
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{run_id}.json").write_text(json.dumps(run, indent=1) + "\n")
    return run


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--num-layers", type=int, default=4)
    ap.add_argument("--max-seq", type=int, default=1536)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--rank", type=int, default=8)
    a = ap.parse_args()
    r = train(iters=a.iters, num_layers=a.num_layers, max_seq=a.max_seq, lr=a.lr, rank=a.rank)
    print(json.dumps({k: v for k, v in r.items() if k != "result"} | {"losses": r["result"]["losses"],
                                                                        "peak_mem_gb": r["result"]["peak_mem_gb"]},
                     indent=1))
