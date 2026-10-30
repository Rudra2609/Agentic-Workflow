"""Verify API (Sprint 6 item 6.11), mounted at ``/api/verify``. Every project route checks ownership (404 for anyone
else's project, like the core API); ``POST`` needs the CSRF header (core middleware).

- ``GET  /runs/{project_id}``                        verification steps of the project (newest first), summaries
- ``GET  /runs/{project_id}/{task_id}``              one step: per-claim verdicts + every layer's result, the
                                                     checked claims with their quotes (the page viewer is Member 5's
                                                     ``/api/research/pages``), follow-up steps it started
- ``POST /runs/{project_id}/{task_id}/follow-up``    "request more research": follow-up research on the chosen
                                                     (default: the flagged) claims + a re-check
- ``GET  /table``                                    the decision table (rows, verdicts, confidence)
- ``GET  /security``                                 the platform's message policy table + the latest audited
                                                     refusals (Sprint 6 security layer, ``hmap.core.policy``)
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from hmap.agents.verify import aggregate
from hmap.agents.verify.hooks import HARD_MAX_ROUNDS, request_follow_up
from hmap.agents.verify.model import REPORT_TYPE, RESEARCH_REPORT_TYPE, TRACE_TYPE
from hmap.api.deps import CurrentSession
from hmap.api.routers.projects import ManagerDep, owned_project
from hmap.core.contracts import ArtifactRef, VerificationReport
from hmap.core.plugins import ProjectStopped

router = APIRouter()


class FollowUpIn(BaseModel):
    claim_ids: list[str] = Field(default_factory=list, max_length=20)
    questions: list[str] = Field(default_factory=list, max_length=5)


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


def _summary(trace: dict[str, Any]) -> dict[str, Any]:
    counts = {"VERIFIED": 0, "UNSUPPORTED": 0, "CONFLICTING": 0, "NEEDS_MORE_RESEARCH": 0}
    for c in trace.get("claims") or []:
        counts[c.get("verdict", "NEEDS_MORE_RESEARCH")] = counts.get(c.get("verdict", "NEEDS_MORE_RESEARCH"), 0) + 1
    return {"task_id": trace.get("task_id"), "status": trace.get("status"), "round": trace.get("round", 0),
            "research_task_id": trace.get("research_task_id"), "layers": trace.get("layers"),
            "claims": len(trace.get("claims") or []), "verified": counts["VERIFIED"],
            "unsupported": counts["UNSUPPORTED"], "conflicting": counts["CONFLICTING"],
            "needs_more": counts["NEEDS_MORE_RESEARCH"], "model_calls": trace.get("model_calls"),
            "tokens": trace.get("tokens"), "seconds": trace.get("seconds"), "started_at": trace.get("started_at"),
            "finished_at": trace.get("finished_at"), "follow_up_questions": trace.get("follow_up_questions") or [],
            "follow_up_of": trace.get("follow_up_of"), "notes": trace.get("notes") or []}


@router.get("/table")
async def decision_table(info: CurrentSession) -> list[dict[str, Any]]:
    return [{"row": r.id, "verdict": r.verdict, "why": r.why, "confidence": aggregate.CONFIDENCE[r.id]}
            for r in aggregate.TABLE]


@router.get("/security")
async def security(info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    """Platform-wide (like the agents page): what agents may send, and what was refused recently. No secrets: key
    ids and fingerprints only."""
    from hmap.core import policy

    pol = getattr(m, "policy", None)
    sinks = list(getattr(pol, "audit_sinks", [policy.AUDIT]))
    entries = await sinks[-1].recent(50)
    ring = policy.signer().keyring
    return {"enforced": bool(getattr(pol, "enforce", True)), "table": policy.POLICY_TABLE,
            "keys": [{"kid": kid, "fingerprint": policy.fingerprint(secret)} for kid, secret in ring.keys],
            "keyring": "environment" if ring.path is None else "local dev keyring",
            "revoked": sorted(ring.revoked),
            "refused": [e.as_dict() for e in entries if e.decision == "deny"],
            "registrations": sum(1 for e in entries if e.message_type == "agent.register")}


@router.get("/runs/{project_id}")
async def list_runs(project_id: str, info: CurrentSession, m: ManagerDep) -> list[dict[str, Any]]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    out = [_summary(await _load(m, project_id, ref)) for ref in _latest_by_id(refs, TRACE_TYPE).values()]
    out.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return out


async def _children(m: Any, project_id: str, task_id: str) -> list[dict[str, Any]]:
    try:
        tasks = await m.list_tasks(project_id)
    except Exception:
        return []
    out = []
    for t in tasks:
        t = t if isinstance(t, dict) else t.to_dict()
        if t.get("parent_task_id") == task_id:
            out.append({"task_id": t.get("task_id"), "capability": t.get("capability"), "state": t.get("state"),
                        "objective": t.get("objective")})
    return out


@router.get("/runs/{project_id}/{task_id}")
async def get_run(project_id: str, task_id: str, info: CurrentSession, m: ManagerDep) -> dict[str, Any]:
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    trace_ref = _latest_by_id(refs, TRACE_TYPE).get(f"vt-{task_id}")
    if trace_ref is None:
        raise _not_found("Verification step")
    trace = await _load(m, project_id, trace_ref)
    report_ref = _latest_by_id(refs, REPORT_TYPE).get(f"vr-{task_id}")
    research: dict[str, Any] | None = None
    rr = trace.get("research_report")
    if isinstance(rr, dict):
        try:
            research = await _load(m, project_id, ArtifactRef.model_validate(rr))
        except Exception:
            research = None
    evidence = {e["id"]: e for e in (research or {}).get("evidence") or []}
    sources = {s["url"]: s for s in (research or {}).get("sources") or []}
    for c in trace.get("claims") or []:
        c["evidence"] = [{**evidence[eid], "title": sources.get(evidence[eid]["url"], {}).get("title", "")}
                         for eid in c.get("evidence_ids") or [] if eid in evidence]
    return {"summary": _summary(trace), "trace": trace,
            "report": await _load(m, project_id, report_ref) if report_ref else None,
            "report_artifact": report_ref.model_dump(mode="json") if report_ref else None,
            "research_questions": (research or {}).get("questions") or [],
            "follow_ups": await _children(m, project_id, task_id)}


@router.post("/runs/{project_id}/{task_id}/follow-up", status_code=status.HTTP_202_ACCEPTED)
async def follow_up(project_id: str, task_id: str, body: FollowUpIn, info: CurrentSession,
                    m: ManagerDep) -> dict[str, Any]:
    """A human asks for more research: on the chosen claims (default: what the check flagged) + a re-check."""
    await owned_project(project_id, info, m)
    refs = await m.artifacts.list(project_id)
    report_ref = _latest_by_id(refs, REPORT_TYPE).get(f"vr-{task_id}")
    trace_ref = _latest_by_id(refs, TRACE_TYPE).get(f"vt-{task_id}")
    if report_ref is None or trace_ref is None:
        raise _not_found("Verification step")
    report = VerificationReport.model_validate_json(await m.artifacts.get(report_ref, project_id=project_id))
    if report.research_report_ref is None or report.research_report_ref.artifact_type != RESEARCH_REPORT_TYPE:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This step had no research report to follow up.")
    trace = await _load(m, project_id, trace_ref)
    questions = [q.strip()[:300] for q in body.questions if q.strip()]
    if body.claim_ids and not questions:
        chosen = [c for c in trace.get("claims") or [] if c.get("claim_id") in set(body.claim_ids)]
        questions = [f"Is it true that {c['text'].strip().rstrip('.')}?" for c in chosen]
    round_ = int(trace.get("round") or 0)
    try:
        created = await request_follow_up(m, project_id, task_id, report, report_ref, round_,
                                          max_rounds=HARD_MAX_ROUNDS, questions=questions or None)
    except ProjectStopped as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if created is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"Nothing to research, or the limit of {HARD_MAX_ROUNDS} follow-up rounds is "
                                   "reached.")
    return created
