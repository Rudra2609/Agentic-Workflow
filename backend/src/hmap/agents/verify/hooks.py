"""Manager hooks of the verifier (Sprint 6 items 6.7 / 6.8).

``task.completed`` of a ``verify.claims`` step:

1. emits ``verification.completed {task_id, report_ref, research_report_ref, summary, round, follow_up}`` (spec §7);
2. **feedback loop:** when claims were flagged (follow-up questions exist), the step had a research report and the
   round is below ``HMAP_VERIFY_MAX_ROUNDS`` (default 1), it creates
   - a ``research.run`` task with ``inputs={"follow_up_of": <research report>, "research_questions": <gaps>}``
     (Member 5's follow-up mode: keeps the earlier evidence, researches only the gaps), and
   - a ``verify.claims`` task that depends on it (``verify_round`` + 1) — the re-check.
   Both are children (``parent_task_id``) of the verify step. The plan's later steps are not held back (they
   already depend on the first check); the re-check's verdicts are the newest for anyone reading them.

The loop always terminates: the round is carried in the task inputs and capped (also when a human asks for more
research from the Verify tab: :data:`HARD_MAX_ROUNDS`).
"""

import json
from typing import Any

from hmap.agents.verify.model import REPORT_TYPE
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, DomainEvent, VerificationReport
from hmap.core.contracts.capabilities import RESEARCH_RUN, VERIFY_CLAIMS
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle, hook
from hmap.core.tracing import get_logger

log = get_logger("hmap.verify.hooks")
HARD_MAX_ROUNDS = 3


def _refs(raw: Any) -> list[ArtifactRef]:
    return [r if isinstance(r, ArtifactRef) else ArtifactRef.model_validate(r) for r in raw or []
            if isinstance(r, (dict, ArtifactRef))]


async def result_refs(manager: ManagerHandle, task: dict[str, Any]) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for exe in task.get("executions", []):
        if exe.get("status") == "SUCCEEDED":
            refs = _refs(exe.get("result_refs"))
    return refs


async def request_follow_up(manager: ManagerHandle, project_id: str, verify_task_id: str, report: VerificationReport,
                            report_ref: ArtifactRef, round_: int, *, max_rounds: int,
                            questions: list[str] | None = None) -> dict[str, str] | None:
    """Create follow-up research + a re-check; ``None`` when there is nothing to do or the round cap is reached."""
    questions = [q.strip()[:300] for q in (questions or report.follow_up_questions) if q.strip()][:5]
    if not questions or report.research_report_ref is None or round_ >= min(max_rounds, HARD_MAX_ROUNDS):
        return None
    research_id = await manager.create_task(
        project_id, RESEARCH_RUN, f"Follow-up research: {questions[0][:110]}",
        inputs={"follow_up_of": report.research_report_ref.model_dump(mode="json"), "research_questions": questions,
                "verify_round": round_ + 1},
        acceptance_criteria=["every claim cites verbatim evidence"], parent_task_id=verify_task_id)
    verify_id = await manager.create_task(
        project_id, VERIFY_CLAIMS, "Re-check the research findings after the follow-up research",
        inputs={"verify_round": round_ + 1, "follow_up_of_verification": report_ref.model_dump(mode="json")},
        depends_on=[research_id], parent_task_id=verify_task_id,
        acceptance_criteria=["every claim is checked against its quoted evidence"])
    log.info("follow-up research requested", verify_task=verify_task_id, research_task=research_id,
             recheck=verify_id, round=round_ + 1, questions=len(questions))
    return {"research_task_id": research_id, "verify_task_id": verify_id}


@hook("task.completed", capability=VERIFY_CLAIMS)
async def on_verified(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    project_id = str(task["project_id"])
    refs = _refs(event.data.get("artifact_refs")) or await result_refs(manager, task)
    ref = next((r for r in refs if r.artifact_type == REPORT_TYPE), None)
    if ref is None:
        return
    report = VerificationReport.model_validate_json(await manager.artifacts.get(ref, project_id=project_id))
    round_ = int((task.get("inputs") or {}).get("verify_round") or 0)
    follow = await request_follow_up(manager, project_id, event.aggregate_id, report, ref, round_,
                                     max_rounds=Settings.from_env().verify_max_rounds)
    await manager.emit(DomainEvent(
        event_type=EventType.VERIFICATION_COMPLETED.value, aggregate_id=event.aggregate_id, project_id=project_id,
        correlation_id=event.correlation_id,
        data={"task_id": event.aggregate_id, "report_ref": ref.model_dump(mode="json"),
              "research_report_ref": (report.research_report_ref.model_dump(mode="json")
                                      if report.research_report_ref else None),
              "summary": report.summary, "round": round_, "follow_up": follow}))


def report_json(raw: bytes) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(raw)
    return data
