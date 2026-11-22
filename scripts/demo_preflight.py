#!/usr/bin/env python3
"""Pre-flight check of `make demo` (Sprint 9 item 9.16): is this laptop ready to run the whole platform?

    python3 scripts/demo_preflight.py --mode live      # make demo
    python3 scripts/demo_preflight.py --mode replay    # make demo-replay (no model needed)
    python3 scripts/demo_preflight.py --json

Each check prints OK / WARN / FAIL; every problem comes with the exact command (or step) that fixes it. Exit code 1
when any check FAILs. Standard library only (runs before the backend's dependencies are installed). Never prints a
key: only how many team keys are set.
"""

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PORTS = {8000: "API", 3000: "dashboard"}
INFRA_PORTS = {5433: "Postgres", 5672: "RabbitMQ", 15672: "RabbitMQ management"}
MIN_FREE_GB = {"live": 4.0, "replay": 1.5}       # live with cloud keys: 2.5 (the local model is only the fallback)
MIN_FREE_GB_WITH_KEYS = 2.5
MIN_DISK_GB = 2.0
DEFAULT_MODEL = "qwen3.5:9b"
OLLAMA_START = "OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama OLLAMA_MAX_LOADED_MODELS=2 ollama serve"


@dataclass
class Check:
    name: str
    status: str            # OK | WARN | FAIL
    detail: str
    fix: str = ""


def env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.removeprefix("export ").strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.split(" #", 1)[0].strip().strip("'\"")
    return out


def setting(name: str, file: dict[str, str]) -> str:
    return os.environ.get(name) or file.get(name) or ""


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def free_ram_gb() -> float | None:
    """Memory available without swapping: free + inactive + speculative pages (macOS), MemAvailable (Linux)."""
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            size = int(re.search(r"page size of (\d+)", out).group(1))  # type: ignore[union-attr]
            pages = sum(int(m.group(1)) for k in ("Pages free", "Pages inactive", "Pages speculative")
                        if (m := re.search(rf"{k}:\s+(\d+)", out)))
            return pages * size / 1024**3
        text = Path("/proc/meminfo").read_text()
        kb = int(re.search(r"MemAvailable:\s+(\d+)", text).group(1))  # type: ignore[union-attr]
        return kb / 1024**2
    except Exception:
        return None


def http_json(url: str, timeout: float = 2.0) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as r:  # a local URL from the settings
        return json.loads(r.read())


def ours_running() -> bool:
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "hmap-postgres-1" in out.stdout


def check_tools(which: Callable[[str], str | None] = shutil.which) -> list[Check]:
    out = []
    for tool, fix in (("uv", "brew install uv"), ("npm", "brew install node@20")):
        out.append(Check(tool, "OK", which(tool) or "") if which(tool) else
                   Check(tool, "FAIL", f"{tool} is not installed", fix))
    if which("docker") is None:
        out.append(Check("docker", "FAIL", "the docker command is not installed", "brew install colima docker "
                                                                                  "docker-compose"))
    elif which("colima") is None:
        out.append(Check("docker", "WARN", "Colima is not installed: Docker must already be running",
                         "brew install colima (or start Docker Desktop)"))
    else:
        out.append(Check("docker", "OK", "docker + colima (make demo starts Colima when needed)"))
    return out


def check_ports(busy: Callable[[int], bool] = port_busy, infra_ours: Callable[[], bool] = ours_running) -> list[Check]:
    out = []
    for port, what in APP_PORTS.items():
        if busy(port):
            out.append(Check(f"port {port}", "FAIL", f"port {port} ({what}) is in use: another copy is running?",
                             f"make stop   # or see who has it: lsof -nP -iTCP:{port} -sTCP:LISTEN"))
        else:
            out.append(Check(f"port {port}", "OK", f"free ({what})"))
    taken = [p for p in INFRA_PORTS if busy(p)]
    if taken and not infra_ours():
        out.append(Check("infra ports", "FAIL", f"port(s) {', '.join(map(str, taken))} are used by something else "
                         "than this project's Postgres / RabbitMQ",
                         f"lsof -nP -iTCP:{taken[0]} -sTCP:LISTEN   # stop that program"))
    else:
        out.append(Check("infra ports", "OK", "already running (this project)" if taken else "free"))
    return out


def key_count(file: dict[str, str]) -> int:
    return sum(len([k for k in setting(v, file).split(",") if k.strip()]) for v in ("HMAP_GROQ_API_KEYS",
                                                                                     "HMAP_GEMINI_API_KEYS"))


