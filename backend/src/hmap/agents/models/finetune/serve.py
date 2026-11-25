"""Serving the adapter (item 11.12) — verify the architecture first.

1. **Ollama** ``ADAPTER``: ``ollama create <name> -f Modelfile`` with ``FROM qwen3.5:4b`` + ``ADAPTER <dir>``. Ollama
   converts safetensors LoRA adapters only for some architectures; :func:`try_ollama` runs it and records the
   answer (a refusal is a result, not a crash).
2. **Fallback**: ``mlx_lm.server --model <base> --adapter-path <dir>`` (OpenAI-compatible) behind the ``mlx``
   backend (``HMAP_MLX_BASE_URL``); the registry lists it as ``mlx:<model id>``, and
   ``HMAP_ROUTE_OVERRIDES=verify:judge=mlx:<id>`` routes Member 6's judge to it.

    uv run python -m hmap.agents.models.finetune.serve --adapter samples/models/finetune/adapters/<run> --ollama
"""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from hmap.agents.models.bench.common import ROOT, SAMPLES
from hmap.agents.models.finetune.train import BASE, HF_HOME, MLX


def try_ollama(adapter: Path, *, base: str = "qwen3.5:4b", name: str = "qwen3.5-4b-verify-lora") -> dict[str, Any]:
    if shutil.which("ollama") is None:
        return {"ok": False, "why": "ollama is not installed"}
    with tempfile.TemporaryDirectory() as tmp:
        mf = Path(tmp) / "Modelfile"
        mf.write_text(f"FROM {base}\nADAPTER {adapter.resolve()}\n")
        p = subprocess.run(["ollama", "create", name, "-f", str(mf)], capture_output=True, text=True, timeout=900,
                           check=False)
    out = (p.stdout + p.stderr).strip()
    return {"ok": p.returncode == 0, "model": name if p.returncode == 0 else None, "output": out[-800:]}


def mlx_server_command(adapter: Path, port: int = 8080) -> list[str]:
    return [*MLX, "-m", "mlx_lm", "server", "--model", BASE, "--adapter-path", str(adapter.resolve()),
            "--host", "127.0.0.1", "--port", str(port)]


def record(result: dict[str, Any]) -> Path:
    path = SAMPLES / "finetune" / "serve_result.json"
    path.write_text(json.dumps(result, indent=1) + "\n")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--ollama", action="store_true", help="try Ollama ADAPTER (creates a local model)")
    a = ap.parse_args()
    adapter = ROOT / a.adapter
    res: dict[str, Any] = {"adapter": a.adapter, "mlx_server": " ".join(mlx_server_command(adapter)),
                           "mlx_env": f"HF_HOME={HF_HOME}"}
    if a.ollama:
        res["ollama"] = try_ollama(adapter)
    print(json.dumps(res, indent=1), "\n", record(res))
