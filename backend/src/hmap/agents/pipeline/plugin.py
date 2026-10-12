"""Default project pipeline as Manager hooks (owner: Member 1). No agents — only orchestration:

    document.uploaded            -> task  document.extract   (artifact_refs: the uploaded documents; inputs.documents:
                                                              [{artifact_id, name, folder, path}] in upload order)
    document.extract completed   -> task  plan.generate      (inputs: RequirementSet artifact)
    plan.generate completed      -> submit the TaskGraph     (project waits in AWAITING_APPROVAL)

Whoever serves a capability (a stub or a member's real agent) is irrelevant here, so Members 2 and 3 only add
their agents; they must not add duplicate hooks for these three steps.
"""

from typing import Any

from hmap.core.contracts import ArtifactRef, DomainEvent, TaskGraph
from hmap.core.contracts.capabilities import CAPABILITY_OUTPUTS, DOCUMENT_EXTRACT, PLAN_GENERATE
from hmap.core.plugins import ManagerHandle, Plugin, hook
from hmap.core.tracing import get_logger

log = get_logger("hmap.pipeline")


async def _result_refs(manager: ManagerHandle, task_id: str) -> list[ArtifactRef]:
    task = await manager.get_task(task_id)
    refs: list[Any] = []
    for exe in task.get("executions", []):
        if exe.get("status") == "SUCCEEDED":
            refs = exe.get("result_refs") or []
    return [r if isinstance(r, ArtifactRef) else ArtifactRef.model_validate(r) for r in refs]


@hook("document.uploaded")
async def on_document_uploaded(event: DomainEvent, manager: ManagerHandle) -> None:
    project_id = event.project_id or event.aggregate_id
    refs = [ArtifactRef.model_validate(r) for r in event.data.get("artifact_refs", [])]
    documents = list(event.data.get("files") or [])          # name + folder per artifact (absent for older events)
    folders = sorted({d["folder"] for d in documents if d.get("folder")})
    criteria = ["every requirement has a source reference"]
    if folders:
        # an assignment split into folders (Part A, Part B, ...) usually means separate parts of the work
        criteria.append("every requirement keeps the folder of its source document")
    await manager.create_task(project_id, DOCUMENT_EXTRACT, "Extract requirements from the uploaded documents",
                              artifact_refs=refs, inputs={"documents": documents} if documents else None,
                              acceptance_criteria=criteria)


@hook("task.completed", capability=DOCUMENT_EXTRACT)
async def on_requirements_ready(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    refs = await _result_refs(manager, event.aggregate_id)
    await manager.create_task(task["project_id"], PLAN_GENERATE, "Turn the requirements into a task graph",
                              artifact_refs=refs, parent_task_id=event.aggregate_id,
                              acceptance_criteria=["acyclic", "every requirement covered"])


@hook("task.completed", capability=PLAN_GENERATE)
async def on_plan_ready(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    project_id = task["project_id"]
    for ref in await _result_refs(manager, event.aggregate_id):
        if ref.artifact_type == CAPABILITY_OUTPUTS[PLAN_GENERATE][0]:
            raw = await manager.artifacts.get(ref, project_id=project_id)
            graph = TaskGraph.model_validate_json(raw).model_copy(update={"project_id": project_id})
            await manager.submit_graph(project_id, graph, require_approval=True)
            return
    log.warning("plan.generate finished without a TaskGraph artifact", task_id=event.aggregate_id)


PLUGIN = Plugin(name="pipeline", manager_hooks=[on_document_uploaded, on_requirements_ready, on_plan_ready],
                priority=50, description="default upload -> extract -> plan -> approval pipeline")
