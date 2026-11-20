"""``code.revise`` inputs (Sprint 7 item 7.9, plan D14).

A revision is an ordinary task for capability ``code.revise`` (the ``revision.request`` message has no handler in
the runtime or the Manager). Whoever asks for one — the coding tab's "Request changes" button now, Member 8's
test loop and Member 10's recovery later — creates it with ``ManagerHandle.create_task``:

    await manager.create_task(project_id, "code.revise", "Fix: client 3 never gets the broadcast",
                              inputs=revision_inputs(changeset_ref, required_changes=[...], round_=1),
                              artifact_refs=[test_report_ref], parent_task_id=original_task_id)

The agent starts from the project head (which holds the original change), reads failures from any
``test-report`` / ``review-report`` in ``artifact_refs``, and returns a new ``CodeChangeSet``.
"""

from typing import Any

from hmap.agents.coding import debug
from hmap.core.contracts import ArtifactRef, ReviewReport, TestReport
from hmap.core.contracts.capabilities import CODE_REVISE
from hmap.core.runtime.base import AgentContext

__all__ = ["CODE_REVISE", "evidence_from_refs", "revision_inputs"]


def revision_inputs(changeset_ref: ArtifactRef | dict[str, Any] | None, *, required_changes: list[str],
                    round_: int = 1, original_task_id: str | None = None) -> dict[str, Any]:
    ref = changeset_ref.model_dump(mode="json") if isinstance(changeset_ref, ArtifactRef) else changeset_ref
    out: dict[str, Any] = {"revision_of": ref, "required_changes": [str(c)[:500] for c in required_changes][:20],
                           "revision_round": int(round_)}
    if original_task_id:
        out["original_task_id"] = original_task_id
    return out


def from_test_report(report: TestReport) -> tuple[list[str], list[debug.Failure]]:
    failures = debug.from_test_report([f.model_dump() for f in report.failures])
    changes = [f"fix: {f.short()}" for f in failures][:10]
    return changes, failures


def from_review_report(report: ReviewReport, task_ids: set[str]) -> list[str]:
    out = []
    for plan in report.revision_requests:
        if not task_ids or plan.task_id in task_ids:
            out.extend(plan.required_changes)
    for f in report.failures:
        if not task_ids or f.responsible_task_id in task_ids:
            out.append(f"{f.category}: {f.description}")
    return out[:10]


async def evidence_from_refs(refs: list[ArtifactRef], ctx: AgentContext,
                             task_ids: set[str]) -> tuple[list[str], list[debug.Failure]]:
    """Requested changes + located failures from the test / review reports handed to a revision."""
    changes: list[str] = []
    failures: list[debug.Failure] = []
    for ref in refs:
        try:
            if ref.artifact_type == "test-report":
                c, f = from_test_report(await ctx.get_json(ref, TestReport))
                changes += c
                failures += f
            elif ref.artifact_type == "review-report":
                changes += from_review_report(await ctx.get_json(ref, ReviewReport), task_ids)
        except Exception:  # evidence is optional; a broken report must not fail the revision
            continue
    return changes, failures
