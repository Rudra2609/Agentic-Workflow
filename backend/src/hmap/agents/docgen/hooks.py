"""Manager hooks of the documentation agent (Sprint 9, plan D12).

1. ``task.completed`` of ``docs.generate`` / ``docs.update`` -> ``docs.completed {task_id, bundle_ref,
   grounded_pct, ungrounded, removed, mode}`` (spec §7: Member 10's review listens to it). Only real bundles count:
   the step must have a ``docgen-trace`` (the stub never writes one).
2. ``code.completed`` (Member 7) -> a ``docs.update`` task, so documents do not go stale after a revision, but only
   when (a) ``HMAP_DOCGEN_AUTO_UPDATE`` is on, (b) the project already has documents (``dh-<project>``) and (c) no
   docs task of the project is still waiting or running. (c) keeps the plan's own docs step, and Member 10's
   recovery (which re-runs test -> docs -> review itself), from getting a second docs run (plan T8).
"""

from typing import Any

from hmap.agents.docgen.model import BUNDLE_TYPE, TRACE_TYPE, DocgenTrace, head_id
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, DocBundle, DomainEvent
from hmap.core.contracts.capabilities import DOCS_GENERATE, DOCS_UPDATE
from hmap.core.contracts.events import EventType
from hmap.core.contracts.states import TERMINAL_TASK_STATES
from hmap.core.plugins import ManagerHandle, hook
from hmap.core.tracing import get_logger

log = get_logger("hmap.docgen.hooks")
DONE_STATES = {s.value for s in TERMINAL_TASK_STATES}


def _refs(raw: Any) -> list[ArtifactRef]:
    return [r if isinstance(r, ArtifactRef) else ArtifactRef.model_validate(r) for r in raw or []
            if isinstance(r, dict | ArtifactRef)]


async def _emit_done(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    project_id = str(task["project_id"])
    refs = _refs(event.data.get("artifact_refs"))
    if not refs:
        for exe in task.get("executions", []):
            if exe.get("status") == "SUCCEEDED":
                refs = _refs(exe.get("result_refs"))
    tr = next((r for r in refs if r.artifact_type == TRACE_TYPE), None)
    bundle_ref = next((r for r in refs if r.artifact_type == BUNDLE_TYPE), None)
    if tr is None or bundle_ref is None:
        return                                      # the stub, or an old run
    trace = DocgenTrace.model_validate_json(await manager.artifacts.get(tr, project_id=project_id))
    bundle = DocBundle.model_validate_json(await manager.artifacts.get(bundle_ref, project_id=project_id))
    await manager.emit(DomainEvent(
        event_type=EventType.DOCS_COMPLETED.value, aggregate_id=event.aggregate_id, project_id=project_id,
        correlation_id=event.correlation_id,
        data={"task_id": event.aggregate_id, "bundle_ref": bundle_ref.model_dump(mode="json"),
              "grounded_pct": bundle.accuracy_report.grounded_pct,
              "ungrounded": len(bundle.accuracy_report.ungrounded_claims), "mode": trace.mode,
              "documents": trace.documents, "capability": task.get("capability")}))


@hook("task.completed", capability=DOCS_GENERATE)
async def on_docs_done(event: DomainEvent, manager: ManagerHandle) -> None:
    await _emit_done(event, manager)


@hook("task.completed", capability=DOCS_UPDATE)
async def on_docs_updated(event: DomainEvent, manager: ManagerHandle) -> None:
    await _emit_done(event, manager)


@hook(EventType.CODE_COMPLETED.value)
async def on_code_completed(event: DomainEvent, manager: ManagerHandle) -> None:
    settings = Settings.from_env()
    project_id = event.project_id
    if not settings.docgen_auto_update or not project_id:
        return
    head = await manager.artifacts.latest(head_id(project_id), project_id=project_id)
    if head is None:
        return                                       # no documents yet: the plan's docs step will write them
    list_tasks = getattr(manager, "list_tasks", None)
    if list_tasks is None:
        return
    pending = [t for t in await list_tasks(project_id) if t.get("capability") in (DOCS_GENERATE, DOCS_UPDATE)
               and str(t.get("state")) not in DONE_STATES]
    if pending:
        log.info("docs.update not started: a docs task is pending", project_id=project_id,
                 pending=[t.get("task_id") for t in pending])
        return
    task_id = await manager.create_task(
        project_id, DOCS_UPDATE, "Update the documentation after the code change",
        acceptance_criteria=["every documented claim is grounded in the changed code"],
        inputs={"previous_bundle": head.model_dump(mode="json"), "changed_by": event.data.get("task_id")},
        parent_task_id=str(event.data.get("task_id") or event.aggregate_id) or None)
    log.info("docs.update started", project_id=project_id, task_id=task_id, after=event.data.get("task_id"))
