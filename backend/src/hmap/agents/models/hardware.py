"""Hardware profiler and memory feasibility (item 11.2), from the prototype (``samples/models/memory.py``).

    memory = weights (the GGUF file) + KV cache x context (+ a fixed runtime overhead, measured)

KV cache per token = 2 (K and V) x layers with attention x KV heads x head size x bytes per value (f16 = 2).
**Hybrid models** such as Qwen 3.5 (``full_attention_interval`` = 4) keep a KV cache in only every 4th layer; the
other layers carry a small fixed recurrent state, so the usual formula (every layer) overestimates them ~4x.

Live state: total / free RAM and swap (macOS ``sysctl`` + ``vm_stat``; Linux ``/proc/meminfo``), the GPU (Apple
Metal = unified memory; CUDA through ``nvidia-smi`` when present), the Docker VM size, and what Ollama has loaded
(``/api/ps``). ``feasible`` answers fits / fits-alone / does-not-fit with the numbers that decided it.

    uv run python -m hmap.agents.models.hardware              # this machine, as JSON
    uv run python -m hmap.agents.models.hardware --watch 1    # peak RAM sampler (item 11.17)
"""

import json
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

GB = 1e9
SNAPSHOT = Path(__file__).resolve().parents[5] / "samples" / "models" / "data" / "model_specs.json"
# Budget assumptions (Sprint 11 item 11.17 measures them on Member 1's laptop; sizing.md has the measured values)
OS_AND_APPS_GB = 4.5     # macOS + browser + terminal, other heavy apps closed
DEMO_STACK_GB = 3.0      # Docker infra (Postgres, broker) + API + agent host + Next.js
HEADROOM_GB = 1.0        # stay out of swap
# Fixed runtime overhead per loaded model (compute buffers, recurrent state), fitted on /api/ps at several context
# lengths (eval.md §1); 0 until measured, so the prototype's "no fitted constants" result stays reproducible.
RUNTIME_OVERHEAD_GB: dict[str, float] = {}

Fit = Literal["fits", "fits_alone", "does_not_fit", "unknown"]


def snapshot_specs() -> dict[str, dict[str, Any]]:
    """The GGUF headers saved by the prototype (``samples/models/data/model_specs.json``)."""
    try:
        data: dict[str, dict[str, Any]] = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        return data
    except (OSError, ValueError):
        return {}


def kv_bytes_per_token(spec: dict[str, Any], *, naive: bool = False, bytes_per_value: int = 2) -> int:
    layers = int(spec["block_count"])
    if spec.get("full_attention_interval") and not naive:
        layers //= int(spec["full_attention_interval"])
    head_dim = int(spec.get("attention.key_length")
                   or int(spec["embedding_length"]) // int(spec["attention.head_count"]))
    kv_heads = int(spec.get("attention.head_count_kv") or spec["attention.head_count"])
    return 2 * layers * kv_heads * head_dim * bytes_per_value


def predict_gb(spec: dict[str, Any], ctx: int = 8192, *, naive: bool = False, model: str | None = None) -> float:
    """Weights + KV cache at ``ctx`` tokens (+ the measured overhead for ``model`` when known)."""
    overhead = RUNTIME_OVERHEAD_GB.get(model or "", 0.0)
    return (int(spec["file_bytes"]) + kv_bytes_per_token(spec, naive=naive) * ctx) / GB + overhead


def model_budget_gb(ram_gb: float, *, stack_gb: float = DEMO_STACK_GB) -> float:
    return ram_gb - OS_AND_APPS_GB - stack_gb - HEADROOM_GB


@dataclass
class Hardware:
    platform: str = ""
    chip: str = ""
    total_gb: float = 0.0
    free_gb: float = 0.0                 # free + inactive (reclaimable) pages
    swap_used_gb: float = 0.0
    gpu: str = "none"                    # metal (unified memory) / cuda / none
    gpu_mem_gb: float | None = None      # CUDA only; Metal shares total_gb
    docker_vm_gb: float | None = None
    resident: dict[str, float] = field(default_factory=dict)   # model -> GB loaded (Ollama /api/ps)
    ollama: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(cmd: list[str], timeout: float = 3.0) -> str:
    if shutil.which(cmd[0]) is None:
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _mac_memory(hw: Hardware) -> None:
    hw.total_gb = int(_run(["sysctl", "-n", "hw.memsize"]) or 0) / GB
    hw.chip = (_run(["sysctl", "-n", "machdep.cpu.brand_string"]) or _run(["sysctl", "-n", "hw.model"])).strip()
    vm = _run(["vm_stat"])
    page = int(m.group(1)) if (m := re.search(r"page size of (\d+) bytes", vm)) else 16384

    def pages(label: str) -> int:
        m = re.search(rf"{label}:\s+(\d+)", vm)
        return int(m.group(1)) if m else 0

    hw.free_gb = (pages("Pages free") + pages("Pages inactive") + pages("Pages speculative")) * page / GB
    if m := re.search(r"used = ([\d.]+)M", _run(["sysctl", "-n", "vm.swapusage"])):
        hw.swap_used_gb = float(m.group(1)) / 1000
    if platform.machine() == "arm64":
        hw.gpu = "metal"


def _linux_memory(hw: Hardware) -> None:
    try:
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line)
    except OSError:
        return

    def kb(key: str) -> float:
        return float(info.get(key, "0 kB").split()[0]) * 1024 / GB

    hw.total_gb, hw.free_gb = kb("MemTotal"), kb("MemAvailable")
    hw.swap_used_gb = kb("SwapTotal") - kb("SwapFree")


