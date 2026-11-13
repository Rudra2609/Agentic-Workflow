"""Coding API (Sprint 7 item 7.14), mounted at ``/api/coding``. Every project route checks ownership (404 for anyone
else's project, like the core API); ``POST`` needs the CSRF header (core middleware).

- ``GET  /runs/{project_id}``                          coding steps of the project (newest first), summaries
- ``GET  /runs/{project_id}/{task_id}``                one step: the trace (tool calls, edits, commands, checks),
                                                       the ``CodeChangeSet``, the diff, the revisions it started
- ``GET  /runs/{project_id}/{task_id}/diff``           the unified diff (text)
- ``GET  /runs/{project_id}/{task_id}/files[?path=]``  the workspace after the step: file list, or one file (read
                                                       from the stored tarball; paths are jailed)
- ``GET  /runs/{project_id}/{task_id}/workspace.zip``  download the workspace
- ``GET  /heads/{project_id}``                         the project's workspace head (all coding steps together)
- ``POST /runs/{project_id}/{task_id}/revise``         "Request changes": a ``code.revise`` task (plan D14)
"""

import io
import json
import zipfile
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from hmap.agents.coding.model import (
    CHANGESET_TYPE,
    HEAD_TYPE,
    PATCH_TYPE,
    TRACE_TYPE,
    WORKSPACE_TYPE,
    changeset_id,
    head_id,
    patch_id,
    trace_id,
    workspace_id,
)
from hmap.agents.coding.revise import revision_inputs
from hmap.agents.coding.workspace import files_from_tar
from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.capabilities import CODE_REVISE
from hmap.core.plugins import ProjectStopped

router = APIRouter()


class ReviseIn(BaseModel):
    required_changes: list[str] = Field(min_length=1, max_length=10)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def _latest_by_id(refs: list[ArtifactRef], artifact_type: str) -> dict[str, ArtifactRef]:
    out: dict[str, ArtifactRef] = {}
    for r in refs:
        if r.artifact_type == artifact_type and (r.artifact_id not in out or r.version > out[r.artifact_id].version):
            out[r.artifact_id] = r
    return out


async def _json(m: Any, project_id: str, ref: ArtifactRef) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(await m.artifacts.get(ref, project_id=project_id))
    return data


def summary(trace: dict[str, Any]) -> dict[str, Any]:
    steps = trace.get("steps") or []
    return {"task_id": trace.get("task_id"), "capability": trace.get("capability"), "status": trace.get("status"),
            "outcome": trace.get("outcome"), "stop_reason": trace.get("stop_reason"),
            "objective": (trace.get("objective") or "")[:300], "base": trace.get("base"),
            "template": trace.get("template"), "files_changed": trace.get("files_changed") or [],
            "checks": {c["name"]: c["status"] for c in trace.get("checks") or []},
            "model_calls": len(steps), "tokens": sum(s.get("prompt_tokens", 0) + s.get("completion_tokens", 0)
                                                     for s in steps),
            "edits": len(trace.get("edits") or []), "edits_rejected": sum(not e.get("ok") for e in trace.get("edits")
                                                                          or []),
            "commands": len(trace.get("commands") or []), "denials": len(trace.get("denials") or []),
            "flags": trace.get("flags") or [], "revision_round": trace.get("revision_round", 0),
            "original_task_id": trace.get("original_task_id"), "head_version": trace.get("head_version")}


async def _trace(m: Any, project_id: str, task_id: str) -> tuple[dict[str, Any], list[ArtifactRef]]:
    refs = await m.artifacts.list(project_id)
    ref = _latest_by_id(refs, TRACE_TYPE).get(trace_id(task_id))
    if ref is None:
        raise _not_found("Coding step")
    return await _json(m, project_id, ref), refs


async def _tree(m: Any, project_id: str, refs: list[ArtifactRef], artifact_id: str,
                artifact_type: str) -> dict[str, str]:
    ref = _latest_by_id(refs, artifact_type).get(artifact_id)
    if ref is None:
        raise _not_found("Workspace")
    return files_from_tar(await m.artifacts.get(ref, project_id=project_id))


@router.get("/runs/{project_id}")
async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    latest = _latest_by_id(refs, TRACE_TYPE)
    out = [summary(await _json(m, project_id, ref)) | {"updated_at": ref.created_at.isoformat()}
           for ref in latest.values()]
    out.sort(key=lambda r: r["updated_at"], reverse=True)
    return out


async def _revisions(m: Any, project_id: str, task_id: str) -> list[dict[str, Any]]:
    try:
        tasks = await m.list_tasks(project_id)
    except Exception:
        return []
    out = []
    for t in tasks:
        t = t if isinstance(t, dict) else t.to_dict()
        if t.get("parent_task_id") == task_id and t.get("capability") == CODE_REVISE:
            out.append({"task_id": t.get("task_id"), "state": t.get("state"), "objective": t.get("objective")})
    return out


