"""Projects, runs, documents, plans, approvals, tasks and artifacts (Sprint 1 item 1.15) — all owner-scoped.

Every route authenticates (``CurrentSession``) and then loads the project through :func:`owned_project`, which
returns 404 for a project that does not exist, was deleted, or belongs to someone else (the same answer, so ids
cannot be probed). The owner always comes from the session, never from the request.
"""

import re
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from hmap.api.deps import CurrentSession, get_manager
from hmap.core import policy
from hmap.core.contracts import ArtifactRef, DomainEvent, EventType, TaskGraph
from hmap.core.errors import ArtifactIntegrityError
from hmap.core.plugins import ProjectStopped
from hmap.manager.manager import InvalidProjectState, Manager, UnknownProject, UnknownTask
from hmap.manager.records import ProjectRecord
from hmap.services.artifact.memory import ArtifactNotFound

router = APIRouter(tags=["projects"])
ManagerDep = Annotated[Manager, Depends(get_manager)]

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_DOCUMENTS = 20                         # per upload (one run)
MAX_TOTAL_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_GOAL_CHARS = 20_000
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED_TYPES = {"application/pdf", DOCX, "text/plain", "text/markdown", "image/png", "image/jpeg"}
# Browsers often send no type (or octet-stream) for Markdown and some Word files; then the extension decides.
EXTENSION_TYPES = {".pdf": "application/pdf", ".docx": DOCX, ".txt": "text/plain", ".md": "text/markdown",
                   ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
# Served inline for preview; everything else is a download. Never inline HTML/SVG (script injection).
INLINE_TYPES = {"text/plain", "text/markdown", "application/json", "application/pdf", "image/png", "image/jpeg"}
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str | None = Field(default=None, max_length=MAX_GOAL_CHARS,
                             description="what the user wants done, in plain words; starts the first run")
    auto_approve: bool = Field(default=False, description="show the plan, then continue without a human approval")
    cloud_ok: bool = Field(default=True, description="false keeps the project on this computer (no cloud models)")
    refine: bool | None = Field(default=None, description="check and improve each result before it is used (slower); "
                                                          "default: HMAP_REFINE_DEFAULT")


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None
    cloud_ok: bool | None = Field(default=None, description="applies to steps that start after the change")
    refine: bool | None = Field(default=None, description="check and improve results; applies to steps that start "
                                                          "after the change")


class RunIn(BaseModel):
    goal: str = Field(min_length=1, max_length=MAX_GOAL_CHARS)


class StopIn(BaseModel):
    reason: str = Field(default="stopped by user", min_length=1, max_length=500)


class ApprovalIn(BaseModel):
    approved: bool
    comment: str | None = Field(default=None, max_length=2000)
    graph_version: int | None = Field(default=None, ge=1,
                                      description="the plan version being decided; a replaced one gets 409")


class TaskIn(BaseModel):
    capability: str = Field(min_length=1)
    objective: str = Field(min_length=1, max_length=4000)
    acceptance_criteria: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class CancelIn(BaseModel):
    reason: str = Field(default="cancelled by user", min_length=1, max_length=500)


def _not_found(what: str = "Project") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


async def owned_project(project_id: str, info: CurrentSession, m: Manager) -> ProjectRecord:
    """The project if the signed-in user owns it; 404 otherwise (unknown, deleted or someone else's)."""
    try:
        project = await m.get_project_record(project_id)
    except UnknownProject:
        raise _not_found() from None
    if project.owner_id is None or project.owner_id != info.user.user_id:
        raise _not_found()
    return project


async def _owned_task(task_id: str, info: CurrentSession, m: Manager) -> dict[str, Any]:
    try:
        task = await m.get_task(task_id)
    except UnknownTask:
        raise _not_found("Task") from None
    try:
        await owned_project(task["project_id"], info, m)
    except HTTPException:
        raise _not_found("Task") from None
    return task


def _run_summaries(project: dict[str, Any], tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for run in project.get("runs", []):
        mine = [t for t in tasks if t.get("run", 1) == run["number"]]
        counts: dict[str, int] = {}
        for t in mine:
            counts[t["state"]] = counts.get(t["state"], 0) + 1
        out.append({**run, "task_count": len(mine), "task_states": counts})
    return out


async def _project_view(m: Manager, project_id: str) -> dict[str, Any]:
    project = await m.get_project(project_id)
    tasks = await m.list_tasks(project_id)
    project["runs"] = _run_summaries(project, tasks)
    project["last_activity_at"] = max([project["updated_at"], *(t["updated_at"] for t in tasks)])
    return project


# ============================================================================ projects


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, info: CurrentSession, m: ManagerDep, request: Request) -> dict[str, Any]:
    goal = body.goal.strip() if body.goal else None
    refine = body.refine if body.refine is not None else bool(getattr(request.app.state.settings, "refine_default",
                                                                      False))
    pid = await m.create_project(body.name.strip(), auto_approve=body.auto_approve, owner_id=info.user.user_id,
                                 description=goal, cloud_ok=body.cloud_ok, refine=refine)
    if goal:
        await _start_text_run(m, pid, goal)
    return await _project_view(m, pid)


async def _start_text_run(m: Manager, project_id: str, goal: str) -> None:
    """A typed request goes through the same pipeline as an uploaded document: it is stored as ``request.txt``."""
    run = await m.start_run(project_id, goal=goal, documents=["request.txt"])
    ref = await m.artifacts.put(goal.encode(), project_id=project_id, artifact_type="document",
                                media_type="text/plain", created_by="user")
    await m.record_run_documents(project_id, run, [ref.artifact_id])
    await m.emit(DomainEvent(event_type=EventType.DOCUMENT_UPLOADED.value, aggregate_id=project_id,
                             project_id=project_id, data={"artifact_refs": [ref.model_dump(mode="json")],
                                                          "filename": "request.txt", "source": "goal"}))


@router.get("/projects")
async def list_projects(info: CurrentSession, m: ManagerDep,
                        q: Annotated[str | None, Query(max_length=200, description="search name/description")] = None,
                        archived: bool = False) -> list[dict[str, Any]]:
    """The signed-in user's projects (never anyone else's). ``archived=true`` lists the archive instead."""
    out = []
    needle = q.strip().lower() if q else ""
    for p in await m.list_projects(owner_id=info.user.user_id):
        if p.get("archived", False) != archived:
            continue
        if needle and needle not in p["name"].lower() and needle not in (p.get("description") or "").lower():
            continue
        tasks = await m.list_tasks(p["project_id"])
        run = p["runs"][-1]["number"] if p.get("runs") else 1
        current = [t for t in tasks if t.get("run", 1) == run]
        counts: dict[str, int] = {}
        for t in current:
            counts[t["state"]] = counts.get(t["state"], 0) + 1
        out.append({**p, "current_run_task_states": counts,
                    "last_activity_at": max([p["updated_at"], *(t["updated_at"] for t in tasks)])})
    out.sort(key=lambda p: p["last_activity_at"], reverse=True)
    return out


@router.get("/projects/{project_id}")
async def get_project(project_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    return await _project_view(m, project_id)


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectPatch, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    await m.update_project(project_id, name=body.name.strip() if body.name else None, archived=body.archived,
                           cloud_ok=body.cloud_ok, refine=body.refine)
    return await _project_view(m, project_id)


@router.delete("/projects/{project_id}", status_code=status.HTTP_200_OK)
async def delete_project(project_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    """Stops running work, erases the project's files and removes it from the workspace (irreversible)."""
    await owned_project(project_id, info, m)
    erased = await m.delete_project(project_id)
    return {"deleted": True, "files_erased": erased}


@router.post("/projects/{project_id}/runs", status_code=status.HTTP_201_CREATED)
async def start_run(project_id: str, body: RunIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    """Run the project again with a (new) request; earlier runs stay in the history."""
    await owned_project(project_id, info, m)
    try:
        await _start_text_run(m, project_id, body.goal.strip())
    except InvalidProjectState as exc:
        raise _conflict(exc) from None
    return await _project_view(m, project_id)


@router.get("/projects/{project_id}/tasks")
async def list_tasks(project_id: str, info: CurrentSession, m: ManagerDep, run: int | None = None
                     ) -> list[dict[str, Any]]:
    await owned_project(project_id, info, m)
    tasks = await m.list_tasks(project_id)
    return [t for t in tasks if run is None or t.get("run", 1) == run]


def _document_path(raw: str) -> tuple[str, str | None]:
    """``"Assignment/Part A/brief.pdf"`` -> ``("brief.pdf", "Assignment/Part A")``. Every segment is made safe,
    empty, ``.`` and ``..`` segments are dropped (no path tricks), and at most three folder levels are kept."""
    parts = [SAFE_FILENAME.sub("_", p).strip()[:100] for p in raw.replace("\\", "/").split("/")]
    parts = [p for p in parts if p and p not in {".", ".."}]
    name = parts[-1][:200] if parts else "document"
    return name, "/".join(parts[:-1][-3:]) or None


def _media_type(upload: UploadFile, name: str) -> str | None:
    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared in ALLOWED_TYPES:
        return declared
    if declared in {"", "application/octet-stream"}:
        return EXTENSION_TYPES.get(name[name.rfind("."):].lower()) if "." in name else None
    return None


@router.post("/projects/{project_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    project_id: str, info: CurrentSession, m: ManagerDep,
    file: Annotated[UploadFile | None, File(description="one document: PDF, DOCX, text, Markdown or image")] = None,
    files: Annotated[list[UploadFile] | None, File(description=f"up to {MAX_DOCUMENTS} documents for one run")] = None,
    paths: Annotated[list[str] | None, Form(description="relative path of each of `files` in the same order, "
                                                        "e.g. 'Part A/brief.pdf', so folders are kept")] = None,
) -> dict[str, Any]:
    """Store the uploads as immutable artifacts and start ONE run with all of them (the pipeline begins with
    extraction). Each document keeps its folder, so later steps can treat folders as parts of the work. Everything
    is checked before anything is stored: one unusable file rejects the whole upload and no run starts."""
    await owned_project(project_id, info, m)
    if paths and len(paths) != len(files or []):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Send one path for each file.")
    named = [(file, file.filename or "document")] if file else []
    named += [(f, (paths[i] if paths else f.filename) or "document") for i, f in enumerate(files or [])]
    if not named:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Choose at least one document.")
    if len(named) > MAX_DOCUMENTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Upload at most {MAX_DOCUMENTS} documents at once.")

    docs: list[tuple[dict[str, Any], str, bytes]] = []
    total = 0
    for upload, raw in named:
        name, folder = _document_path(raw)
        path = f"{folder}/{name}" if folder else name
        media_type = _media_type(upload, name)
        if media_type is None:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                detail=f"“{path}” isn't a supported type. Use PDF, DOCX, text, Markdown, PNG or JPEG.")
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=f"“{path}” is larger than 25 MB.")
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"“{path}” is empty.")
        if not policy.content_matches(media_type, data):           # Sprint 6: the bytes must match the type
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                detail=f"“{path}” does not look like the file type its name says.")
        total += len(data)
        if total > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail="These documents add up to more than 100 MB.")
        docs.append(({"name": name, "folder": folder, "path": path}, media_type, data))

    try:
        run = await m.start_run(project_id, documents=[d["path"] for d, _, _ in docs])
    except InvalidProjectState as exc:
        raise _conflict(exc) from None
    refs: list[ArtifactRef] = []
    described: list[dict[str, Any]] = []
    for doc, media_type, data in docs:
        ref = await m.artifacts.put(data, project_id=project_id, artifact_type="document", media_type=media_type,
                                    created_by="user")
        refs.append(ref)
        described.append({"artifact_id": ref.artifact_id, **doc})
    await m.record_run_documents(project_id, run, [r.artifact_id for r in refs])
    first = described[0]["path"]
    await m.emit(DomainEvent(event_type=EventType.DOCUMENT_UPLOADED.value, aggregate_id=project_id,
                             project_id=project_id, data={"artifact_refs": [r.model_dump(mode="json") for r in refs],
                                                          "filename": first, "files": described, "run": run}))
    return {"artifact": refs[0].model_dump(mode="json"), "artifacts": [r.model_dump(mode="json") for r in refs],
            "filename": first, "documents": described, "run": run}


