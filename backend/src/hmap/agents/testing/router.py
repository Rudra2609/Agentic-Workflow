"""Testing API (Sprint 8 item 8.14, plan D16), mounted at ``/api/testing``. Every route checks project ownership
(404 for anyone else's project, like the core API); ``POST`` needs the CSRF header (core middleware).

- ``GET  /runs/{project_id}``                    test runs of the project (newest first), summaries
- ``GET  /runs/{project_id}/{task_id}``          one run: stages, steps, failures with hints, report, generated
                                                 tests, the loop (earlier and later rounds of the same coding step)
- ``GET  /runs/{project_id}/{task_id}/log``      the full stage log (text)
- ``POST /runs/{project_id}/{task_id}/rerun``    "Re-run": a new ``test.run`` with the same inputs and artifacts
- ``GET  /quarantine/{project_id}``              flaky tests that do not count right now (and recently released)
- ``POST /quarantine/{project_id}/release``      a person releases one (``{"test": node id}``)
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from hmap.agents.testing import quarantine
from hmap.agents.testing.model import (
    GENERATED_TYPE,
    LOG_TYPE,
    REPORT_TYPE,
    TRACE_TYPE,
    generated_id,
    log_id,
    report_id,
    trace_id,
)
from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.capabilities import TEST_RUN
from hmap.core.plugins import ProjectStopped

router = APIRouter()


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def _latest(refs: list[ArtifactRef], artifact_type: str) -> dict[str, ArtifactRef]:
    out: dict[str, ArtifactRef] = {}
    for r in refs:
        if r.artifact_type == artifact_type and (r.artifact_id not in out or r.version > out[r.artifact_id].version):
            out[r.artifact_id] = r
    return out


def summary(trace: dict[str, Any]) -> dict[str, Any]:
    failures = [f for f in trace.get("failures") or [] if f.get("category") != "LINT" and not f.get("flaky")]
    stages = trace.get("stages") or []
    return {"task_id": trace.get("task_id"), "status": trace.get("status"), "passed": trace.get("passed"),
            "backend": trace.get("backend"), "objective": (trace.get("objective") or "")[:300],
            "stages": {s["name"]: s["status"] for s in stages},
            "tests": sum(int(s.get("tests") or 0) for s in stages),
            "tests_failed": sum(int(s.get("tests_failed") or 0) for s in stages),
            "failures": len(failures), "lint": sum(f.get("category") == "LINT" for f in trace.get("failures") or []),
            "flaky": len(trace.get("flaky") or []), "coverage": trace.get("coverage"),
            "pass_ratio": trace.get("pass_ratio"), "loop_round": (trace.get("loop") or {}).get("round", 0),
            "coding_task_id": trace.get("coding_task_id"), "generated": len((trace.get("generated") or {})
                                                                           .get("kept") or []),
            "seconds": trace.get("seconds")}


async def _json(m: Any, project_id: str, ref: ArtifactRef) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(await m.artifacts.get(ref, project_id=project_id))
    return data


@router.get("/runs/{project_id}")
async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    out = [summary(await _json(m, project_id, ref)) | {"updated_at": ref.created_at.isoformat()}
           for ref in _latest(refs, TRACE_TYPE).values()]
    out.sort(key=lambda r: r["updated_at"], reverse=True)
    return out


async def _loop(m: Any, project_id: str, trace: dict[str, Any], traces: dict[str, ArtifactRef]) -> list[dict[str, Any]]:
    """Every test run of the same loop (same origin), in round order."""
    origin = (trace.get("loop") or {}).get("origin_task_id") or trace.get("task_id")
    rows = []
    for ref in traces.values():
        t = await _json(m, project_id, ref)
        if t.get("task_id") == origin or (t.get("loop") or {}).get("origin_task_id") == origin:
            rows.append(summary(t))
    rows.sort(key=lambda r: r["loop_round"])
    return rows


@router.get("/runs/{project_id}/{task_id}")
async def get_run(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    traces = _latest(refs, TRACE_TYPE)
    tr = traces.get(trace_id(task_id))
    if tr is None:
        raise _not_found("Test run")
    trace = await _json(m, project_id, tr)
    rep = _latest(refs, REPORT_TYPE).get(report_id(task_id))
    gen = _latest(refs, GENERATED_TYPE).get(generated_id(task_id))
    return {"summary": summary(trace) | {"updated_at": tr.created_at.isoformat()}, "trace": trace,
            "report": await _json(m, project_id, rep) if rep else None,
            "report_artifact": rep.model_dump(mode="json") if rep else None,
            "generated_tests": (await m.artifacts.get(gen, project_id=project_id)).decode("utf-8") if gen else None,
            "loop": await _loop(m, project_id, trace, traces)}


@router.get("/runs/{project_id}/{task_id}/log", response_class=PlainTextResponse)
async def get_log(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> str:
    await owned_project(project_id, info, m)
    ref = _latest(await m.artifacts.list(project_id), LOG_TYPE).get(log_id(task_id))
    if ref is None:
        raise _not_found("Log")
    return str((await m.artifacts.get(ref, project_id=project_id)).decode("utf-8", "replace"))


@router.post("/runs/{project_id}/{task_id}/rerun", status_code=status.HTTP_202_ACCEPTED)
async def rerun(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    try:
        task = await m.get_task(task_id)
    except Exception as exc:
        raise _not_found("Test run") from exc
    if task.get("project_id") != project_id or task.get("capability") != TEST_RUN:
        raise _not_found("Test run")
    if task.get("state") not in ("COMPLETED", "FAILED", "DEAD_LETTERED", "CANCELLED"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This test run is still going.")
    inputs = {k: v for k, v in (task.get("inputs") or {}).items() if k != "loop"}
    try:
        new_id = await m.create_task(
            project_id, TEST_RUN, f"Re-run: {str(task.get('objective'))[:180]}",
            acceptance_criteria=list(task.get("acceptance_criteria") or [])[:20], inputs=inputs,
            artifact_refs=[ArtifactRef.model_validate(r) for r in task.get("artifact_refs") or []],
            parent_task_id=task_id)
    except ProjectStopped as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"task_id": new_id, "rerun_of": task_id}


class ReleaseIn(BaseModel):
    test: str = Field(min_length=1, max_length=500)


@router.get("/quarantine/{project_id}")
async def get_quarantine(project_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    return quarantine.as_dict(await quarantine.load(m.artifacts, project_id)) | {
        "release_after": quarantine.RELEASE_AFTER}


@router.post("/quarantine/{project_id}/release")
async def release_test(project_id: str, body: ReleaseIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    q = await quarantine.load(m.artifacts, project_id)
    if not quarantine.release(q, body.test):
        raise _not_found("Quarantined test")
    await quarantine.save(m.artifacts, q, f"user:{info.user.user_id}")
    return quarantine.as_dict(q)
