"""Recovery (Sprint 10 items 10.6 / 10.7, plan D6, D7, D9, D10).

Two parts:

- :func:`plan_round` (pure, run by the review agent): the failures of this round -> the minimal set of
  ``RevisionPlan``\\ s (one per responsible task, merged changes), cheapest action first — **rerun** a first-time
  timeout / flaky test, **revise** the responsible task, **replan** a requirement no task covers, **escalate** when a
  stop rule fires or the attribution is unsure — plus the downstream tasks to execute again.
- :class:`ReviewRecovery` (the plug-in ``recovery`` strategy slot, run by the Manager): hands the review task the
  project's task table, and when the run's tasks are all settled reads the newest review report and either lets the
  project finish (PASS, or a person accepted it), waits for a person (ESCALATE -> ``REVIEWING``), re-reviews (the
  work changed after the review read it: Member 8's loop was still fixing, plan T5) or creates the revision tasks:
  the fix, the downstream re-runs (test -> docs) and the next review round. Completed tasks are never re-run unless
  they are downstream of a fix; their evidence stays (artifacts are versioned). No file under ``manager/`` is ours.
"""

import contextlib
import json
from dataclasses import dataclass, field
from typing import Any

from hmap.agents.coding.revise import revision_inputs
from hmap.agents.review.evidence import Bundle, _origin
from hmap.agents.review.model import (
    Decided,
    FailureRec,
    ReviewTrace,
    decision_id,
    report_id,
    trace_id,
)
from hmap.agents.review.stop import check as stop_check
from hmap.agents.review.stop import signature
from hmap.core.config import Settings
from hmap.core.contracts import ArtifactRef, DomainEvent, ReviewReport
from hmap.core.contracts.capabilities import (
    CODE_IMPLEMENT,
    CODE_REVISE,
    DOCS_GENERATE,
    DOCS_UPDATE,
    PLAN_REPLAN,
    REVIEW_FINAL,
    TEST_RUN,
)
from hmap.core.contracts.domain import RevisionPlan
from hmap.core.contracts.events import EventType
from hmap.core.plugins import ManagerHandle
from hmap.core.tracing import get_logger

log = get_logger("hmap.review.recovery")

SETTLED = {"COMPLETED", "FAILED", "DEAD_LETTERED", "CANCELLED", "BLOCKED"}
COPY_INPUTS = ("entrypoint", "sample_input", "long_running", "generate_tests", "tests", "research_questions",
               "requirement_ids", "phase", "files", "repo_name", "capabilities")


# ================================================================ planning (pure)

@dataclass
class RoundPlan:
    plans: list[RevisionPlan] = field(default_factory=list)
    rerun: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    waiting: list[str] = field(default_factory=list)       # items whose test loop is still running
    recommendation: str = "PASS"


def plan_round(failures: list[FailureRec], decided: list[Decided], b: Bundle, *, review_task_id: str, round_: int,
               history: list[list[str]], max_rounds: int, min_confidence: float, calls: int = 0,
               budget_calls: int = 0) -> RoundPlan:
    out = RoundPlan()
    by_item = {d.item.id: d for d in decided}
    active = [f for f in failures if not f.no_action]
    for f in list(active):
        d = by_item.get(f.item_id)
        if d is not None and any(t.pending for t in d.item.evidence.tests):
            out.waiting.append(f.item_id)
            active.remove(f)
    if not active:
        out.recommendation = "REVISE" if out.waiting else "PASS"
        return out
    sig = signature([(f.item_id, f.category) for f in active])
    stop = stop_check(sig, history, round_=round_, max_rounds=max_rounds, calls=calls, budget_calls=budget_calls)
    merged: dict[tuple[str, str], RevisionPlan] = {}

    def add(task_id: str, action: str, change: str) -> None:
        key = (action, task_id)
        if key not in merged:
            merged[key] = RevisionPlan(task_id=task_id, action=action, required_changes=[])
        if change not in merged[key].required_changes:
            merged[key].required_changes.append(change[:500])

    for f in active:
        change = f"{f.item_id} {f.category}: {f.why}"
        d = by_item.get(f.item_id)
        if stop.stop:
            add(f.task_id or review_task_id, "escalate", change)
        elif f.task_id is None:
            add(review_task_id, "replan", f"{f.item_id} is not covered by any step: {f.why}"[:500])
        elif f.confidence < min_confidence:
            add(f.task_id, "escalate", f"not sure which step caused it ({f.confidence:.1f}): {change}")
        elif round_ == 0 and d is not None and any(t.status == "timeout" or t.flaky for t in d.item.evidence.tests):
            test = next(t for t in d.item.evidence.tests if t.status == "timeout" or t.flaky)
            origin = _origin(b.tasks[test.task_id], b.tasks) if test.task_id in b.tasks else test.task_id
            add(origin or f.task_id, "rerun", f"re-run first (a timeout / flaky test may be the slow laptop): "
                                              f"{change}")
        else:
            add(f.task_id, "revise", change)
    out.plans = list(merged.values())
    out.stop_reason = stop.reason
    redo = [p.task_id for p in out.plans if p.action in ("revise", "rerun") and p.task_id in b.tasks]
    rerun: list[str] = []
    for t in redo:
        for x in b.descendants(t):
            if b.tasks[x].capability != REVIEW_FINAL and x not in redo and x not in rerun:
                rerun.append(x)
    out.rerun = rerun
    acts = {p.action for p in out.plans}
    if out.waiting or acts & {"revise", "rerun", "replan"}:
        out.recommendation = "REVISE"
    else:
        out.recommendation = "ESCALATE"
    if "escalate" in acts and not acts & {"revise", "rerun", "replan"}:
        out.recommendation = "ESCALATE"
    return out