@router.post("/projects/{project_id}/plan", status_code=status.HTTP_202_ACCEPTED)
async def submit_plan(project_id: str, graph: TaskGraph, info: CurrentSession, m: ManagerDep,
                      require_approval: bool = True) -> dict[str, Any]:
    """Submit a TaskGraph directly (normally the pipeline does this after plan.generate)."""
    await owned_project(project_id, info, m)
    try:
        await m.submit_graph(project_id, graph.model_copy(update={"project_id": project_id}),
                             require_approval=require_approval)
    except (InvalidProjectState, ProjectStopped) as exc:
        raise _conflict(exc) from None
    return await _project_view(m, project_id)


@router.post("/projects/{project_id}/stop")
async def stop_project(project_id: str, info: CurrentSession, m: ManagerDep,
                       body: StopIn | None = None) -> dict[str, Any]:
    """The human's Stop button: cancel all unfinished tasks and close the run (409 if it already finished)."""
    await owned_project(project_id, info, m)
    try:
        cancelled = await m.stop_project(project_id, (body or StopIn()).reason)
    except InvalidProjectState as exc:
        raise _conflict(exc) from None
    return {"cancelled_tasks": cancelled, "project": await _project_view(m, project_id)}


@router.post("/projects/{project_id}/approval")
async def decide_approval(project_id: str, body: ApprovalIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    """Human-in-the-loop gate: approve or reject the submitted plan."""
    await owned_project(project_id, info, m)
    try:
        await m.approve(project_id, body.approved, body.comment, graph_version=body.graph_version)
    except InvalidProjectState as exc:
        raise _conflict(exc) from None
    return await _project_view(m, project_id)


@router.post("/projects/{project_id}/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(project_id: str, body: TaskIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    try:
        task_id = await m.create_task(project_id, body.capability, body.objective,
                                      acceptance_criteria=body.acceptance_criteria, inputs=body.inputs,
                                      depends_on=body.depends_on)
    except UnknownTask:
        raise _not_found("Dependency task") from None
    except ProjectStopped as exc:
        raise _conflict(exc) from None
    return await m.get_task(task_id)


# ============================================================================ tasks


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    return await _owned_task(task_id, info, m)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, body: CancelIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await _owned_task(task_id, info, m)
    cancelled = await m.cancel_task(task_id, body.reason)
    return {"cancelled": cancelled, "task": await m.get_task(task_id)}


# ============================================================================ artifacts (results and files)


@router.get("/projects/{project_id}/artifacts")
async def list_artifacts(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]:
    """Every stored file of the project, newest first, with the task (and run) that produced it; uploads carry
    the ``name`` they were uploaded as ("Part A/brief.pdf", or "request.txt" for a typed request)."""
    project = await owned_project(project_id, info, m)
    names = {aid: doc for run in project.runs for doc, aid in zip(run.documents, run.document_ids, strict=False)}
    produced: dict[tuple[str, int], dict[str, Any]] = {}
    for t in await m.list_tasks(project_id):
        for exe in await m.list_executions(t["task_id"]):
            for r in exe.get("result_refs") or []:
                produced[(r["artifact_id"], r["version"])] = {
                    "task_id": t["task_id"], "task_title": t.get("title") or t["objective"],
                    "capability": t["capability"], "run": t.get("run", 1), "agent_id": exe.get("agent_id")}
    refs = await m.artifacts.list(project_id)
    out = [{**r.model_dump(mode="json"), "produced_by": produced.get((r.artifact_id, r.version)),
            "name": names.get(r.artifact_id)} for r in refs]
    out.sort(key=lambda a: a["created_at"], reverse=True)
    return out


@router.get("/projects/{project_id}/artifacts/{artifact_id}")
async def download_artifact(project_id: str, artifact_id: str, info: CurrentSession, m: ManagerDep,
                            version: Annotated[int | None, Query(ge=1)] = None, download: bool = False) -> Response:
    """The file's bytes, SHA-256 verified. Owner only; never served as HTML (no script can run from a result)."""
    await owned_project(project_id, info, m)
    refs = [r for r in await m.artifacts.list(project_id) if r.artifact_id == artifact_id]
    ref: ArtifactRef | None = (max(refs, key=lambda r: r.version) if version is None
                               else next((r for r in refs if r.version == version), None))
    if ref is None:
        raise _not_found("File")
    try:
        data = await m.artifacts.get(ref, project_id=project_id)
    except ArtifactNotFound:
        raise _not_found("File") from None
    except ArtifactIntegrityError:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="This file failed its integrity check and was not sent.") from None
    media = ref.media_type if ref.media_type in INLINE_TYPES else "application/octet-stream"
    ext = {"application/json": ".json", "text/plain": ".txt", "text/markdown": ".md", "application/pdf": ".pdf",
           "image/png": ".png", "image/jpeg": ".jpg"}.get(ref.media_type, "")
    name = f"{ref.artifact_type}-{ref.artifact_id}-v{ref.version}{ext}"
    disposition = "attachment" if download or media == "application/octet-stream" else "inline"
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
        "Cache-Control": "private, no-store",
    })