def _cuda(hw: Hardware) -> None:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if out.strip():
        name, _, mem = out.splitlines()[0].partition(",")
        hw.gpu, hw.chip = "cuda", hw.chip or name.strip()
        hw.gpu_mem_gb = float(mem.strip() or 0) / 1000


def _docker(hw: Hardware) -> None:
    out = _run(["docker", "info", "--format", "{{.MemTotal}}"], timeout=4.0).strip()
    if out.isdigit() and int(out) > 0:          # 0 / no answer: Docker (Colima) is not running
        hw.docker_vm_gb = int(out) / GB


def ollama_ps(base_url: str, *, client: httpx.Client | None = None) -> dict[str, float] | None:
    """Loaded models -> GB (``/api/ps``); ``None`` when Ollama does not answer."""
    try:
        c = client or httpx.Client(timeout=2.0)
        resp = c.get(f"{base_url.rstrip('/')}/api/ps")
        resp.raise_for_status()
        return {str(m["name"]): float(m.get("size", 0)) / GB for m in resp.json().get("models", [])}
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def profile(ollama_base_url: str = "http://127.0.0.1:11434", *, docker: bool = True,
            client: httpx.Client | None = None) -> Hardware:
    hw = Hardware(platform=f"{platform.system()} {platform.machine()}")
    if sys.platform == "darwin":
        _mac_memory(hw)
    else:
        _linux_memory(hw)
    _cuda(hw)
    if docker:
        _docker(hw)
    resident = ollama_ps(ollama_base_url, client=client)
    hw.ollama = resident is not None
    hw.resident = resident or {}
    if hw.swap_used_gb > 1.0:
        hw.notes.append(f"{hw.swap_used_gb:.1f} GB of swap in use: speed numbers taken now are not representative")
    return hw


@dataclass
class Feasibility:
    model: str
    fit: Fit
    need_gb: float | None
    available_gb: float
    why: str


def feasible(model: str, spec: dict[str, Any] | None, hw: Hardware, *, ctx: int = 8192,
             stack_gb: float = DEMO_STACK_GB) -> Feasibility:
    """Does ``model`` fit next to what is loaded (``fits``), only after unloading the others (``fits_alone``), or
    not at all? A model already resident always fits."""
    budget = model_budget_gb(hw.total_gb, stack_gb=stack_gb) if hw.total_gb else 0.0
    if model in hw.resident:
        return Feasibility(model, "fits", hw.resident[model], budget, "already loaded")
    if spec is None or "block_count" not in spec:
        return Feasibility(model, "unknown", None, budget, "no GGUF header for this model")
    need = predict_gb(spec, ctx, model=model)
    loaded = sum(gb for name, gb in hw.resident.items() if "embed" not in name)
    if need <= budget - loaded:
        return Feasibility(model, "fits", need, budget - loaded, f"{need:.1f} GB needed, {budget - loaded:.1f} free "
                                                                  "in the model budget")
    if need <= budget:
        return Feasibility(model, "fits_alone", need, budget, f"{need:.1f} GB: fits only after unloading "
                                                               f"{', '.join(hw.resident) or 'nothing'}")
    return Feasibility(model, "does_not_fit", need, budget, f"{need:.1f} GB needed, the model budget on "
                                                             f"{hw.total_gb:.0f} GB is {budget:.1f} GB")


def sizing_table(specs: dict[str, dict[str, Any]], ram_sizes: tuple[int, ...] = (8, 16, 24, 48),
                 ctx: int = 8192) -> list[dict[str, Any]]:
    """Which models fit on each laptop size next to the demo stack (computed; sizing.md marks it as such)."""
    rows = []
    for ram in ram_sizes:
        budget = model_budget_gb(ram)
        fits = [m for m, s in specs.items() if "block_count" in s and predict_gb(s, ctx, model=m) <= budget]
        rows.append({"ram_gb": ram, "model_budget_gb": round(budget, 1), "fits": sorted(fits)})
    return rows


def watch(interval_s: float, ollama_base_url: str) -> None:  # pragma: no cover - interactive sampler
    """Print used RAM every ``interval_s`` and the peak on Ctrl-C (item 11.17)."""
    peak = 0.0
    try:
        while True:
            hw = profile(ollama_base_url, docker=False)
            used = hw.total_gb - hw.free_gb
            peak = max(peak, used)
            print(f"{time.strftime('%H:%M:%S')} used {used:5.1f} GB  swap {hw.swap_used_gb:4.1f} GB  "
                  f"models {', '.join(hw.resident) or '-'}  peak {peak:5.1f} GB", flush=True)
            time.sleep(interval_s)
    except KeyboardInterrupt:
        print(json.dumps({"peak_used_gb": round(peak, 2)}))


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--watch", type=float, default=0.0, help="sample every N seconds until Ctrl-C")
    a = ap.parse_args()
    if a.watch:
        watch(a.watch, a.ollama)
    else:
        print(json.dumps(profile(a.ollama).to_dict(), indent=1))
