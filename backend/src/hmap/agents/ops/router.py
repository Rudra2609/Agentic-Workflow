"""Operations API (Sprint 4 items 4.16 and 4.18), mounted at ``/api/ops``. Project data is owner-only (404 for anyone
else's task, like the core API); ``POST`` needs the CSRF header (core middleware). Paths avoid the core prefixes
(``/tasks``, ``/dead-letters``), as the plug-in rules require.

- ``GET  /overview``             agents, queues, task states, dead letters, tracing / dashboard links (own projects)
- ``GET  /failures``             recent failed / dead-lettered / blocked / cancelled tasks of the user's projects
- ``GET  /explain/{task_id}``    "why did this task fail?"
- ``GET  /dlq``                  dead-lettered tasks (replayable) + bus dead letters of the user's projects
- ``POST /replay/{task_id}``     replay a dead-lettered task as a new attempt (``{"reason": ...}``, audited)
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from hmap.agents.ops.explain import explain
from hmap.api.deps import CurrentSession, get_system
from hmap.api.routers.projects import owned_project
from hmap.core.contracts import TaskState
from hmap.core.plugins import ProjectStopped
from hmap.manager import InvalidTaskState, UnknownTask
from hmap.obs import enabled as tracing_enabled
from hmap.system import HmapSystem

router = APIRouter()
SystemDep = Annotated[HmapSystem, Depends(get_system)]
FAILURE_STATES = {TaskState.FAILED, TaskState.DEAD_LETTERED, TaskState.BLOCKED, TaskState.CANCELLED,
                  TaskState.RETRY_SCHEDULED}


class ReplayIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500, description="why it is safe to try again (audit trail)")


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found.")


async def _own_projects(s: HmapSystem, info: Any) -> dict[str, dict[str, Any]]:
    return {p["project_id"]: p for p in await s.manager.list_projects(owner_id=info.user.user_id)}


async def _owned_task(s: HmapSystem, info: Any, task_id: str) -> dict[str, Any]:
    try:
        task = await s.manager.get_task(task_id)
    except UnknownTask:
        raise _not_found() from None
    try:
        await owned_project(task["project_id"], info, s.manager)
    except HTTPException:
        raise _not_found() from None
    return task


def _links(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {"jaeger": settings.jaeger_url, "grafana": settings.grafana_url, "prometheus": settings.prometheus_url}


def _row(t: Any, project: dict[str, Any]) -> dict[str, Any]:
    return {"task_id": t.task_id, "project_id": t.project_id, "project_name": project.get("name"),
            "capability": t.capability, "title": t.title or t.objective[:80], "state": t.state.value,
            "attempts": t.attempts, "replays": t.replays, "last_error": t.last_error,
            "updated_at": t.updated_at.isoformat(), "plan_task_id": t.plan_task_id}


@router.get("/overview")
async def overview(info: CurrentSession, s: SystemDep, request: Request) -> dict[str, Any]:
    projects = await _own_projects(s, info)
    states: dict[str, int] = {}
    for t in await s.store.list_tasks():
        if t.project_id in projects and not t.replaced:
            states[t.state.value] = states.get(t.state.value, 0) + 1
    agents: dict[str, int] = {}
    for a in await s.registry.list():
        agents[a.state.value] = agents.get(a.state.value, 0) + 1
    return {"tasks_by_state": states, "dead_lettered": states.get("DEAD_LETTERED", 0), "agents_by_state": agents,
            "queues": await s.bus.queue_depths(), "tracing": tracing_enabled(), "links": _links(request),
            "metrics_path": "/metrics"}


@router.get("/failures")
async def failures(info: CurrentSession, s: SystemDep,
                   limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[dict[str, Any]]:
    projects = await _own_projects(s, info)
    rows = [_row(t, projects[t.project_id]) for t in await s.store.list_tasks(states=FAILURE_STATES)
            if t.project_id in projects and not t.replaced]
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return rows[:limit]


@router.get("/explain/{task_id}")
async def explain_task(task_id: str, info: CurrentSession, s: SystemDep, request: Request) -> dict[str, Any]:
    await _owned_task(s, info, task_id)
    return await explain(s, task_id, jaeger_url=_links(request)["jaeger"], tracing=tracing_enabled(),
                         feed=getattr(request.app.state, "feed", None))


@router.get("/dlq")
async def dlq(info: CurrentSession, s: SystemDep) -> dict[str, Any]:
    projects = await _own_projects(s, info)
    tasks = [_row(t, projects[t.project_id]) for t in await s.store.list_tasks(states={TaskState.DEAD_LETTERED})
             if t.project_id in projects and not t.replaced]
    tasks.sort(key=lambda r: r["updated_at"], reverse=True)
    messages = []
    for d in await s.bus.dead_letters():
        body = d.body if isinstance(d.body, dict) else {}
        pid = body.get("project_id")
        if isinstance(pid, str) and pid in projects:
            messages.append({"queue": d.queue, "reason": d.reason, "attempts": d.attempts,
                             "message_type": body.get("message_type"), "task_id": body.get("task_id"),
                             "project_id": pid, "message_id": body.get("message_id")})
    return {"tasks": tasks, "messages": messages}


@router.post("/replay/{task_id}")
async def replay(task_id: str, body: ReplayIn, info: CurrentSession, s: SystemDep) -> dict[str, Any]:
    """Replay a dead-lettered task as a NEW execution (never automatic, never blind: research §26)."""
    await _owned_task(s, info, task_id)
    try:
        out = await s.manager.replay_dead_letter(task_id, operator=f"user:{info.user.user_id}",
                                                 reason=body.reason.strip())
    except (InvalidTaskState, ProjectStopped, ValueError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"task_id": task_id, "replay": out["replay"], "unblocked": out["unblocked"],
            "state": out["task"]["state"], "executions": len(out["task"]["executions"])}
