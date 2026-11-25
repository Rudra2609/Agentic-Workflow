"""Models API (item 11.13), mounted at ``/api/models``. Signed-in users only; nothing here is project data (a route
decision is role / plug-in / model / reason / outcome, never a prompt), so every signed-in user sees the same pages.

| Route | |
|---|---|
| ``GET registry`` | the models (installed, resident, memory, tok/s from the benchmark), whether Ollama answers |
| ``POST registry/sync`` | re-read Ollama / MLX / llama.cpp / the cloud routes |
| ``POST registry/{id}/pin`` / ``disable`` / ``enable`` | the freeze (11.24); a disabled model is never used |
| ``POST pull`` | the ``ollama pull`` command of a tier model; runs it with ``HMAP_MODELS_ALLOW_PULL`` |
| ``GET hardware`` | RAM / swap / GPU / Docker / resident models, feasibility per local model, the sizing table |
| ``GET routes`` | recent decisions (filters ``role``, ``plugin``), a summary, the router's live state; with ``since`` |
|  | only decisions made or finished after that time: the Models tab polls it every 2 s (the decision stream) |
| ``GET bench`` · ``GET bench/{set}`` | benchmark rows (store + ``samples/models/bench/results``), the quality table |
| ``GET finetune`` | fine-tune runs and their held-out results |
"""

import asyncio
import contextlib
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from hmap.agents.models.hardware import feasible, profile, sizing_table, snapshot_specs
from hmap.agents.models.model import now_iso
from hmap.agents.models.registry import ModelRegistry
from hmap.agents.models.router import MEMORY_STORE, TABLE_PATH, ModelRouter, load_table
from hmap.agents.models.store import ModelStore, PgModelStore
from hmap.api.deps import CurrentSession
from hmap.core.config import Settings

router = APIRouter()
SAMPLES = Path(__file__).resolve().parents[5] / "samples" / "models"
TIER_MODELS = {"lite": ["qwen3.5:4b", "nomic-embed-text"], "1": ["qwen3.5:9b", "nomic-embed-text"],
               "2": ["qwen3.5:9b", "qwen3.5:4b", "nomic-embed-text"]}


def _settings(request: Request) -> Settings:
    s = getattr(request.app.state, "settings", None)
    return s if isinstance(s, Settings) else Settings.from_env()


def store_for(app_state: Any) -> ModelStore:
    system = getattr(app_state, "system", None)
    db = getattr(getattr(system, "persistence", None), "db", None)
    return PgModelStore(db) if db is not None else MEMORY_STORE


def live_router(app_state: Any) -> ModelRouter | None:
    system = getattr(app_state, "system", None)
    route = getattr(getattr(system, "llm", None), "route", None)
    return route if isinstance(route, ModelRouter) else None


def _tok_s() -> dict[str, float]:
    """Generation speed per local model: the harness's speed results, else the bake-off snapshot."""
    out: dict[str, float] = {}
    for path in (SAMPLES / "data" / "speed.json", SAMPLES / "bench" / "results" / "speed.json"):
        with contextlib.suppress(OSError, ValueError):
            for model, row in json.loads(path.read_text(encoding="utf-8")).items():
                if isinstance(row, dict) and row.get("tok_s"):
                    out[model] = float(row["tok_s"])
    return out


@router.get("/registry")
async def list_models(info: CurrentSession, request: Request, sync: bool = False) -> dict[str, Any]:
    store = store_for(request.app.state)
    registry = ModelRegistry(_settings(request), store)
    synced = sync or not await store.list_models()
    rows = await registry.sync() if synced else await store.list_models()
    speeds = _tok_s()
    models = []
    for r in rows:
        d = r.model_dump(mode="json")
        if d["spec"]["tok_s"] is None and r.spec.id in speeds:
            d["spec"]["tok_s"] = speeds[r.spec.id]
        models.append(d)
    return {"models": models, "ollama_up": registry.ollama_up if synced else None, "error": registry.last_error}


@router.post("/registry/sync")
async def sync_models(info: CurrentSession, request: Request) -> dict[str, Any]:
    registry = ModelRegistry(_settings(request), store_for(request.app.state))
    rows = await registry.sync()
    return {"models": [r.model_dump(mode="json") for r in rows], "ollama_up": registry.ollama_up,
            "error": registry.last_error}


async def _flag(request: Request, model_id: str, **flags: Any) -> dict[str, Any]:
    if not await store_for(request.app.state).set_flags(model_id, **flags):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such model in the registry.")
    return {"id": model_id, **flags}


