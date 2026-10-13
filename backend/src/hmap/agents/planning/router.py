"""Plan API (spec item 3.11), mounted at ``/api/planning``. Every route checks project ownership (404 for anyone
else's project, like the core API); state-changing calls need the CSRF header (core middleware).

- ``GET  /plan/{project_id}[?version=]``   the plan (latest, or a version) + report, versions, step states, and
                                            whether the requirements changed since it was made
- ``PUT  /plan/{project_id}``              a human edit -> validated -> the next version -> replaces the running plan
                                            (approval needed again); 409 when stale, 422 with the problems
- ``POST /plan/{project_id}/approve``      approve / reject (a comment is required to reject) a given version
- ``POST /plan/{project_id}/replan``       start a ``plan.replan`` task (feedback and / or failed steps)
- ``GET  /plan/{project_id}/roadmap.md``   the roadmap as Markdown
- ``GET  /capabilities``                   what a plan step may be assigned to
"""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, ValidationError

from hmap.agents.planning.agent import GRAPH_TYPE, REPORT_TYPE, report_id
from hmap.agents.planning.model import PlanReport
from hmap.agents.planning.replan import apply_edit
from hmap.agents.planning.templates import PHASE_ALLOWED, PLAN_CAPABILITIES
from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.capabilities import PLAN_REPLAN
from hmap.core.contracts.domain import RequirementSet, TaskGraph
from hmap.core.plugins import ProjectStopped
from hmap.manager import InvalidProjectState, StaleGraph

router = APIRouter()


class PlanEdit(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=200)
    base_version: int = Field(ge=1, description="the version the edit started from (stale edits are refused)")
    graph: dict[str, Any]


class Decision(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=2000)
    graph_version: int | None = Field(default=None, ge=1)


class ReplanIn(BaseModel):
    feedback: str | None = Field(default=None, max_length=2000)
    failed: list[str] = Field(default_factory=list, max_length=100)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=message)


async def _refs(m: Any, project_id: str, artifact_type: str) -> list[ArtifactRef]:
    return [r for r in await m.artifacts.list(project_id) if r.artifact_type == artifact_type]


async def _plan_versions(m: Any, project_id: str) -> list[ArtifactRef]:
    """Versions of the newest plan (each run makes a new task-graph artifact; edits and replans add versions)."""
    refs = await _refs(m, project_id, GRAPH_TYPE)
    if not refs:
        return []
    firsts = [r for r in refs if r.version == 1] or refs
    artifact_id = max(firsts, key=lambda r: r.created_at).artifact_id
    return sorted((r for r in refs if r.artifact_id == artifact_id), key=lambda r: r.version)


async def _report(m: Any, project_id: str, graph_ref: ArtifactRef) -> PlanReport | None:
    reports = [r for r in await _refs(m, project_id, REPORT_TYPE) if r.artifact_id == report_id(graph_ref.artifact_id)]
    match = [r for r in reports if r.version <= graph_ref.version]
    if not match:
        return None
    ref = max(match, key=lambda r: r.version)
    return PlanReport.model_validate_json(await m.artifacts.get(ref, project_id=project_id))


async def _states(m: Any, project_id: str) -> dict[str, str]:
    """Plan task id -> Manager state, for the current run's live (not replaced) plan steps."""
    project = await m.get_project_record(project_id)
    out: dict[str, str] = {}
    for t in await m.list_tasks(project_id):
        if t.get("plan_task_id") and t.get("run", 1) == project.current_run and not t.get("replaced"):
            out[t["plan_task_id"]] = t["state"]
    return out


async def _requirements(m: Any, project_id: str, report: PlanReport | None) -> tuple[ArtifactRef | None,
                                                                                       dict[str, Any]]:
    """The newest version of the requirement set the plan was made from (people may edit it later)."""
    refs = await _refs(m, project_id, "requirement-set")
    used = (report.requirement_set or {}) if report else {}
    artifact_id = used.get("artifact_id")
    mine = [r for r in refs if r.artifact_id == artifact_id] if artifact_id else []
    if not mine and refs:
        firsts = [r for r in refs if r.version == 1] or refs
        newest = max(firsts, key=lambda r: r.created_at).artifact_id
        mine = [r for r in refs if r.artifact_id == newest]
    latest = max(mine, key=lambda r: r.version) if mine else None
    info = {"artifact_id": latest.artifact_id if latest else None, "used_version": used.get("version"),
            "latest_version": latest.version if latest else None}
    info["changed"] = bool(latest and used.get("version") and latest.version != used.get("version")) or bool(
        latest and artifact_id and latest.artifact_id != artifact_id)
    return latest, info


@router.get("/capabilities")
async def capabilities(info: CurrentSession) -> dict[str, Any]:
    return {"capabilities": list(PLAN_CAPABILITIES),
            "by_phase": {phase: sorted(c for c in caps if c in PLAN_CAPABILITIES)
                         for phase, caps in PHASE_ALLOWED.items()}}


