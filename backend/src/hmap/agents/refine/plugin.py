"""Member 4 plug-in: self-reflection and refinement (Sprint 4).

- ``refiners``: check-and-improve adapters for ``document.extract`` (Member 2) and ``plan.generate`` (Member 3); the
  agent runtime applies them when a task has ``refine=true`` (the project setting) — their code is untouched (D1).
- ``RefineAgent`` serves ``refine.run`` (standalone refinement of any artifact, item 4.12).
- hooks: progress messages carrying a refinement record become ``refine.iteration`` / ``refine.stopped`` events
  (D5); a standalone refinement that improved the current plan hands the new version to the Manager (approval again).
"""

import json

from hmap.agents.refine.adapters import EXTRACTION_ADAPTER, PLAN_ADAPTER
from hmap.agents.refine.agent import RefineAgent
from hmap.agents.refine.router import router
from hmap.agents.refine.trace import PROGRESS_TYPE, TRACE_TYPE
from hmap.core.contracts import ArtifactRef, DomainEvent, TaskGraph
from hmap.core.contracts.capabilities import DOCUMENT_EXTRACT, PLAN_GENERATE, REFINE_RUN
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle, Plugin, hook
from hmap.core.tracing import get_logger

log = get_logger("hmap.refine")


@hook("task.progress")
async def announce_refinement(event: DomainEvent, manager: ManagerHandle) -> None:
    """``task.progress`` with a refinement record -> ``refine.iteration`` (running) / ``refine.stopped`` (final)."""
    refs = [ArtifactRef.model_validate(r) for r in event.data.get("artifact_refs") or []
            if isinstance(r, dict) and r.get("artifact_type") in (PROGRESS_TYPE, TRACE_TYPE)]
    project_id = event.project_id
    if not refs or project_id is None:
        return
    ref = refs[-1]
    run = json.loads(await manager.artifacts.get(ref, project_id=project_id))
    iterations = run.get("iterations") or []
    last = iterations[-1] if iterations else {}
    data = {"task_id": event.aggregate_id, "run_id": run.get("run_id"), "capability": run.get("capability"),
            "subject": run.get("subject"), "iteration": last.get("index"), "score": last.get("score"),
            "issues_by_category": last.get("issues_by_category") or {}, "strategy": last.get("strategy"),
            "best_iteration": run.get("best_iteration"), "base_score": run.get("base_score"),
            "best_score": run.get("best_score"), "trace_ref": ref.model_dump(mode="json")}
    if ref.artifact_type == TRACE_TYPE:
        event_type = EventType.REFINE_STOPPED.value
        data.update({"stop_reason": run.get("stop_reason"), "iterations": max(0, len(iterations) - 1),
                     "applied": run.get("applied"), "tokens": run.get("tokens"), "seconds": run.get("seconds")})
    else:
        event_type = EventType.REFINE_ITERATION.value
    await manager.emit(DomainEvent(event_type=event_type, aggregate_id=event.aggregate_id, project_id=project_id,
                                   correlation_id=event.correlation_id, data=data))


@hook("task.completed", capability=REFINE_RUN)
async def apply_refined_plan(event: DomainEvent, manager: ManagerHandle) -> None:
    """A standalone check of the plan that produced a better version replaces the plan (approval needed again)."""
    task = await manager.get_task(event.aggregate_id)
    project_id = task["project_id"]
    refs = [ArtifactRef.model_validate(r) for r in event.data.get("artifact_refs") or []]
    graph_ref = next((r for r in refs if r.artifact_type == "task-graph"), None)
    if graph_ref is None or graph_ref.created_by == "user" or graph_ref.version <= 1:
        return
    graph = TaskGraph.model_validate_json(await manager.artifacts.get(graph_ref, project_id=project_id))
    try:
        await manager.replace_graph(project_id, graph.model_copy(update={"project_id": project_id}),
                                    require_approval=True)
    except ValueError as exc:  # StaleGraph / InvalidProjectState / ProjectStopped: a newer plan won meanwhile
        log.info("refined plan not applied", task_id=event.aggregate_id, reason=str(exc))


PLUGIN = Plugin(
    name="refine",
    agents=[RefineAgent],
    router=router,
    manager_hooks=[announce_refinement, apply_refined_plan],
    refiners={DOCUMENT_EXTRACT: EXTRACTION_ADAPTER, PLAN_GENERATE: PLAN_ADAPTER},
    priority=100,
    description="Self-refinement: critique -> classify -> revise -> stop, with Reflexion; refines requirements and "
                "plans when a project has 'Check and improve results' on; refine.run for any artifact.",
)
