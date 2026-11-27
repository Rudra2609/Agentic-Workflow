#!/usr/bin/env python3
"""Final release gate, regression matrix (Sprint 11 item 11.19, Member 11).

    all sprint tests x HMAP_LLM_MODE {fake, replay, live-smoke} x HMAP_ROUTER {off, on} x tier {0, 1}

| Cell | What runs |
|---|---|
| fake x {off,on} (tier 0) | ``scripts/precommit.sh``: every sprint's tests, lint, types, frontend |
| replay x {off,on} (tier 0) | ``scripts/demo_final.sh``: the three golden scenarios, replayed |
| live-smoke x {off,on} (cloud) | ``hmap.agents.models.smoke`` through the platform-built gateway (team keys); with
|  | ``--live-e2e`` also ``demo_final --live --only=tcp`` |
| tier 1 x {off,on} | the same smoke on the local model only (``HMAP_CLOUD_OK=false``, Ollama with qwen3.5:9b) |

Each cell's status, seconds and the tail of its output go to ``samples/models/release/matrix.json``; the table is
written into ``docs/members/11/release.md`` between the matrix markers.

    python3 scripts/release_matrix.py                   # every cell that can run here (skips what is not up)
    python3 scripts/release_matrix.py --only fake replay
    python3 scripts/release_matrix.py --live-e2e        # also one golden scenario live per router setting
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "models" / "release" / "matrix.json"
DOC = ROOT / "docs" / "members" / "11" / "release.md"
START, END = "<!-- matrix:start -->", "<!-- matrix:end -->"


def ollama_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2):
            return True
    except OSError:
        return False


def keys_present() -> bool:
    env = (ROOT / ".env").read_text() if (ROOT / ".env").exists() else ""
    return any(line.startswith(("HMAP_GROQ_API_KEYS=", "HMAP_GEMINI_API_KEYS=")) and line.split("=", 1)[1].strip()
               for line in env.splitlines())


def cell(name: str, cmd: list[str], env: dict[str, str], timeout: float) -> dict[str, object]:
    print(f"\n=== {name}: {' '.join(cmd)}", flush=True)
    started = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **env}, capture_output=True, text=True, timeout=timeout,
                           check=False)
        status = "green" if p.returncode == 0 else f"red (exit {p.returncode})"
        tail = (p.stdout + p.stderr).strip().splitlines()[-12:]
    except subprocess.TimeoutExpired:
        status, tail = f"red (timeout {timeout:.0f} s)", []
    res = {"cell": name, "status": status, "seconds": round(time.monotonic() - started, 1), "env": env,
           "command": " ".join(cmd), "tail": tail}
    print(f"    {status} in {res['seconds']} s", flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", choices=("fake", "replay", "live", "tier1"))
    ap.add_argument("--live-e2e", action="store_true")
    args = ap.parse_args()
    want = set(args.only or ("fake", "replay", "live", "tier1"))
    smoke = ["uv", "run", "--directory", "backend", "--frozen", "python", "-m", "hmap.agents.models.smoke"]
    results: list[dict[str, object]] = []
    for router in ("off", "on"):
        r = {"HMAP_ROUTER": router}
        if "fake" in want:
            results.append(cell(f"fake / router {router} / tier 0", ["scripts/precommit.sh"], r, 5400))
        if "replay" in want:
            results.append(cell(f"replay / router {router} / tier 0", ["scripts/demo_final.sh"],
                                {**r, "HMAP_LLM_MODE": "replay"}, 1800))
        if "live" in want:
            if keys_present():
                results.append(cell(f"live-smoke / router {router} / cloud", smoke, {**r, "HMAP_LLM_MODE": "live"},
                                    600))
                if args.live_e2e:
                    results.append(cell(f"live e2e (tcp) / router {router} / cloud",
                                        ["scripts/demo_final.sh", "--live", "--only=tcp"], r, 3600))
            else:
                results.append({"cell": f"live-smoke / router {router} / cloud", "status": "not run (no keys in .env)"})
        if "tier1" in want:
            if ollama_up():
                results.append(cell(f"live-smoke / router {router} / tier 1 (local only)", smoke,
                                    {**r, "HMAP_LLM_MODE": "live", "HMAP_CLOUD_OK": "false",
                                     "HMAP_ROLE_MAP": "reasoner=qwen3.5:9b,judge=qwen3.5:9b,coder=qwen3.5:9b,"
                                                      "fast=qwen3.5:9b,classify=qwen3.5:9b,embed=nomic-embed-text"},
                                    1800))
            else:
                results.append({"cell": f"live-smoke / router {router} / tier 1", "status": "not run (Ollama is "
                                "not running)"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(OUT.read_text()) if OUT.exists() else {"cells": {}}
    cells = {**previous.get("cells", {}), **{str(c["cell"]): c for c in results}}
    OUT.write_text(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "cells": cells}, indent=1) + "\n")
    rows = ["| Cell | Status | Seconds |", "|---|---|---|"]
    rows += [f"| {c['cell']} | {c['status']} | {c.get('seconds', '')} |" for c in cells.values()]
    if DOC.exists():
        text = DOC.read_text()
        if START in text and END in text:
            head, rest = text.split(START, 1)
            _, tail = rest.split(END, 1)
            DOC.write_text(f"{head}{START}\n" + "\n".join(rows) + f"\n{END}{tail}")
    print("\n" + "\n".join(rows))
    return 0 if all(str(c["status"]).startswith(("green", "not run")) for c in results) else 1


if __name__ == "__main__":
    sys.exit(main())
