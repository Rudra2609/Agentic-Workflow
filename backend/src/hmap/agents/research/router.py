"""Research API (Sprint 5 item 5.13), mounted at ``/api/research``. Every project route checks ownership (404 for
anyone else's project, like the core API); ``POST`` needs the CSRF header (core middleware).

- ``GET  /runs/{project_id}``                       research steps of the project (newest first), summaries
- ``GET  /runs/{project_id}/{task_id}``             one step: the trace (rounds), the report, the brief
- ``GET  /pages/{project_id}/{artifact_id}``        a cited page's cleaned text (+ ``?task_id=`` the spans of that
                                                    step's evidence in it, for the evidence viewer)
- ``POST /runs/{project_id}``                       research a question now (an ad-hoc ``research.run`` task)
- ``GET  /providers``                               mode, providers, the offline corpus
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from hmap.agents.research import quotes
from hmap.agents.research.corpus import corpus_meta
from hmap.agents.research.model import BRIEF_TYPE, PAGE_TYPE, REPORT_TYPE, TRACE_TYPE
from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef
from hmap.core.contracts.capabilities import RESEARCH_RUN
from hmap.core.plugins import ProjectStopped

router = APIRouter()


class ResearchIn(BaseModel):
    questions: list[str] = Field(min_length=1, max_length=5)
    mode: str | None = Field(default=None, pattern=r"^(online|cached|local)$")
    max_rounds: int | None = Field(default=None, ge=1, le=6)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def _latest_by_id(refs: list[ArtifactRef], artifact_type: str) -> dict[str, ArtifactRef]:
    out: dict[str, ArtifactRef] = {}
    for r in refs:
        if r.artifact_type == artifact_type and (r.artifact_id not in out or r.version > out[r.artifact_id].version):
            out[r.artifact_id] = r
    return out


async def _load(m: Any, project_id: str, ref: ArtifactRef) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(await m.artifacts.get(ref, project_id=project_id))
    return data


async def _reports(m: Any, project_id: str, refs: list[ArtifactRef]) -> dict[str, tuple[ArtifactRef, dict[str, Any]]]:
    """task id -> (newest report ref, report) — a refined report is a newer version of the same artifact."""
    out: dict[str, tuple[ArtifactRef, dict[str, Any]]] = {}
    for ref in _latest_by_id(refs, REPORT_TYPE).values():
        body = await _load(m, project_id, ref)
        tid = str(body.get("task_id"))
        if tid not in out or (ref.created_at, ref.version) > (out[tid][0].created_at, out[tid][0].version):
            out[tid] = (ref, body)
    return out


def _summary(trace: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    subs = (report or {}).get("sub_questions") or []
    cov = [float(s.get("coverage", 0)) for s in subs]
    return {
        "task_id": trace.get("task_id"), "status": trace.get("status"), "mode": trace.get("mode"),
        "providers": trace.get("providers"), "rounds": len(trace.get("rounds") or []),
        "stop_reason": trace.get("stop_reason"), "tokens": trace.get("tokens"), "model_calls": trace.get("model_calls"),
        "seconds": trace.get("seconds"), "started_at": trace.get("started_at"), "finished_at": trace.get("finished_at"),
        "follow_up_of": trace.get("follow_up_of"),
        "questions": (report or {}).get("questions") or [],
        "claims": len((report or {}).get("claims") or []), "evidence": len((report or {}).get("evidence") or []),
        "sources": len((report or {}).get("sources") or []), "sub_questions": len(subs),
        "covered": sum(1 for s in subs if s.get("status") == "covered"),
        "coverage": round(sum(cov) / len(cov), 3) if cov else 0.0,
    }


@router.get("/providers")
async def providers(info: CurrentSession) -> dict[str, Any]:
    s = Settings.from_env()
    return {"mode": s.research_mode, "providers": list(s.research_providers), "corpus": corpus_meta()}


@router.get("/runs/{project_id}")
async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    reports = await _reports(m, project_id, refs)
    out = []
    for ref in _latest_by_id(refs, TRACE_TYPE).values():
        trace = await _load(m, project_id, ref)
        rep = reports.get(str(trace.get("task_id")))
        out.append(_summary(trace, rep[1] if rep else None))
    out.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return out


@router.get("/runs/{project_id}/{task_id}")
async def get_run(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    trace_ref = _latest_by_id(refs, TRACE_TYPE).get(f"rt-{task_id}")
    if trace_ref is None:
        raise _not_found("Research step")
    trace = await _load(m, project_id, trace_ref)
    rep = (await _reports(m, project_id, refs)).get(task_id)
    brief_ref = _latest_by_id(refs, BRIEF_TYPE).get(f"rb-{task_id}")
    return {"summary": _summary(trace, rep[1] if rep else None), "trace": trace,
            "report": rep[1] if rep else None,
            "report_artifact": rep[0].model_dump(mode="json") if rep else None,
            "brief": await _load(m, project_id, brief_ref) if brief_ref else None}


@router.get("/pages/{project_id}/{artifact_id}")
async def get_page(project_id: str, artifact_id: str, info: CurrentSession, m: ManagerDep,
                   task_id: str | None = Query(default=None, max_length=80)) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    ref = _latest_by_id(refs, PAGE_TYPE).get(artifact_id)
    if ref is None:
        raise _not_found("Page")
    page = await _load(m, project_id, ref)
    spans: list[dict[str, Any]] = []
    if task_id:
        rep = (await _reports(m, project_id, refs)).get(task_id)
        for e in (rep[1].get("evidence") or []) if rep else []:
            if e.get("url") == page.get("url") and (span := quotes.locate(str(e.get("quote", "")), page["text"])):
                spans.append({"evidence_id": e.get("id"), "start": span[0], "end": span[1]})
    return {"url": page.get("url"), "title": page.get("title"), "kind": page.get("kind"),
            "provider": page.get("provider"), "retrieved_at": page.get("retrieved_at"),
            "content_sha256": page.get("content_sha256"), "text": page.get("text", ""), "spans": spans,
            "injection_lines_removed": page.get("injection_lines_removed", 0), "license": page.get("license")}


@router.post("/runs/{project_id}", status_code=status.HTTP_202_ACCEPTED)
async def start_run(project_id: str, body: ResearchIn, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    """Research one or more questions now (an ad-hoc ``research.run`` task in this project)."""
    await owned_project(project_id, info, m)
    questions = [q.strip()[:300] for q in body.questions if q.strip()]
    if not questions:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Ask at least one question.")
    inputs: dict[str, Any] = {"research_questions": questions}
    if body.mode:
        inputs["research_mode"] = body.mode
    if body.max_rounds:
        inputs["budget"] = {"max_rounds": body.max_rounds}
    try:
        task_id = await m.create_task(project_id, RESEARCH_RUN, f"Research: {questions[0][:120]}", inputs=inputs,
                                      acceptance_criteria=["every claim cites verbatim evidence"])
    except ProjectStopped as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"task_id": task_id}
