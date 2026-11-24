"""Review API (Sprint 10 item 10.9, plan D12), mounted at ``/api/review``. Every route checks project ownership (404
for anyone else's project); ``POST`` needs the CSRF header (core middleware).

- ``GET  /reports/{project_id}``                         review rounds of the current run + the recovery timeline
- ``GET  /reports/{project_id}/{task_id}``               one review: report, every item with its evidence and how it
                                                         was decided, trace, a person's decisions
- ``POST /reports/{project_id}/{task_id}/override``      a person's verdict for one item (+ note); the report gets a
                                                         new version; overrides are kept as calibration labels
- ``POST /reports/{project_id}/{task_id}/accept``        accept with notes: the project completes
- ``POST /reports/{project_id}/{task_id}/request-changes``  text (+ optional step) -> a revision of that step, or a
                                                         replan through Member 3's ``plan.replan``
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from hmap.agents.review.aggregate import blocking, completeness
from hmap.agents.review.model import (
    DECISION_TYPE,
    EVIDENCE_TYPE,
    REPORT_TYPE,
    Decided,
    decision_id,
    evidence_id,
    report_id,
    trace_id,
)
from hmap.agents.review.recovery import ReviewRecovery
from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.contracts import DomainEvent, ReviewReport
from hmap.core.contracts.capabilities import REVIEW_FINAL
from hmap.core.contracts.domain import RevisionPlan
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ProjectStopped

router = APIRouter()


class OverrideIn(BaseModel):
    item_id: str = Field(min_length=1, max_length=40)
    verdict: Literal["PASS", "PARTIAL", "FAIL"]
    note: str = Field(default="", max_length=2000)


class AcceptIn(BaseModel):
    notes: str = Field(default="", max_length=4000)


class ChangesIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    task_id: str | None = Field(default=None, max_length=80, description="revise this step; none: replan")


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


async def _json(m: Any, project_id: str, artifact_id: str) -> dict[str, Any] | None:
    ref = await m.artifacts.latest(artifact_id, project_id=project_id)
    if ref is None:
        return None
    try:
        data: dict[str, Any] = json.loads(await m.artifacts.get(ref, project_id=project_id))
        return data
    except Exception:
        return None


def _recovery(m: Any) -> ReviewRecovery:
    r = getattr(m, "recovery", None)
    return r if isinstance(r, ReviewRecovery) else ReviewRecovery()


async def _reviews(m: Any, project_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    project = await m.get_project(project_id)
    run = project.get("current_run", 1)
    tasks = sorted((t for t in await m.list_tasks(project_id) if t.get("run", 1) == run),
                   key=lambda t: str(t.get("created_at")))
    return project, tasks, [t for t in tasks if t["capability"] == REVIEW_FINAL and not t.get("replaced")]


async def _review_task(m: Any, project_id: str, task_id: str) -> dict[str, Any]:
    _, _tasks, reviews = await _reviews(m, project_id)
    hit = next((t for t in reviews if t["task_id"] == task_id), None)
    if hit is None:
        raise _not_found("Review")
    return hit


@router.get("/reports/{project_id}")
async def list_reports(project_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    project, tasks, reviews = await _reviews(m, project_id)
    rounds = []
    for r in reviews:
        trace = await _json(m, project_id, trace_id(r["task_id"])) or {}
        report = await _json(m, project_id, report_id(r["task_id"])) or {}
        made = [{"task_id": t["task_id"], "capability": t["capability"], "title": t.get("title") or t.get("objective"),
                 "state": t["state"], "action": ((t.get("inputs") or {}).get("recovery") or {}).get("action"),
                 "parent_task_id": t.get("parent_task_id")}
                for t in tasks if isinstance((t.get("inputs") or {}).get("recovery"), dict)
                and t["inputs"]["recovery"].get("review_task_id") == r["task_id"]]
        decision = await _json(m, project_id, decision_id(r["task_id"]))
        rounds.append({"task_id": r["task_id"], "state": r["state"], "created_at": r.get("created_at"),
                       "round": trace.get("round", (r.get("inputs") or {}).get("review_round", 0)),
                       "recommendation": report.get("recommendation"), "completeness": trace.get("completeness"),
                       "failures": len(report.get("failures") or []), "stop_reason": trace.get("stop_reason"),
                       "plan": trace.get("plan") or {}, "created_tasks": made,
                       "stale_of": (r.get("inputs") or {}).get("stale_of"), "decision": decision})
    return {"project_id": project_id, "project_state": project.get("state"), "rounds": rounds}


@router.get("/reports/{project_id}/{task_id}")
async def get_report(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    await _review_task(m, project_id, task_id)
    report = await _json(m, project_id, report_id(task_id))
    if report is None:
        raise _not_found("Report")
    evidence = await _json(m, project_id, evidence_id(task_id)) or {}
    project = await m.get_project(project_id)
    return {"report": report, "items": evidence.get("items") or [], "mode": evidence.get("mode"),
            "notes": evidence.get("notes") or [], "tasks": evidence.get("tasks") or [],
            "trace": await _json(m, project_id, trace_id(task_id)) or {},
            "decision": await _json(m, project_id, decision_id(task_id)), "project_state": project.get("state")}


async def _save_decision(m: Any, project_id: str, task_id: str, user: str, change: dict[str, Any]) -> dict[str, Any]:
    old = await _json(m, project_id, decision_id(task_id)) or {"overrides": {}, "history": []}
    now = datetime.now(UTC).isoformat()
    new = {**old, **{k: v for k, v in change.items() if k != "override"}}
    if "override" in change:
        new["overrides"] = {**(old.get("overrides") or {}), change["override"]["item_id"]: change["override"]}
    new["history"] = [*(old.get("history") or []), {**change, "by": user, "at": now}][-50:]
    await m.artifacts.put(json.dumps(new, indent=2).encode(), project_id=project_id, artifact_type=DECISION_TYPE,
                          media_type="application/json", created_by=f"user:{user}", artifact_id=decision_id(task_id))
    return new


@router.post("/reports/{project_id}/{task_id}/override")
async def override(project_id: str, task_id: str, body: OverrideIn, info: CurrentSession,
                   m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    await _review_task(m, project_id, task_id)
    raw = await _json(m, project_id, report_id(task_id))
    evidence = await _json(m, project_id, evidence_id(task_id)) or {}
    if raw is None:
        raise _not_found("Report")
    decided = [Decided.model_validate(d) for d in evidence.get("items") or []]
    if body.item_id not in {d.item.id for d in decided}:
        raise _not_found("Item")
    decision = await _save_decision(m, project_id, task_id, info.user.user_id,
                                    {"override": body.model_dump()})
    for d in decided:
        o = (decision.get("overrides") or {}).get(d.item.id)
        if o:
            d.verdict, d.source, d.rationale = o["verdict"], "human", f"set by a person: {o.get('note') or ''}"
    report = ReviewReport.model_validate(raw)
    still = {d.item.id for d in blocking(decided)}
    by_id = {d.item.id: d for d in decided}
    results = [r.model_copy(update={"verdict": by_id[r.req_id].verdict, "rationale": by_id[r.req_id].rationale})
               if r.req_id in by_id else r for r in report.requirement_results]
    failures = [f for f in report.failures if f.requirement_id in still]
    plans = [p for p in report.revision_requests
             if any(c.split(" ")[0] in still for c in p.required_changes) or (p.action == "replan" and still)]
    rec = "PASS" if not still else report.recommendation
    new = report.model_copy(update={"requirement_results": results, "failures": failures, "revision_requests": plans,
                                    "overall": completeness(decided), "recommendation": rec})
    await m.artifacts.put(new.model_dump_json(indent=2).encode(), project_id=project_id, artifact_type=REPORT_TYPE,
                          media_type="application/json", created_by=f"user:{info.user.user_id}",
                          artifact_id=report_id(task_id))
    evidence["items"] = [d.model_dump(mode="json") for d in decided]
    await m.artifacts.put(json.dumps(evidence, indent=2).encode(), project_id=project_id, artifact_type=EVIDENCE_TYPE,
                          media_type="application/json", created_by=f"user:{info.user.user_id}",
                          artifact_id=evidence_id(task_id))
    if rec == "PASS":
        await m.resume_review(project_id)
    return {"report": new.model_dump(mode="json"), "decision": decision}


@router.post("/reports/{project_id}/{task_id}/accept")
async def accept(project_id: str, task_id: str, body: AcceptIn, info: CurrentSession,
                 m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    await _review_task(m, project_id, task_id)
    decision = await _save_decision(m, project_id, task_id, info.user.user_id,
                                    {"accepted": True, "notes": body.notes})
    ref = await m.artifacts.latest(report_id(task_id), project_id=project_id)
    await m.emit(DomainEvent(
        event_type=EventType.REVIEW_COMPLETED.value, aggregate_id=task_id, project_id=project_id,
        correlation_id=project_id,
        data={"project_id": project_id, "task_id": task_id, "outcome": "PASS", "accepted_by_human": True,
              "notes": body.notes[:500], "report_ref": ref.model_dump(mode="json") if ref else None}))
    await m.resume_review(project_id)
    return {"decision": decision, "project_state": (await m.get_project(project_id)).get("state")}


@router.post("/reports/{project_id}/{task_id}/request-changes", status_code=status.HTTP_202_ACCEPTED)
async def request_changes(project_id: str, task_id: str, body: ChangesIn, info: CurrentSession,
                          m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    last = await _review_task(m, project_id, task_id)
    _, tasks, _ = await _reviews(m, project_id)
    rec = _recovery(m)
    report, round_ = await rec._report(project_id, task_id, m)
    text = body.text.strip()
    if body.task_id is not None and body.task_id not in {t["task_id"] for t in tasks}:
        raise _not_found("Step")
    plan = RevisionPlan(task_id=body.task_id or task_id, action="revise" if body.task_id else "replan",
                        required_changes=[f"requested by a person: {text}"])
    try:
        made = await rec.execute(project_id, last, report, round_, m, tasks, plans=[plan])
    except ProjectStopped as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    decision = await _save_decision(m, project_id, task_id, info.user.user_id,
                                    {"request_changes": text, "step": body.task_id, "created": made})
    if not made:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Nothing could be created for this request (no plan or "
                                                             "requirements to replan from).")
    return {"created": made, "decision": decision}
