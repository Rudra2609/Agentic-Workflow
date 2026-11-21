"""Manager hook of the testing agent (Sprint 8, plan D10, D15).

``task.completed`` of a ``test.run`` step:

1. emits ``test.completed {task_id, report_ref, passed, failures, changeset_ref, coding_task_id, loop_round}``
   (spec §7: Member 10's review and Member 7 listen to it);
2. asks :func:`.refine_loop.decide` whether to revise; if so creates ``code.revise`` (Member 7) for the tested
   coding step and a new ``test.run`` that depends on it (one more loop round).

Only reports of the real agent count: the step must have a ``testing-trace`` (the stub never writes one: trap T1).
"""

from typing import Any

from hmap.agents.coding.revise import revision_inputs
from hmap.agents.testing.model import REPORT_TYPE, TRACE_TYPE, TestingTrace
from hmap.agents.testing.refine_loop import decide, signature
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, DomainEvent
from hmap.core.contracts.capabilities import CODE_REVISE, TEST_RUN
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle, hook
from hmap.core.tracing import get_logger

log = get_logger("hmap.testing.hooks")


def _refs(raw: Any) -> list[ArtifactRef]:
    return [r if isinstance(r, ArtifactRef) else ArtifactRef.model_validate(r) for r in raw or []
            if isinstance(r, dict | ArtifactRef)]


async def result_refs(event: DomainEvent, task: dict[str, Any]) -> list[ArtifactRef]:
    refs = _refs(event.data.get("artifact_refs"))
    if not refs:
        for exe in task.get("executions", []):
            if exe.get("status") == "SUCCEEDED":
                refs = _refs(exe.get("result_refs"))
    return refs


@hook("task.completed", capability=TEST_RUN)
async def on_tests_done(event: DomainEvent, manager: ManagerHandle) -> None:
    task = await manager.get_task(event.aggregate_id)
    project_id = str(task["project_id"])
    refs = await result_refs(event, task)
    tr_ref = next((r for r in refs if r.artifact_type == TRACE_TYPE), None)
    rep_ref = next((r for r in refs if r.artifact_type == REPORT_TYPE), None)
    if tr_ref is None or rep_ref is None:
        return                                    # the stub, or an old run: nothing of ours to act on
    trace = TestingTrace.model_validate_json(await manager.artifacts.get(tr_ref, project_id=project_id))
    await manager.emit(DomainEvent(
        event_type=EventType.TEST_COMPLETED.value, aggregate_id=event.aggregate_id, project_id=project_id,
        correlation_id=event.correlation_id,
        data={"task_id": event.aggregate_id, "report_ref": rep_ref.model_dump(mode="json"), "passed": trace.passed,
              "failures": len([f for f in trace.failures if f.category != "LINT" and not f.flaky]),
              "changeset_ref": trace.changeset_ref.model_dump(mode="json") if trace.changeset_ref else None,
              "coding_task_id": trace.coding_task_id, "loop_round": trace.loop.round, "backend": trace.backend}))
    settings = Settings.from_env()
    decision = decide(trace, enabled=settings.testing_auto_revise, max_rounds=settings.testing_max_rounds)
    log.info("test loop decision", task_id=event.aggregate_id, revise=decision.revise, reason=decision.reason)
    if not decision.revise:
        return
    await start_revision(manager, task, trace, rep_ref, decision.required_changes)


async def start_revision(manager: ManagerHandle, task: dict[str, Any], trace: TestingTrace, report_ref: ArtifactRef,
                         changes: list[str]) -> tuple[str, str]:
    project_id = str(task["project_id"])
    coding_task = await manager.get_task(trace.coding_task_id or "")
    original = (coding_task.get("inputs") or {}).get("original_task_id") or trace.coding_task_id
    round_ = trace.loop.round + 1
    criteria = list(task.get("acceptance_criteria") or [])[:10]
    revise_id = await manager.create_task(
        project_id, CODE_REVISE, f"Fix the failing tests (round {round_}): {changes[0][:140]}",
        acceptance_criteria=[*criteria, *changes][:20],
        inputs=revision_inputs(trace.changeset_ref, required_changes=changes, round_=round_,
                               original_task_id=original),
        artifact_refs=[report_ref], parent_task_id=trace.coding_task_id)
    inputs = {k: v for k, v in (task.get("inputs") or {}).items() if k in ("entrypoint", "sample_input",
                                                                         "long_running", "generate_tests", "tests")}
    inputs["loop"] = {"round": round_, "origin_task_id": trace.loop.origin_task_id or task["task_id"],
                      "history": [*trace.loop.history, trace.pass_ratio],
                      "last_failures": signature(trace.failures)}
    test_id = await manager.create_task(
        project_id, TEST_RUN, f"Test again after the fix (round {round_}): {str(task.get('objective'))[:140]}",
        acceptance_criteria=criteria, inputs=inputs, depends_on=[revise_id], parent_task_id=task["task_id"])
    log.info("test loop: revision started", round=round_, revise_task=revise_id, test_task=test_id)
    return revise_id, test_id
