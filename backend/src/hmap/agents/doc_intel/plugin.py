"""Member 2 plug-in: document intelligence (Sprint 2). Replaces the ``document.extract`` stub (priority 0).

The ``pipeline`` plug-in (Member 1) already creates the extract task on upload and the plan task afterwards; this
plug-in only adds the agent, its API and the ``project.requirements_ready`` event (spec §7) for the UI and Member 3.
"""

from hmap.agents.doc_intel.agent import DocIntelAgent
from hmap.agents.doc_intel.router import router
from hmap.core.contracts import ArtifactRef, DomainEvent
from hmap.core.contracts.capabilities import DOCUMENT_EXTRACT
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle, Plugin, hook


@hook("task.completed", capability=DOCUMENT_EXTRACT)
async def announce_requirements(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    refs = []
    for exe in task.get("executions", []):
        if exe.get("status") == "SUCCEEDED":
            refs = [ArtifactRef.model_validate(r) for r in exe.get("result_refs") or []]
    rs = next((r for r in refs if r.artifact_type == "requirement-set"), None)
    if rs is None:
        return
    project_id = task["project_id"]
    await manager.emit(DomainEvent(event_type=EventType.REQUIREMENTS_READY.value, aggregate_id=project_id,
                                   project_id=project_id, correlation_id=event.correlation_id,
                                   data={"project_id": project_id, "task_id": event.aggregate_id,
                                         "requirement_set_ref": rs.model_dump(mode="json")}))


PLUGIN = Plugin(
    name="doc_intel",
    agents=[DocIntelAgent],
    router=router,
    manager_hooks=[announce_requirements],
    priority=100,
    description="Document intelligence: PDF / DOCX / scans / images / text -> a traceable RequirementSet.",
)