@router.get("/runs/{project_id}/{task_id}")
async def get_run(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    trace, refs = await _trace(m, project_id, task_id)
    ccs_ref = _latest_by_id(refs, CHANGESET_TYPE).get(changeset_id(task_id))
    patch_ref = _latest_by_id(refs, PATCH_TYPE).get(patch_id(task_id))
    trace_ref = _latest_by_id(refs, TRACE_TYPE)[trace_id(task_id)]
    return {"summary": summary(trace) | {"updated_at": trace_ref.created_at.isoformat()}, "trace": trace,
            "changeset": await _json(m, project_id, ccs_ref) if ccs_ref else None,
            "changeset_artifact": ccs_ref.model_dump(mode="json") if ccs_ref else None,
            "diff": (await m.artifacts.get(patch_ref, project_id=project_id)).decode("utf-8") if patch_ref else "",
            "revisions": await _revisions(m, project_id, task_id)}


@router.get("/runs/{project_id}/{task_id}/diff", response_class=PlainTextResponse)
async def get_diff(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> str:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    ref = _latest_by_id(refs, PATCH_TYPE).get(patch_id(task_id))
    if ref is None:
        raise _not_found("Diff")
    return str((await m.artifacts.get(ref, project_id=project_id)).decode("utf-8"))


def _check_path(path: str) -> str:
    clean = path.strip()
    if not clean or "\0" in clean or clean.startswith(("/", "\\", "~")) or ".." in clean.replace("\\", "/").split("/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Use a path inside the workspace.")
    return clean


@router.get("/runs/{project_id}/{task_id}/files")
async def get_files(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep,
                    path: str | None = Query(default=None, max_length=500)) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    files = await _tree(m, project_id, refs, workspace_id(task_id), WORKSPACE_TYPE)
    if path is None:
        return {"files": [{"path": p, "lines": t.count("\n") + 1, "bytes": len(t.encode())} for p, t in files.items()]}
    rel = _check_path(path)
    if rel not in files:
        raise _not_found("File")
    return {"path": rel, "text": files[rel]}


def _zip(files: dict[str, str], folder: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, text in files.items():
            info = zipfile.ZipInfo(f"{folder}/{rel}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text)
    return buf.getvalue()


@router.get("/runs/{project_id}/{task_id}/workspace.zip")
async def download(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> Response:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    files = await _tree(m, project_id, refs, workspace_id(task_id), WORKSPACE_TYPE)
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in task_id)[:60]
    return Response(_zip(files, name), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})


@router.get("/heads/{project_id}")
async def get_head(project_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    versions = sorted((r for r in refs if r.artifact_type == HEAD_TYPE and r.artifact_id == head_id(project_id)),
                      key=lambda r: r.version)
    if not versions:
        return {"version": None, "versions": 0, "files": []}
    files = files_from_tar(await m.artifacts.get(versions[-1], project_id=project_id))
    return {"version": versions[-1].version, "versions": len(versions), "updated_at": versions[-1].created_at,
            "files": [{"path": p, "lines": t.count("\n") + 1} for p, t in files.items()]}


@router.post("/runs/{project_id}/{task_id}/revise", status_code=status.HTTP_202_ACCEPTED)
async def request_changes(project_id: str, task_id: str, body: ReviseIn, info: CurrentSession,
                          m: ManagerDep) -> dict[str, Any]:
    """A human asks for changes to a coding step's result: a ``code.revise`` task (bounded rounds)."""
    await owned_project(project_id, info, m)
    trace, refs = await _trace(m, project_id, task_id)
    if trace.get("status") != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This coding step is still running.")
    ccs_ref = _latest_by_id(refs, CHANGESET_TYPE).get(changeset_id(task_id))
    if ccs_ref is None:
        raise _not_found("Code change")
    changes = [c.strip()[:500] for c in body.required_changes if c.strip()]
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Describe at least one change.")
    round_ = int(trace.get("revision_round") or 0) + 1
    limit = Settings.from_env().coding_max_revisions
    if round_ > limit:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"The limit of {limit} revision rounds is reached.")
    original = trace.get("original_task_id") or task_id
    try:
        new_id = await m.create_task(
            project_id, CODE_REVISE, f"Revise the code: {changes[0][:160]}",
            acceptance_criteria=[*(trace.get("acceptance_criteria") or [])[:10], *changes],
            inputs=revision_inputs(ccs_ref, required_changes=changes, round_=round_, original_task_id=original),
            parent_task_id=task_id)
    except ProjectStopped as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"task_id": new_id, "round": round_, "revision_of": task_id}
