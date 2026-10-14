"""Refinement API (Sprint 4 item 4.13), mounted at ``/api/refine``. Every route checks project ownership (404 for
anyone else's project, like the core API); ``POST`` needs the CSRF header (core middleware).

- ``GET  /runs/{project_id}``                              refinement runs of the project (newest first), summaries
- ``GET  /runs/{project_id}/{run_id}``                     one run: every iteration (critique, issues by category,
                                                           strategy, Reflexion note, per-critic scores), stop reason
- ``GET  /runs/{project_id}/{run_id}/outputs/{index}``     the output of iteration ``index``
- ``GET  /runs/{project_id}/{run_id}/diff?a=&b=``          what changed between two iterations' outputs
- ``POST /runs/{project_id}``                              check and improve an artifact now (a ``refine.run`` task)
- ``GET  /policy``                                         the default stop policy (for the UI)
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from hmap.agents.refine.diff import diff
from hmap.agents.refine.stop import default_policy
from hmap.agents.refine.trace import OUTPUT_TYPE, PROGRESS_TYPE, TRACE_TYPE
from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.capabilities import REFINE_RUN
from hmap.core.plugins import ProjectStopped

router = APIRouter()

SUMMARY_FIELDS = ("run_id", "task_id", "capability", "subject", "status", "best_iteration", "stop_reason",
                  "base_score", "best_score", "tokens", "model_calls", "seconds", "started_at", "updated_at",
                  "applied", "error", "output_artifact")
CONTEXT = {"requirement-set": ["document-model"], "task-graph": ["requirement-set", "plan-report"]}


class RefineIn(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, ge=1)
    stop_policy: dict[str, Any] | None = None


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


async def _runs(m: Any, project_id: str) -> dict[str, ArtifactRef]:
    """run id -> the ref to show: the final trace when the run stopped, else its newest progress version."""
    refs = await m.artifacts.list(project_id)
    final: dict[str, ArtifactRef] = {}
    progress: dict[str, ArtifactRef] = {}
    for r in refs:
        if r.artifact_type == TRACE_TYPE:
            if r.artifact_id not in final or r.version > final[r.artifact_id].version:
                final[r.artifact_id] = r
        elif r.artifact_type == PROGRESS_TYPE:
            run_id = r.artifact_id.removesuffix("-progress")
            if run_id not in progress or r.version > progress[run_id].version:
                progress[run_id] = r
    return {**progress, **final}


async def _load(m: Any, project_id: str, ref: ArtifactRef) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(await m.artifacts.get(ref, project_id=project_id))
    return data


@router.get("/policy")
async def policy(info: CurrentSession) -> dict[str, Any]:
    return {"default": default_policy().describe(), "hard_max_iters": 10}


@router.get("/runs/{project_id}")
async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]:
    await owned_project(project_id, info, m)
    out = []
    for ref in (await _runs(m, project_id)).values():
        run = await _load(m, project_id, ref)
        item = {k: run.get(k) for k in SUMMARY_FIELDS}
        item["iterations"] = max(0, len(run.get("iterations") or []) - 1)
        last = (run.get("iterations") or [{}])[-1]
        item["issues_by_category"] = last.get("issues_by_category") or {}
        item["scores"] = [it.get("score") for it in run.get("iterations") or []]
        out.append(item)
    out.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return out


@router.get("/runs/{project_id}/{run_id}")
async def get_run(project_id: str, run_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    ref = (await _runs(m, project_id)).get(run_id)
    if ref is None:
        raise _not_found("Refinement run")
    return await _load(m, project_id, ref)


async def _output(m: Any, project_id: str, run_id: str, index: int) -> Any:
    refs = [r for r in await m.artifacts.list(project_id)
            if r.artifact_type == OUTPUT_TYPE and r.artifact_id == f"{run_id}-out" and r.version == index + 1]
    if not refs:
        raise _not_found("Iteration output")
    return json.loads(await m.artifacts.get(refs[0], project_id=project_id))


@router.get("/runs/{project_id}/{run_id}/outputs/{index}")
async def get_output(project_id: str, run_id: str, index: int, info: CurrentSession, m: ManagerDep) -> Any:
    await owned_project(project_id, info, m)
    return await _output(m, project_id, run_id, index)


@router.get("/runs/{project_id}/{run_id}/diff")
async def get_diff(project_id: str, run_id: str, info: CurrentSession, m: ManagerDep,
                   a: Annotated[int, Query(ge=0)] = 0, b: Annotated[int, Query(ge=0)] = 1) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    before = await _output(m, project_id, run_id, a)
    after = await _output(m, project_id, run_id, b)
    return {"a": a, "b": b, "changes": diff(before, after)}


@router.post("/runs/{project_id}", status_code=status.HTTP_202_ACCEPTED)
async def start_run(project_id: str, body: RefineIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    """Check and improve one artifact of the project now (a ``refine.run`` task; its context artifacts — the
    document model for requirements, the requirements and report for a plan — are attached automatically)."""
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    mine = [r for r in refs if r.artifact_id == body.artifact_id and (body.version is None or
                                                                       r.version == body.version)]
    if not mine:
        raise _not_found("Artifact")
    target = max(mine, key=lambda r: r.version)
    context: list[ArtifactRef] = []
    for kind in CONTEXT.get(target.artifact_type, []):
        candidates = [r for r in refs if r.artifact_type == kind]
        if kind == "plan-report":
            candidates = [r for r in candidates if r.artifact_id == f"{target.artifact_id}-report"]
        if candidates:
            context.append(max(candidates, key=lambda r: (r.created_at, r.version)))
    try:
        task_id = await m.create_task(project_id, REFINE_RUN, f"Check and improve the {target.artifact_type}",
                                      artifact_refs=[target, *context],
                                      inputs={"artifact_id": target.artifact_id, "kind": target.artifact_type,
                                              **({"stop_policy": body.stop_policy} if body.stop_policy else {})},
                                      acceptance_criteria=["the result is kept only if it scores higher"])
    except ProjectStopped as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"task_id": task_id, "artifact_id": target.artifact_id, "version": target.version}
