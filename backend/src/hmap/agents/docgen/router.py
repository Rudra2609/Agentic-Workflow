"""Documentation API (Sprint 9 item 9.13, plan D18), mounted at ``/api/docgen``. Every route checks project
ownership (404 for anyone else's project); ``POST`` needs the CSRF header (core middleware).

- ``GET  /bundles/{project_id}``                         docs runs of the project (newest first)
- ``GET  /bundles/{project_id}/{task_id}``               one run: documents, accuracy (every claim), trace, graph
- ``GET  /bundles/{project_id}/{task_id}/files/{name}``  one document as Markdown (readme/api/architecture/...)
- ``POST /bundles/{project_id}/{task_id}/regenerate``    a new ``docs.generate`` with the same inputs
- ``GET  /bundles/{project_id}/{task_id}/architecture.svg``   the architecture as SVG (stretch)
- ``GET  /bundles/{project_id}/{task_id}/site.html``    every document on one static HTML page (stretch)
- ``GET  /bundles/{project_id}/{task_id}/docstrings.diff``  suggested docstrings as a patch, never applied (stretch)
- ``POST /check/{project_id}``                           paste Markdown -> grounding report against the latest facts
                                                         (the demo's "inject a false claim" step); rules only
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from hmap.agents.docgen import architecture, export
from hmap.agents.docgen.grounding import rule_claims, summarize
from hmap.agents.docgen.model import (
    ACCURACY_TYPE,
    BUNDLE_TYPE,
    DOC_FILES,
    DOCSTRINGS_TYPE,
    FACTS_TYPE,
    TRACE_TYPE,
    Facts,
    accuracy_id,
    bundle_id,
    doc_id,
    docstrings_id,
    facts_id,
    trace_id,
)
from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.capabilities import DOCS_GENERATE, DOCS_UPDATE
from hmap.core.plugins import ProjectStopped

router = APIRouter()
MAX_CHECK_CHARS = 100_000


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def _latest(refs: list[ArtifactRef], artifact_type: str) -> dict[str, ArtifactRef]:
    out: dict[str, ArtifactRef] = {}
    for r in refs:
        if r.artifact_type == artifact_type and (r.artifact_id not in out or r.version > out[r.artifact_id].version):
            out[r.artifact_id] = r
    return out


async def _json(m: Any, project_id: str, ref: ArtifactRef) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(await m.artifacts.get(ref, project_id=project_id))
    return data


def summary(trace: dict[str, Any], acc: dict[str, Any] | None) -> dict[str, Any]:
    acc = acc or {}
    return {"task_id": trace.get("task_id"), "capability": trace.get("capability"), "status": trace.get("status"),
            "mode": trace.get("mode"), "step": trace.get("step"), "documents": trace.get("documents") or [],
            "grounded_pct": acc.get("grounded_pct"), "checked": acc.get("checked", 0),
            "ungrounded": acc.get("ungrounded", 0), "removed": len(acc.get("removed") or []),
            "unverified": acc.get("unverified", 0), "coverage_pct": acc.get("coverage_pct"),
            "examples_run": sum(1 for e in acc.get("examples") or [] if e.get("ok") is not None),
            "examples_failed": sum(1 for e in acc.get("examples") or [] if e.get("ok") is False),
            "degraded": trace.get("degraded", False), "rounds": trace.get("rounds", 0),
            "model_calls": trace.get("model_calls", 0), "seconds": trace.get("seconds"),
            "source": trace.get("source")}


@router.get("/bundles/{project_id}")
async def list_bundles(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    accs = _latest(refs, ACCURACY_TYPE)
    out = []
    for ref in _latest(refs, TRACE_TYPE).values():
        trace = await _json(m, project_id, ref)
        acc_ref = accs.get(accuracy_id(str(trace.get("task_id"))))
        acc = await _json(m, project_id, acc_ref) if acc_ref else None
        out.append(summary(trace, acc) | {"updated_at": ref.created_at.isoformat()})
    out.sort(key=lambda r: r["updated_at"], reverse=True)
    return out


async def _doc_text(m: Any, project_id: str, refs: list[ArtifactRef], name: str, task_id: str) -> str | None:
    artifact_type, _ = DOC_FILES[name]
    ref = _latest(refs, artifact_type).get(doc_id(name, task_id))
    if ref is None:
        return None
    text = (await m.artifacts.get(ref, project_id=project_id)).decode("utf-8", "replace")
    if name == "summaries":
        try:
            return str(json.loads(text)["markdown"])
        except (ValueError, KeyError):
            return str(text)
    return str(text)


@router.get("/bundles/{project_id}/{task_id}")
async def get_bundle(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    tr = _latest(refs, TRACE_TYPE).get(trace_id(task_id))
    if tr is None:
        raise _not_found("Documentation run")
    trace = await _json(m, project_id, tr)
    acc_ref = _latest(refs, ACCURACY_TYPE).get(accuracy_id(task_id))
    acc = await _json(m, project_id, acc_ref) if acc_ref else None
    b_ref = _latest(refs, BUNDLE_TYPE).get(bundle_id(task_id))
    docs = {}
    for name in trace.get("documents") or []:
        if name in DOC_FILES and (text := await _doc_text(m, project_id, refs, name, task_id)) is not None:
            docs[name] = text
    graph = None
    f_ref = _latest(refs, FACTS_TYPE).get(facts_id(task_id))
    if f_ref is not None:
        facts = Facts.model_validate_json(await m.artifacts.get(f_ref, project_id=project_id))
        graph = architecture.extract(facts).graph()
    return {"summary": summary(trace, acc) | {"updated_at": tr.created_at.isoformat()}, "trace": trace,
            "accuracy": acc, "bundle": await _json(m, project_id, b_ref) if b_ref else None,
            "bundle_artifact": b_ref.model_dump(mode="json") if b_ref else None, "documents": docs, "graph": graph}


@router.get("/bundles/{project_id}/{task_id}/files/{name}", response_class=PlainTextResponse)
async def get_file(project_id: str, task_id: str, name: str, info: CurrentSession, m: ManagerDep) -> str:
    await owned_project(project_id, info, m)
    if name not in DOC_FILES:
        raise _not_found("Document")
    text = await _doc_text(m, project_id, await m.artifacts.list(project_id), name, task_id)
    if text is None:
        raise _not_found("Document")
    return text


@router.post("/bundles/{project_id}/{task_id}/regenerate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    try:
        task = await m.get_task(task_id)
    except Exception as exc:
        raise _not_found("Documentation run") from exc
    if task.get("project_id") != project_id or task.get("capability") not in (DOCS_GENERATE, DOCS_UPDATE):
        raise _not_found("Documentation run")
    if task.get("state") not in ("COMPLETED", "FAILED", "DEAD_LETTERED", "CANCELLED"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This documentation run is still going.")
    try:
        new_id = await m.create_task(
            project_id, DOCS_GENERATE, f"Regenerate: {str(task.get('objective'))[:180]}",
            acceptance_criteria=list(task.get("acceptance_criteria") or [])[:20],
            inputs={k: v for k, v in (task.get("inputs") or {}).items() if k != "previous_bundle"},
            artifact_refs=[ArtifactRef.model_validate(r) for r in task.get("artifact_refs") or []],
            parent_task_id=task_id)
    except ProjectStopped as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"task_id": new_id, "regenerated_from": task_id}


async def _facts(m: Any, project_id: str, refs: list[ArtifactRef], task_id: str) -> Facts | None:
    ref = _latest(refs, FACTS_TYPE).get(facts_id(task_id))
    return Facts.model_validate_json(await m.artifacts.get(ref, project_id=project_id)) if ref else None


@router.get("/bundles/{project_id}/{task_id}/architecture.svg")
async def architecture_svg(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> Response:
    await owned_project(project_id, info, m)
    facts = await _facts(m, project_id, await m.artifacts.list(project_id), task_id)
    if facts is None:
        raise _not_found("Architecture")
    body = export.svg(architecture.extract(facts).graph(), f"Architecture: {facts.repo}")
    return Response(body, media_type="image/svg+xml", headers={
        "Content-Disposition": f'attachment; filename="{facts.repo}-architecture.svg"'})


@router.get("/bundles/{project_id}/{task_id}/site.html")
async def site_html(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> Response:
    """Every document on one static page (docs-as-site); served as a download with a strict CSP."""
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    docs = {n: t for n in DOC_FILES if (t := await _doc_text(m, project_id, refs, n, task_id)) is not None}
    if not docs:
        raise _not_found("Documentation")
    facts = await _facts(m, project_id, refs, task_id)
    graph = export.svg(architecture.extract(facts).graph()) if facts else None
    name = facts.repo if facts else task_id
    return Response(export.site(docs, f"Documentation: {name}", graph), media_type="text/html", headers={
        "Content-Disposition": f'attachment; filename="{name}-docs.html"',
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@router.get("/bundles/{project_id}/{task_id}/docstrings.diff", response_class=PlainTextResponse)
async def docstrings(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> str:
    """The suggested docstrings as a patch (``git apply``); the agent never applies it."""
    await owned_project(project_id, info, m)
    ref = _latest(await m.artifacts.list(project_id), DOCSTRINGS_TYPE).get(docstrings_id(task_id))
    if ref is None:
        raise _not_found("Docstring patch")
    return str((await m.artifacts.get(ref, project_id=project_id)).decode("utf-8", "replace"))


class CheckIn(BaseModel):
    markdown: str = Field(min_length=1, max_length=MAX_CHECK_CHARS)
    task_id: str | None = Field(default=None, max_length=200)


@router.post("/check/{project_id}")
async def check(project_id: str, body: CheckIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    facts_refs = _latest(await m.artifacts.list(project_id), FACTS_TYPE)
    ref = facts_refs.get(facts_id(body.task_id)) if body.task_id else \
        max(facts_refs.values(), key=lambda r: r.created_at, default=None)
    if ref is None:
        raise _not_found("Facts of this project (generate documentation first)")
    facts = Facts.model_validate_json(await m.artifacts.get(ref, project_id=project_id))
    acc = summarize(rule_claims(body.markdown, facts, "pasted"))
    return {"facts_of": ref.artifact_id, "accuracy": acc.model_dump(mode="json")}