# ================================================================ the Manager side (strategy slot)

def _when(row: dict[str, Any], key: str = "updated_at") -> str:
    return str(row.get(key) or "")


def _succeeded(task: dict[str, Any]) -> dict[str, Any] | None:
    done = [e for e in task.get("executions") or [] if e.get("status") == "SUCCEEDED"]
    return max(done, key=lambda e: e.get("attempt", 0)) if done else None


def _ref(raw: Any) -> ArtifactRef | None:
    try:
        return raw if isinstance(raw, ArtifactRef) else ArtifactRef.model_validate(raw)
    except Exception:
        return None


class ReviewRecovery:
    """The ``recovery`` strategy (``provides={"recovery": ReviewRecovery}`` in ``plugin.py``)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = Settings.from_env()
        return self._settings

    # ---------------------------------------------------------------- assign_inputs
    async def assign_inputs(self, task: dict[str, Any], manager: ManagerHandle) -> dict[str, Any]:
        if task.get("capability") != REVIEW_FINAL:
            return {}
        return {"project_tasks": await self.table(str(task["project_id"]), manager)}

    async def table(self, project_id: str, manager: ManagerHandle) -> list[dict[str, Any]]:
        project = await manager.get_project(project_id)
        run = project.get("current_run", 1)
        rows = []
        for t in sorted(await manager.list_tasks(project_id), key=lambda t: _when(t, "created_at")):
            if t.get("run", 1) != run:
                continue
            inputs = t.get("inputs") or {}
            results: list[str] = []
            if t.get("state") == "COMPLETED":
                exe = _succeeded(await manager.get_task(t["task_id"]))
                results = [str(r.get("artifact_id")) for r in (exe or {}).get("result_refs") or []
                           if isinstance(r, dict)]
            loop: dict[str, Any] = inputs["loop"] if isinstance(inputs.get("loop"), dict) else {}
            rec: dict[str, Any] = inputs["recovery"] if isinstance(inputs.get("recovery"), dict) else {}
            rows.append({
                "task_id": t["task_id"], "capability": t["capability"], "plan_task_id": t.get("plan_task_id"),
                "title": str(t.get("title") or t.get("objective") or "")[:160],
                "requirement_ids": [str(r) for r in inputs.get("requirement_ids") or []],
                "depends_on": list(t.get("depends_on") or []), "parent_task_id": t.get("parent_task_id"),
                "state": t.get("state"), "replaced": bool(t.get("replaced")),
                "original_task_id": inputs.get("original_task_id") or rec.get("origin_task_id"),
                "loop_origin": loop.get("origin_task_id"), "recovery_round": rec.get("round"),
                "feedback": str(inputs.get("feedback") or "")[:500] if t["capability"] == PLAN_REPLAN else "",
                "phase": str(inputs.get("phase") or ""),
                "results": results, "created_at": _when(t, "created_at")})
        return rows

    # ---------------------------------------------------------------- on_settle
    async def on_settle(self, project_id: str, outcome: str, manager: ManagerHandle) -> str | None:
        project = await manager.get_project(project_id)
        run = project.get("current_run", 1)
        tasks = [t for t in await manager.list_tasks(project_id) if t.get("run", 1) == run and not t.get("replaced")]
        reviews = [t for t in tasks if t["capability"] == REVIEW_FINAL]
        if not reviews:
            return None
        last = max(reviews, key=lambda t: _when(t, "created_at"))
        if last.get("state") != "COMPLETED":
            return await self._failed_steps(project_id, last, manager, tasks)
        if any(((t.get("inputs") or {}).get("recovery") or {}).get("review_task_id") == last["task_id"]
               for t in tasks if isinstance((t.get("inputs") or {}).get("recovery"), dict)):
            return None                              # this review was acted on already (its work is settled)
        full = await manager.get_task(last["task_id"])
        exe = _succeeded(full)
        started = _when(exe or {}, "created_at")
        stale = [t for t in tasks if t["capability"] not in (REVIEW_FINAL, PLAN_REPLAN) and t.get("state") ==
                 "COMPLETED" and _when(t) > started and t["capability"].split(".")[0] in
                 ("code", "test", "docs", "research", "verify")]
        decision = await self._decision(project_id, last["task_id"], manager)
        if decision.get("accepted"):
            return "COMPLETED"
        report, round_ = await self._report(project_id, last["task_id"], manager)
        if stale and int((last.get("inputs") or {}).get("stale_count") or 0) < 3:
            await self._review_again(project_id, last, manager, round_=round_, reason="stale", deps=[])
            return "hold"
        if report is None:
            return None
        if report.recommendation == "PASS":
            return "COMPLETED"                       # the review is the judge, also after re-run failed steps
        hold = "REVIEWING" if self.settings.review_hold_on_escalate else None
        if report.recommendation == "ESCALATE" or not self.settings.review_auto_recover:
            return hold
        created = await self.execute(project_id, last, report, round_, manager, tasks)
        return "hold" if created else hold

    async def _failed_steps(self, project_id: str, last: dict[str, Any], manager: ManagerHandle,
                            tasks: list[dict[str, Any]]) -> str | None:
        """The review never ran because a step FAILED / dead-lettered (its dependants are BLOCKED): re-run each
        failed plan step once (plan D6 "rerun"), with its downstream steps and the review."""
        if not self.settings.review_auto_recover:
            return None
        acted = {((t.get("inputs") or {}).get("recovery") or {}).get("origin_task_id") for t in tasks
                 if isinstance((t.get("inputs") or {}).get("recovery"), dict)}
        failed = [t for t in tasks if t.get("plan_task_id") and t.get("state") in ("FAILED", "DEAD_LETTERED")
                  and t["task_id"] not in acted and t["capability"] != REVIEW_FINAL]
        if not failed:
            return None
        plans = [RevisionPlan(task_id=t["task_id"], action="rerun", required_changes=[
            "the step failed: " + str((t.get("last_error") or {}).get("message") or "")[:200]]) for t in failed]
        made = await self.execute(project_id, last, None, int((last.get("inputs") or {}).get("review_round") or 0),
                                  manager, tasks, plans=plans)
        return "hold" if made else None

    async def _decision(self, project_id: str, review_task: str, manager: ManagerHandle) -> dict[str, Any]:
        ref = await manager.artifacts.latest(decision_id(review_task), project_id=project_id)
        if ref is None:
            return {}
        try:
            data: dict[str, Any] = json.loads(await manager.artifacts.get(ref, project_id=project_id))
            return data
        except Exception:
            return {}

    async def _report(self, project_id: str, review_task: str,
                      manager: ManagerHandle) -> tuple[ReviewReport | None, int]:
        round_ = 0
        tr = await manager.artifacts.latest(trace_id(review_task), project_id=project_id)
        if tr is not None:
            with contextlib.suppress(Exception):
                round_ = ReviewTrace.model_validate_json(await manager.artifacts.get(tr, project_id=project_id)).round
        ref = await manager.artifacts.latest(report_id(review_task), project_id=project_id)
        if ref is None:
            return None, round_
        try:
            return ReviewReport.model_validate_json(await manager.artifacts.get(ref, project_id=project_id)), round_
        except Exception:
            return None, round_

    async def _review_again(self, project_id: str, last: dict[str, Any], manager: ManagerHandle, *, round_: int,
                            reason: str, deps: list[str], rec: dict[str, Any] | None = None) -> str:
        inputs: dict[str, Any] = {k: v for k, v in (last.get("inputs") or {}).items()
                                  if k in ("requirement_ids", "phase")}
        inputs.update({"review_round": round_, "previous_review": last["task_id"]})
        if rec is not None:
            inputs["recovery"] = {**rec, "action": "review"}
        if reason == "stale":
            inputs["stale_of"] = last["task_id"]
            inputs["stale_count"] = int((last.get("inputs") or {}).get("stale_count") or 0) + 1
        what = (f"Final review again (round {round_}): the work changed while it was being reviewed"
                if reason == "stale" else f"Final review after the fixes (round {round_})")
        ref = await manager.artifacts.latest(report_id(last["task_id"]), project_id=project_id)
        return await manager.create_task(project_id, REVIEW_FINAL, what,
                                         acceptance_criteria=list(last.get("acceptance_criteria") or []),
                                         inputs=inputs, artifact_refs=[ref] if ref else [], depends_on=deps,
                                         parent_task_id=last["task_id"])

    async def execute(self, project_id: str, last: dict[str, Any], report: ReviewReport | None, round_: int,
                      manager: ManagerHandle, tasks: list[dict[str, Any]], *,
                      plans: list[RevisionPlan] | None = None) -> list[str]:
        """Create the revision tasks for ``report`` (or ``plans``): fixes, downstream re-runs, the next review."""
        by_id = {t["task_id"]: t for t in tasks}
        software = any(t["capability"].startswith("code.") for t in tasks)
        rep_ref = await manager.artifacts.latest(report_id(last["task_id"]), project_id=project_id)
        nxt = round_ + 1
        rec = {"round": nxt, "review_task_id": last["task_id"]}
        created: dict[str, str] = {}
        made: list[str] = []
        plans = plans if plans is not None else (report.revision_requests if report is not None else [])
        for p in plans:
            if p.action == "replan":
                tid = await self._replan(project_id, p, manager, rec, tasks)
                if tid:
                    made.append(tid)
                continue
            if p.action not in ("revise", "rerun") or p.task_id not in by_id:
                continue
            origin = self._origin(p.task_id, by_id)
            newest = self._newest(origin, by_id)
            tid = await self._redo(project_id, by_id[origin], newest, p.action, p.required_changes, nxt, rec,
                                   rep_ref, manager, deps=list(by_id[origin].get("depends_on") or []),
                                   software=software)
            created[origin] = tid
            made.append(tid)
            await manager.emit(DomainEvent(
                event_type=EventType.REVISION_REQUESTED.value, aggregate_id=newest["task_id"], project_id=project_id,
                correlation_id=project_id,
                data={"task_id": newest["task_id"], "revision_task_id": tid, "action": p.action, "round": nxt,
                      "review_task_id": last["task_id"], "required_changes": p.required_changes[:5]}))
        if not created:
            return made
        # downstream re-runs: plan steps that depend on a redone step, until nothing changes (plan tasks of one graph
        # share a creation time, so the order is found here, not by sorting)
        plan_steps = [t for t in tasks if t.get("plan_task_id") and t["capability"] != REVIEW_FINAL]
        changed = True
        while changed:
            changed = False
            for t in plan_steps:
                deps = list(t.get("depends_on") or [])
                if t["task_id"] in created or not any(d in created for d in deps):
                    continue
                if any(d in by_id and d not in created and self._depends_on_created(d, by_id, created)
                       for d in deps):
                    continue                     # a dependency is itself downstream and not created yet
                new_deps = [created.get(d, d) for d in deps]
                newest = self._newest(t["task_id"], by_id)
                tid = await self._redo(project_id, t, newest, "rerun", [], nxt, rec, rep_ref, manager,
                                       deps=new_deps, software=software)
                created[t["task_id"]] = tid
                made.append(tid)
                changed = True
        made.append(await self._review_again(project_id, last, manager, round_=nxt, reason="round",
                                             deps=list(created.values()), rec=rec))
        log.info("recovery: revision round created", project_id=project_id, round=nxt, tasks=len(made))
        return made

    @staticmethod
    def _depends_on_created(task_id: str, by_id: dict[str, dict[str, Any]], created: dict[str, str]) -> bool:
        """``task_id`` (transitively) depends on a redone step, so it will be redone too."""
        todo, seen = [task_id], set()
        while todo:
            cur = todo.pop()
            for d in by_id.get(cur, {}).get("depends_on") or []:
                if d in created:
                    return True
                if d not in seen:
                    seen.add(d)
                    todo.append(d)
        return False

    @staticmethod
    def _origin(task_id: str, by_id: dict[str, dict[str, Any]]) -> str:
        cur = task_id
        seen: set[str] = set()
        while cur in by_id and cur not in seen:
            seen.add(cur)
            t = by_id[cur]
            if t.get("plan_task_id"):
                return cur
            inputs = t.get("inputs") or {}
            loop: dict[str, Any] = inputs["loop"] if isinstance(inputs.get("loop"), dict) else {}
            rec: dict[str, Any] = inputs["recovery"] if isinstance(inputs.get("recovery"), dict) else {}
            nxt = inputs.get("original_task_id") or rec.get("origin_task_id") or loop.get("origin_task_id") \
                or t.get("parent_task_id")
            if not nxt:
                return cur
            cur = nxt
        return task_id

    def _newest(self, origin: str, by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
        fam = [t for t in by_id.values() if self._origin(t["task_id"], by_id) == origin
               and t.get("state") == "COMPLETED" and t["capability"] != REVIEW_FINAL]
        return max(fam, key=lambda t: _when(t, "created_at")) if fam else by_id[origin]

    async def _redo(self, project_id: str, origin: dict[str, Any], newest: dict[str, Any], action: str,
                    changes: list[str], round_: int, rec: dict[str, Any], rep_ref: ArtifactRef | None,
                    manager: ManagerHandle, *, deps: list[str], software: bool = True) -> str:
        cap = origin["capability"]
        inputs = {k: v for k, v in (origin.get("inputs") or {}).items() if k in COPY_INPUTS}
        inputs["recovery"] = {**rec, "origin_task_id": origin["task_id"], "action": action}
        refs = [rep_ref] if rep_ref is not None else []
        title = str(origin.get("title") or origin.get("objective") or cap)[:120]
        criteria = list(origin.get("acceptance_criteria") or [])[:10]
        if cap in (CODE_IMPLEMENT, CODE_REVISE) and action == "revise":
            exe = _succeeded(await manager.get_task(newest["task_id"])) or {}
            cs = next((r for r in exe.get("result_refs") or [] if isinstance(r, dict)
                       and r.get("artifact_type") == "code-change-set"), None)
            inputs.update(revision_inputs(cs, required_changes=changes or ["fix the review's findings"],
                                          round_=round_, original_task_id=origin["task_id"]))
            return await manager.create_task(project_id, CODE_REVISE, f"Fix (review round {round_}): "
                                             f"{(changes or [title])[0][:140]}",
                                             acceptance_criteria=[*criteria, *changes][:20], inputs=inputs,
                                             artifact_refs=refs, depends_on=[], parent_task_id=newest["task_id"])
        if cap == TEST_RUN:
            # the outer loop owns this round: Member 8's inner loop must not add rounds of its own (plan T5)
            mx = self.settings.testing_max_rounds
            inputs["loop"] = {"round": mx, "origin_task_id": origin["task_id"], "history": [0.0] * mx,
                              "last_failures": []}
            if action == "revise":
                inputs["generate_tests"] = True
        if cap in (DOCS_GENERATE, DOCS_UPDATE):
            # software: refresh the docs from the changed code; a report project: write the step again from the
            # (re-verified) research with the feedback (docs.update only knows code changes)
            cap = DOCS_UPDATE if software else DOCS_GENERATE
            if changes:
                inputs["feedback"] = "; ".join(changes)[:1500]
        elif changes:
            inputs["feedback"] = "; ".join(changes)[:1500]
        verb = "Fix" if action == "revise" else "Re-run"
        return await manager.create_task(project_id, cap, f"{verb} (review round {round_}): {title}",
                                         acceptance_criteria=[*criteria, *changes][:20], inputs=inputs,
                                         artifact_refs=refs, depends_on=deps, parent_task_id=newest["task_id"])

    async def _replan(self, project_id: str, p: RevisionPlan, manager: ManagerHandle, rec: dict[str, Any],
                      tasks: list[dict[str, Any]]) -> str | None:
        refs = await manager.artifacts.list(project_id)
        graphs = [r for r in refs if r.artifact_type == "task-graph"]
        rss = [r for r in refs if r.artifact_type == "requirement-set"]
        if not graphs or not rss:
            return None
        firsts = [r for r in graphs if r.version == 1] or graphs
        gid = max(firsts, key=lambda r: r.created_at).artifact_id
        graph = max((r for r in graphs if r.artifact_id == gid), key=lambda r: r.version)
        rs = max(rss, key=lambda r: (r.created_at, r.version))
        states = {t["plan_task_id"]: t["state"] for t in tasks if t.get("plan_task_id")}
        feedback = "; ".join(p.required_changes)[:1900]
        return await manager.create_task(project_id, PLAN_REPLAN, f"Replan (review): {feedback[:80]}",
                                         artifact_refs=[graph, rs],
                                         inputs={"feedback": feedback, "failed": [], "states": states,
                                                 "recovery": {**rec, "action": "replan"}},
                                         acceptance_criteria=["finished steps are kept", "every requirement covered"])