@router.post("/registry/{model_id:path}/pin")
async def pin_model(model_id: str, info: CurrentSession, request: Request) -> dict[str, Any]:
    return await _flag(request, model_id, pinned=True)


@router.post("/registry/{model_id:path}/disable")
async def disable_model(model_id: str, info: CurrentSession, request: Request) -> dict[str, Any]:
    return await _flag(request, model_id, status="disabled")


@router.post("/registry/{model_id:path}/enable")
async def enable_model(model_id: str, info: CurrentSession, request: Request) -> dict[str, Any]:
    return await _flag(request, model_id, status="installed")


class PullIn(BaseModel):
    model: str


@router.post("/pull")
async def pull_model(body: PullIn, info: CurrentSession, request: Request) -> dict[str, Any]:
    allowed = sorted({m for models in TIER_MODELS.values() for m in models})
    if body.model not in allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Only tier models can be pulled here: "
                                                                f"{', '.join(allowed)}.")
    command = f"OLLAMA_MODELS=/Volumes/Tirth_SSD/ollama ollama pull {body.model}"
    settings = _settings(request)
    if not settings.models_allow_pull or shutil.which("ollama") is None:
        return {"started": False, "command": command,
                "why": "run it in a terminal (HMAP_MODELS_ALLOW_PULL is off)" if shutil.which("ollama")
                else "the ollama command is not installed here"}
    subprocess.Popen(["ollama", "pull", body.model], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"started": True, "command": command}


@router.get("/hardware")
async def hardware(info: CurrentSession, request: Request) -> dict[str, Any]:
    settings = _settings(request)
    hw = await asyncio.to_thread(profile, settings.ollama_base_url)
    specs = snapshot_specs()
    return {"hardware": hw.to_dict(),
            "feasibility": [feasible(m, s, hw).__dict__ for m, s in sorted(specs.items())],
            "sizing": sizing_table(specs)}


def _summary(records: list[Any]) -> dict[str, Any]:
    answered = Counter(r.answered_by.partition(":")[0] for r in records if r.answered_by)
    return {"decisions": len(records), "answered_by": dict(answered),
            "failed": sum(1 for r in records if r.ok is False), "rules": dict(Counter(r.rule for r in records)),
            "rate_limited": sum(r.rate_limited for r in records), "attempts": sum(r.attempts for r in records)}


@router.get("/routes")
async def routes(info: CurrentSession, request: Request, limit: int = 200, role: str | None = None,
                 plugin: str | None = None, since: str | None = None) -> dict[str, Any]:
    """``since`` (an ISO time from the previous answer's ``now``): only decisions logged after it. A decision's
    outcome is written to the same row, so a poll also sees calls that finished since."""
    records = await store_for(request.app.state).recent_routes(limit=min(max(limit, 1), 2000), role=role,
                                                               plugin=plugin)
    if since:
        records = [r for r in records if r.at > since or r.ok is None]
    live = live_router(request.app.state)
    return {"enabled": _settings(request).router == "on", "summary": _summary(records), "now": now_iso(),
            "routes": [r.model_dump(mode="json") for r in records],
            "live": live.snapshot() if live is not None else None}


def _result_files() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in sorted((SAMPLES / "bench" / "results").glob("*.json")):
        with contextlib.suppress(OSError, ValueError):
            out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


@router.get("/bench")
async def bench(info: CurrentSession, request: Request) -> dict[str, Any]:
    rows = await store_for(request.app.state).list_bench()
    return {"rows": [r.model_dump(mode="json") for r in rows], "files": _result_files(), "table": load_table(),
            "table_path": str(TABLE_PATH.relative_to(SAMPLES.parents[1]))}


@router.get("/bench/{set_name}")
async def bench_set(set_name: str, info: CurrentSession, request: Request) -> dict[str, Any]:
    rows = await store_for(request.app.state).list_bench(set_name=set_name)
    files = _result_files()
    if not rows and set_name not in files:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No benchmark results for that set.")
    return {"rows": [r.model_dump(mode="json") for r in rows], "file": files.get(set_name)}


@router.get("/finetune")
async def finetune(info: CurrentSession, request: Request) -> dict[str, Any]:
    runs = await store_for(request.app.state).list_finetune()
    files = {}
    for path in sorted((SAMPLES / "finetune").glob("*.json")):
        with contextlib.suppress(OSError, ValueError):
            files[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return {"runs": runs, "files": files}
