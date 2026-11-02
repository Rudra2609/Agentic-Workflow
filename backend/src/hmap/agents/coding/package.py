"""Where a task's workspace starts (plan D1), and how its result is stored (D2, D3).

Start, first match wins: ``inputs.workspace_ref`` (benchmark, demo, API) → the project's workspace head
``wsh-<project_id>`` → the newest ``workspace`` among the task's ``artifact_refs`` (an upstream changeset) → empty
(the loop then installs a template).

Result: ``code-change-set`` ``ccs-<task_id>`` (first), ``workspace`` ``ws-<task_id>`` (the full tree after this task),
``code-patch`` ``patch-<task_id>`` (only this task's diff) and ``coding-trace`` ``ct-<task_id>``. The head moves to
the new tree; if another coding task moved it meanwhile, this task's change is re-applied on the newer head with a
three-way merge (:func:`~hmap.agents.coding.workspace.rebase`); a conflict is reported to the caller, which redoes
the task once on the newer head.
"""

from dataclasses import dataclass

from hmap.agents.coding.model import (
    CHANGESET_TYPE,
    HEAD_TYPE,
    PATCH_MEDIA,
    PATCH_TYPE,
    TRACE_TYPE,
    WORKSPACE_MEDIA,
    WORKSPACE_TYPE,
    CodingTrace,
    changeset_id,
    head_id,
    patch_id,
    trace_id,
    workspace_id,
)
from hmap.agents.coding.workspace import Workspace, changed_files, files_from_tar, pack, rebase, unified_diff, unpack
from hmap.core.contracts import ArtifactRef, CodeChangeSet, TaskAssign
from hmap.core.contracts.domain import CommandRun
from hmap.core.runtime.base import AgentContext


@dataclass
class Base:
    how: str                                # inputs | head | upstream | empty
    ref: ArtifactRef | None = None          # what was unpacked
    head: ArtifactRef | None = None         # the head version this task started from (None = no head yet)
    files: dict[str, str] | None = None     # text files at the start


async def latest_head(ctx: AgentContext) -> ArtifactRef | None:
    return await ctx.artifacts.latest(head_id(ctx.project_id), project_id=ctx.project_id)


async def load_base(task: TaskAssign, ctx: AgentContext, ws: Workspace) -> Base:
    explicit = task.inputs.get("workspace_ref")
    head = await latest_head(ctx)
    ref: ArtifactRef | None
    if isinstance(explicit, dict):
        ref = ArtifactRef.model_validate(explicit)
        base = Base("inputs", ref, head)
    elif head is not None:
        base = Base("head", head, head)
    else:
        upstream = [r for r in task.artifact_refs if r.artifact_type in (WORKSPACE_TYPE, HEAD_TYPE)]
        ref = max(upstream, key=lambda r: (r.created_at, r.version), default=None)
        base = Base("upstream" if ref else "empty", ref, None)
    if base.ref is not None:
        unpack(await ctx.artifacts.get(base.ref, project_id=ctx.project_id), ws)
    base.files = ws.snapshot()
    return base


@dataclass
class Stored:
    refs: list[ArtifactRef]
    changeset: CodeChangeSet
    conflicts: list[str]


def summary_notes(trace: CodingTrace) -> str:
    parts = []
    if trace.template:
        parts.append(f"started from the {trace.template} template")
    if trace.plan and trace.plan.get("summary"):
        parts.append(f"plan: {trace.plan['summary']}")
    checks = ", ".join(f"{c.name} {c.status}" for c in trace.checks)
    if checks:
        parts.append(f"checks: {checks}")
    parts.append(f"stop: {trace.stop_reason}")
    if trace.outcome == "partial":
        failing = [c for c in trace.checks if c.status == "failed"]
        if failing:
            parts.append("NOT DONE: " + "; ".join(f"{c.name}: {c.detail[-160:]}" for c in failing))
        elif trace.stop_reason in ("no_model", "step_budget"):
            parts.append("NOT DONE: the model did not finish the change")
    if trace.flags:
        parts.append(f"repository text that talks to an AI was treated as data: {', '.join(trace.flags[:5])}")
    return " | ".join(parts)[:2000]


async def store(task: TaskAssign, ctx: AgentContext, ws: Workspace, trace: CodingTrace, base: Base,
                *, update_head: bool = True) -> Stored:
    """Write the head (rebasing if it moved), the workspace, the patch, the trace and the changeset."""
    before = base.files or {}
    after = ws.snapshot()
    conflicts: list[str] = []
    head_now = await latest_head(ctx) if update_head else None
    moved = update_head and head_now is not None and (base.head is None or head_now.version != base.head.version)
    if moved and head_now is not None:
        head_files = files_from_tar(await ctx.artifacts.get(head_now, project_id=ctx.project_id))
        merged, conflicts = rebase(before, after, head_files)
        if not conflicts:
            ws.restore(merged)
            trace.notes.append(f"the project head moved (v{head_now.version}); this change was re-applied on it")
    tree = pack(ws)
    if update_head and not conflicts:
        head_ref = await ctx.artifacts.put(tree, project_id=ctx.project_id, artifact_type=HEAD_TYPE,
                                           media_type=WORKSPACE_MEDIA, created_by=ctx.agent_id,
                                           artifact_id=head_id(ctx.project_id))
        trace.head_version = head_ref.version
    ws_ref = await ctx.artifacts.put(tree, project_id=ctx.project_id, artifact_type=WORKSPACE_TYPE,
                                     media_type=WORKSPACE_MEDIA, created_by=ctx.agent_id,
                                     artifact_id=workspace_id(task.task_id))
    patch = unified_diff(before, after)
    patch_ref = await ctx.artifacts.put(patch.encode("utf-8"), project_id=ctx.project_id, artifact_type=PATCH_TYPE,
                                        media_type=PATCH_MEDIA, created_by=ctx.agent_id,
                                        artifact_id=patch_id(task.task_id))
    trace.files_changed = changed_files(before, after)
    trace.status = "done"
    changeset = CodeChangeSet(
        task_id=task.task_id, workspace_ref=ws_ref, patch_ref=patch_ref, files_changed=trace.files_changed,
        commands_run=[CommandRun(cmd=c.cmd[:500], exit_code=c.exit_code if c.exit_code is not None else -1,
                                 duration_s=c.duration_s) for c in trace.commands if not c.denied][-40:],
        notes=summary_notes(trace))
    trace_ref = await ctx.put_json(trace, artifact_type=TRACE_TYPE, artifact_id=trace_id(task.task_id))
    ccs_ref = await ctx.put_json(changeset, artifact_type=CHANGESET_TYPE, artifact_id=changeset_id(task.task_id))
    return Stored([ccs_ref, ws_ref, patch_ref, trace_ref], changeset, conflicts)
