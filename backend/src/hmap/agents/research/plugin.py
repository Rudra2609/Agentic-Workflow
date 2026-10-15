"""Member 5 plug-in: autonomous research (Sprint 5).

- ``ResearchAgent`` serves ``research.run`` (priority 100: the stub stands down).
- hooks: a completed research step emits ``research.completed {task_id, report_ref, ...}`` for Member 6 (item
  5.11); a deleted project's index rows are removed.
- router ``/api/research`` (auto-mounted); UI ``frontend/src/features/research/`` (auto-registered).
"""

import json

from hmap.agents.research.agent import ResearchAgent
from hmap.agents.research.index import backend_for
from hmap.agents.research.model import REPORT_TYPE
from hmap.agents.research.router import router
from hmap.core.contracts import ArtifactRef, DomainEvent
from hmap.core.contracts.capabilities import RESEARCH_RUN
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle, Plugin, hook
from hmap.core.tracing import get_logger

log = get_logger("hmap.research")


@hook("task.completed", capability=RESEARCH_RUN)
async def announce_research(event: DomainEvent, manager: ManagerHandle) -> None:
    refs = [ArtifactRef.model_validate(r) for r in event.data.get("artifact_refs") or [] if isinstance(r, dict)]
    report_ref = next((r for r in refs if r.artifact_type == REPORT_TYPE), None)
    project_id = event.project_id
    if report_ref is None or project_id is None:
        return
    report = json.loads(await manager.artifacts.get(report_ref, project_id=project_id))
    subs = report.get("sub_questions") or []
    await manager.emit(DomainEvent(
        event_type=EventType.RESEARCH_COMPLETED.value, aggregate_id=event.aggregate_id, project_id=project_id,
        correlation_id=event.correlation_id,
        data={"task_id": event.aggregate_id, "report_ref": report_ref.model_dump(mode="json"),
              "stop_reason": report.get("stop_reason"), "claims": len(report.get("claims") or []),
              "evidence": len(report.get("evidence") or []), "sources": len(report.get("sources") or []),
              "coverage": report.get("coverage") or {},
              "covered": sum(1 for s in subs if s.get("status") == "covered"), "sub_questions": len(subs)}))


@hook("project.deleted")
async def forget_project(event: DomainEvent, manager: ManagerHandle) -> None:
    project_id = event.project_id or event.aggregate_id
    removed = await backend_for(manager.contexts).delete_project(project_id)
    log.info("research index rows removed", project_id=project_id, chunks=removed)


PLUGIN = Plugin(
    name="research",
    agents=[ResearchAgent],
    router=router,
    manager_hooks=[announce_research, forget_project],
    priority=100,
    description="Autonomous research: plans sub-questions, searches (Wikipedia, arXiv, DuckDuckGo, offline corpus), "
                "reads, quotes verbatim evidence, tracks coverage, stops, and writes a cited ResearchReport.",
)