def check_ram(mode: str, free: float | None, minimum: float | None = None, *, keys: int = 0) -> Check:
    default = MIN_FREE_GB_WITH_KEYS if mode == "live" and keys else MIN_FREE_GB[mode]
    need = minimum if minimum is not None else default
    if free is None:
        return Check("free memory", "WARN", "could not read the free memory")
    if free < need:
        fix = ("close heavy apps (browsers, IDEs), or run the offline demo: make demo-replay" if mode == "live"
               else "close heavy apps (browsers, IDEs, Ollama: pkill -f 'ollama serve')")
        return Check("free memory", "FAIL", f"{free:.1f} GB free, the {mode} demo needs {need:.1f} GB", fix)
    return Check("free memory", "OK", f"{free:.1f} GB free (needs {need:.1f} GB)")


def check_disk(path: Path = ROOT) -> Check:
    free = shutil.disk_usage(path).free / 1024**3
    if free < MIN_DISK_GB:
        return Check("disk", "FAIL", f"{free:.1f} GB free on {path}", "free some disk space (docker system prune, "
                                                                      "old handoff folders)")
    return Check("disk", "OK", f"{free:.0f} GB free")


def check_model(mode: str, file: dict[str, str], fetch: Callable[[str], object] = http_json) -> list[Check]:
    if mode != "live":
        return [Check("model", "OK", "replay: recorded answers, no model needed")]
    keys = key_count(file)
    url = (setting("OLLAMA_BASE_URL", file) or "http://127.0.0.1:11434").rstrip("/")
    roles = setting("HMAP_ROLE_MAP", file)
    model = next((m for m in re.findall(r"=\s*([\w.:-]+)", roles) if "embed" not in m), DEFAULT_MODEL)
    out = [Check("cloud keys", "OK", f"{keys} team key(s) set in .env") if keys else
           Check("cloud keys", "WARN", "no cloud keys: every role runs on the local model (slower)",
                 "paste the team keys into .env (HMAP_GROQ_API_KEYS / HMAP_GEMINI_API_KEYS)")]
    try:
        tags = fetch(f"{url}/api/tags")
    except Exception:
        st = "WARN" if keys else "FAIL"
        out.append(Check("ollama", st, f"Ollama is not answering at {url}" + (" (cloud keys cover the chat roles; "
                         "documents still need the local embedder)" if keys else ""), OLLAMA_START))
        return out
    names = {m.get("name", "") for m in (tags.get("models", []) if isinstance(tags, dict) else [])}
    out.append(Check("ollama", "OK", f"answering at {url} ({len(names)} models)"))
    for want in (model, "nomic-embed-text"):
        if not any(n == want or n.startswith(want + ":") or n.split(":")[0] == want for n in names):
            out.append(Check(f"model {want}", "FAIL" if not keys or want == "nomic-embed-text" else "WARN",
                             f"{want} is not pulled", f"ollama pull {want}"))
        else:
            out.append(Check(f"model {want}", "OK", "pulled"))
    return out


def check_extras(file: dict[str, str]) -> list[Check]:
    out = [Check(".env", "OK", "present") if (ROOT / ".env").is_file() else
           Check(".env", "WARN", "no .env: defaults are used", "cp .env.example .env")]
    try:
        if subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode != 0:
            raise OSError("docker is not running")
        r = subprocess.run(["docker", "image", "inspect", "hmap-sandbox-py:1"], capture_output=True, timeout=10)
        out.append(Check("sandbox image", "OK", "hmap-sandbox-py:1") if r.returncode == 0 else
                   Check("sandbox image", "WARN", "the testing sandbox image is missing: tests run in the weaker "
                         "local runner", "make sandbox-image   # once, needs the internet"))
    except (OSError, subprocess.TimeoutExpired):
        out.append(Check("sandbox image", "WARN", "Docker is not running yet (make demo starts it)"))
    return out


def run(mode: str) -> list[Check]:
    file = env_file()
    minimum = setting("HMAP_DEMO_MIN_FREE_GB", file)
    return [*check_tools(), *check_ports(),
            check_ram(mode, free_ram_gb(), float(minimum) if minimum else None, keys=key_count(file)),
            check_disk(), *check_model(mode, file), *check_extras(file)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", choices=("live", "replay"), default="live")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    checks = run(args.mode)
    if args.json:
        print(json.dumps([asdict(c) for c in checks], indent=1))
    else:
        colour = {"OK": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m"}
        print(f"pre-flight ({args.mode})")
        for c in checks:
            print(f"  {colour[c.status]}{c.status:4s}\033[0m  {c.name}: {c.detail}")
            if c.fix and c.status != "OK":
                print(f"        fix: {c.fix}")
    return 1 if any(c.status == "FAIL" for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