@router.get("/plan/{project_id}")
async def get_plan(project_id: str, info: CurrentSession, m: ManagerDep,
                   version: Annotated[int | None, Query(ge=1)] = None) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    versions = await _plan_versions(m, project_id)
    if not versions:
        raise _not_found("Plan")
    ref = versions[-1] if version is None else next((r for r in versions if r.version == version), None)
    if ref is None:
        raise _not_found("Plan version")
    graph = TaskGraph.model_validate_json(await m.artifacts.get(ref, project_id=project_id))
    report = await _report(m, project_id, ref)
    _, requirements = await _requirements(m, project_id, report)
    project = await m.get_project_record(project_id)
    return {"artifact": ref.model_dump(mode="json"), "graph": graph.model_dump(mode="json"),
            "report": report.model_dump(mode="json") if report else None,
            "versions": [{"version": r.version, "created_by": r.created_by, "created_at": r.created_at.isoformat()}
                         for r in versions],
            "submitted_version": project.graph_version, "project_state": project.state.value,
            "states": await _states(m, project_id), "requirements": requirements}


@router.get("/plan/{project_id}/roadmap.md")
async def roadmap_markdown(project_id: str, info: CurrentSession, m: ManagerDep) -> Response:
    await owned_project(project_id, info, m)
    versions = await _plan_versions(m, project_id)
    if not versions:
        raise _not_found("Plan")
    graph = TaskGraph.model_validate_json(await m.artifacts.get(versions[-1], project_id=project_id))
    return Response(graph.roadmap.markdown or "", media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="plan-v{graph.version}.md"'})


@router.put("/plan/{project_id}")
async def edit_plan(project_id: str, body: PlanEdit, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    versions = [r for r in await _plan_versions(m, project_id) if r.artifact_id == body.artifact_id]
    if not versions:
        raise _not_found("Plan")
    base_ref = versions[-1]
    if base_ref.version != body.base_version:
        raise _conflict(f"This plan was changed meanwhile (now version {base_ref.version}). Reload and try again.")
    states = await _states(m, project_id)
    if not states:
        raise _conflict("This plan is not active yet (or was replaced by a newer run); wait until it is shown.")
    base = TaskGraph.model_validate_json(await m.artifacts.get(base_ref, project_id=project_id))
    previous = await _report(m, project_id, base_ref)
    rs_ref, _ = await _requirements(m, project_id, previous)
    if rs_ref is None:
        raise _not_found("Requirements")
    rs = RequirementSet.model_validate_json(await m.artifacts.get(rs_ref, project_id=project_id))
    try:
        graph, report, problems = apply_edit(body.graph, rs, base=base, states=states,
                                             kind=previous.project_kind if previous else "software",
                                             author=f"user:{info.user.user_id}", previous=previous)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail={"message": f"Not saved: {str(exc).splitlines()[0][:300]}", "issues": []}) from None
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={
            "message": "Not saved: " + "; ".join(p.message for p in problems[:3]),
            "issues": [p.model_dump(mode="json") for p in problems]})
    graph = graph.model_copy(update={"project_id": project_id})
    report = report.model_copy(update={"requirement_set": {"artifact_id": rs_ref.artifact_id,
                                                           "version": rs_ref.version}})
    author = f"user:{info.user.user_id}"
    new = await m.artifacts.put(graph.model_dump_json(indent=2).encode(), project_id=project_id,
                                artifact_type=GRAPH_TYPE, media_type="application/json", created_by=author,
                                artifact_id=body.artifact_id)
    await m.artifacts.put(report.model_copy(update={"graph_version": new.version}).model_dump_json(indent=2).encode(),
                          project_id=project_id, artifact_type=REPORT_TYPE, media_type="application/json",
                          created_by=author, artifact_id=report_id(body.artifact_id))
    try:
        await m.replace_graph(project_id, graph, require_approval=True)
    except (StaleGraph, InvalidProjectState, ProjectStopped) as exc:
        raise _conflict(f"Saved as version {new.version}, but it could not replace the running plan: {exc}") from None
    return await get_plan(project_id, info, m)


@router.post("/plan/{project_id}/approve")
async def decide(project_id: str, body: Decision, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    if not body.approved and not (body.comment or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Say why the plan is rejected.")
    try:
        await m.approve(project_id, body.approved, (body.comment or "").strip() or None,
                        graph_version=body.graph_version)
    except StaleGraph as exc:
        raise _conflict(f"The plan changed meanwhile ({exc}). Reload and decide on the new version.") from None
    except InvalidProjectState as exc:
        raise _conflict(str(exc)) from None
    return await get_plan(project_id, info, m)


@router.post("/plan/{project_id}/replan", status_code=status.HTTP_202_ACCEPTED)
async def start_replan(project_id: str, body: ReplanIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    versions = await _plan_versions(m, project_id)
    if not versions:
        raise _not_found("Plan")
    states = await _states(m, project_id)
    if not states:
        raise _conflict("There is no active plan to change in this run.")
    previous = await _report(m, project_id, versions[-1])
    rs_ref, _ = await _requirements(m, project_id, previous)
    if rs_ref is None:
        raise _not_found("Requirements")
    feedback = (body.feedback or "").strip()
    failed = [f for f in dict.fromkeys(body.failed) if f in states]
    what = f"Replan: {feedback[:80]}" if feedback else "Replan around failed steps" if failed else \
        "Replan with the latest requirements"
    try:
        task_id = await m.create_task(project_id, PLAN_REPLAN, what, artifact_refs=[versions[-1], rs_ref],
                                      inputs={"feedback": feedback, "failed": failed, "states": states},
                                      acceptance_criteria=["finished steps are kept", "every requirement covered"])
    except ProjectStopped as exc:
        raise _conflict(str(exc)) from None
    return {"task_id": task_id, "base_version": versions[-1].version}
