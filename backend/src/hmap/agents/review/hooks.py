"""Manager hook of the review agent (Sprint 10, plan D8): ``task.completed`` of ``review.final`` ->
``review.completed {project_id, task_id, report_ref, outcome PASS/REVISE/ESCALATE, round, stop_reason}`` (spec §7:
Member 11 and the dashboards listen to it). Only real reports count: the step must have a ``review-trace`` (the stub
never writes one). The recovery itself runs in the ``recovery`` slot when the run settles, not here."""

from typing import Any

from hmap.agents.review.model import REPORT_TYPE, TRACE_TYPE, ReviewTrace
from hmap.core.contracts import ArtifactRef, DomainEvent, ReviewReport
from hmap.core.contracts.capabilities import REVIEW_FINAL
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle, hook


def _refs(raw: Any) -> list[ArtifactRef]:
    return [r if isinstance(r, ArtifactRef) else ArtifactRef.model_validate(r) for r in raw or []
            if isinstance(r, dict | ArtifactRef)]


@hook("task.completed", capability=REVIEW_FINAL)
async def on_review_done(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    project_id = str(task["project_id"])
    refs = _refs(event.data.get("artifact_refs"))
    if not refs:
        for exe in task.get("executions", []):
            if exe.get("status") == "SUCCEEDED":
                refs = _refs(exe.get("result_refs"))
    tr = next((r for r in refs if r.artifact_type == TRACE_TYPE), None)
    rep = next((r for r in refs if r.artifact_type == REPORT_TYPE), None)
    if tr is None or rep is None:
        return
    trace = ReviewTrace.model_validate_json(await manager.artifacts.get(tr, project_id=project_id))
    report = ReviewReport.model_validate_json(await manager.artifacts.get(rep, project_id=project_id))
    await manager.emit(DomainEvent(
        event_type=EventType.REVIEW_COMPLETED.value, aggregate_id=event.aggregate_id, project_id=project_id,
        correlation_id=event.correlation_id,
        data={"project_id": project_id, "task_id": event.aggregate_id, "report_ref": rep.model_dump(mode="json"),
              "outcome": report.recommendation, "round": trace.round, "completeness": trace.completeness,
              "failures": len(report.failures), "stop_reason": trace.stop_reason}))
