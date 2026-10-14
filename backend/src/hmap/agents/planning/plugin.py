"""Member 3 plug-in: planning and task decomposition (Sprint 3). Replaces the ``plan.generate`` stub (priority 0)
and Member 1's naive executor (``executor`` strategy slot).

The ``pipeline`` plug-in (Member 1) already creates the plan task after extraction and submits the plan for approval;
this plug-in adds the agent, the layer-parallel executor, the plan API and two hooks:

- ``plan.replan`` finished -> ``Manager.replace_graph`` (finished steps kept, approval again);
- a plan approved -> ``plan.approved {project_id, plan_ref, graph_version}`` (spec §7) for the UI and Members 4/5.
"""

from hmap.agents.planning.agent import GRAPH_TYPE, PlanningAgent
from hmap.agents.planning.executor import LayerParallelExecutor
from hmap.agents.planning.router import router
from hmap.core.contracts import ArtifactRef, DomainEvent, TaskGraph
from hmap.core.contracts.capabilities import PLAN_REPLAN
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle, Plugin, hook
from hmap.core.tracing import get_logger

log = get_logger("hmap.planning")


async def _result_refs(manager: ManagerHandle, task_id: str) -> list[ArtifactRef]:
    task = await manager.get_task(task_id)
    refs: list[ArtifactRef] = []
    for exe in task.get("executions", []):
        if exe.get("status") == "SUCCEEDED":
            refs = [ArtifactRef.model_validate(r) for r in exe.get("result_refs") or []]
    return refs


@hook("task.completed", capability=PLAN_REPLAN)
async def apply_replan(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    project_id = task["project_id"]
    ref = next((r for r in await _result_refs(manager, event.aggregate_id) if r.artifact_type == GRAPH_TYPE), None)
    if ref is None:
        log.warning("plan.replan finished without a task graph", task_id=event.aggregate_id)
        return
    graph = TaskGraph.model_validate_json(await manager.artifacts.get(ref, project_id=project_id))
    try:
        await manager.replace_graph(project_id, graph.model_copy(update={"project_id": project_id}),
                                    require_approval=True)
    except ValueError as exc:  # StaleGraph / InvalidProjectState: a newer plan won meanwhile
        log.info("replan not applied", task_id=event.aggregate_id, reason=str(exc))


@hook("approval.decided")
async def announce_plan_approved(event: DomainEvent, manager: ManagerHandle) -> None:
    if not event.data.get("approved"):
        return
    project_id = event.project_id or event.aggregate_id
    version = event.data.get("graph_version")
    refs = [r for r in await manager.artifacts.list(project_id) if r.artifact_type == GRAPH_TYPE]
    if version is not None:
        refs = [r for r in refs if r.version == version] or refs
    if not refs:
        return
    ref = max(refs, key=lambda r: (r.created_at, r.version))
    await manager.emit(DomainEvent(event_type=EventType.PLAN_APPROVED.value, aggregate_id=project_id,
                                   project_id=project_id, correlation_id=event.correlation_id,
                                   data={"project_id": project_id, "plan_ref": ref.model_dump(mode="json"),
                                         "graph_version": version if version is not None else ref.version,
                                         "auto": bool(event.data.get("auto"))}))


PLUGIN = Plugin(
    name="planning",
    agents=[PlanningAgent],
    router=router,
    manager_hooks=[apply_replan, announce_plan_approved],
    provides={"executor": LayerParallelExecutor},
    priority=100,
    description="Planning: RequirementSet -> validated TaskGraph (DAG, roadmap, coverage), layer-parallel executor, "
                "human edits and replanning.",
)
