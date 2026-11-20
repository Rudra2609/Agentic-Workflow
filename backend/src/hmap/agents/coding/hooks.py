"""Manager hooks of the coding agent (Sprint 7, plan D16).

``task.completed`` of a ``code.implement`` / ``code.revise`` step emits ``code.completed {task_id, changeset_ref,
patch_ref, workspace_ref, files_changed, checks_passed, outcome, revision_of}`` (spec §7): Member 8's tests and
Member 9's ``docs.update`` listen to it. There is deliberately **no** hook on failed tests in Sprint 7 (plan D15):
the ``test.run`` stub always reports a failure, and the test → revise loop is Member 8's (item 8.9).
"""

from typing import Any

from hmap.agents.coding.model import CHANGESET_TYPE
from hmap.core.contracts import ArtifactRef, CodeChangeSet, DomainEvent
from hmap.core.contracts.capabilities import CODE_IMPLEMENT, CODE_REVISE
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle, hook
from hmap.core.tracing import get_logger

log = get_logger("hmap.coding.hooks")


def _refs(raw: Any) -> list[ArtifactRef]:
    return [r if isinstance(r, ArtifactRef) else ArtifactRef.model_validate(r) for r in raw or []
            if isinstance(r, dict | ArtifactRef)]


async def emit_code_completed(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    project_id = str(task["project_id"])
    refs = _refs(event.data.get("artifact_refs"))
    if not refs:
        for exe in task.get("executions", []):
            if exe.get("status") == "SUCCEEDED":
                refs = _refs(exe.get("result_refs"))
    ref = next((r for r in refs if r.artifact_type == CHANGESET_TYPE), None)
    if ref is None:
        return
    ccs = CodeChangeSet.model_validate_json(await manager.artifacts.get(ref, project_id=project_id))
    inputs = task.get("inputs") or {}
    await manager.emit(DomainEvent(
        event_type=EventType.CODE_COMPLETED.value, aggregate_id=event.aggregate_id, project_id=project_id,
        correlation_id=event.correlation_id,
        data={"task_id": event.aggregate_id, "changeset_ref": ref.model_dump(mode="json"),
              "patch_ref": ccs.patch_ref.model_dump(mode="json") if ccs.patch_ref else None,
              "workspace_ref": ccs.workspace_ref.model_dump(mode="json"), "files_changed": ccs.files_changed,
              "checks_passed": "NOT DONE" not in ccs.notes, "outcome": event.data.get("outcome"),
              "capability": task.get("capability"), "revision_of": inputs.get("revision_of")}))


@hook("task.completed", capability=CODE_IMPLEMENT)
async def on_code_implemented(event: DomainEvent, manager: ManagerHandle) -> None:
    await emit_code_completed(event, manager)


@hook("task.completed", capability=CODE_REVISE)
async def on_code_revised(event: DomainEvent, manager: ManagerHandle) -> None:
    await emit_code_completed(event, manager)
