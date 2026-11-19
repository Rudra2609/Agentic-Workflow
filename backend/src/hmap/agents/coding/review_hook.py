"""Self-review before returning (Sprint 7 item 7.11): Member 4's ``Refiner`` around the finished change.

- Always: a ``ProgrammaticCritic`` turns the agent's own check results into issues (a compile / import failure is
  critical, failing tests or lint errors are major, no change at all is an omission). Code findings are facts.
- When the task asks for refinement (``task.refine``, the project's "Check and improve results" setting): also an
  ``LLMRubricCritic`` (role ``judge``) asks whether the diff meets every acceptance criterion, and a reviser runs
  **one** more fix round through the coding loop with the critique as requested changes.

The best attempt is kept (Member 4's regression guard). The result is summarised in the coding trace
(``review`` notes, score), not as a ``refinement-trace`` artifact: Member 4's Refinement tab expects its own run
record, and the coding tab already shows every round.
"""

from collections.abc import Sequence
from typing import Any

from hmap.agents.coding.loop import CodingLoop, NoModel, StepBudget
from hmap.agents.coding.workspace import changed_files, unified_diff
from hmap.agents.refine import LLMRubricCritic, ProgrammaticCritic, RefineContext, Refiner, Revision
from hmap.agents.refine.critics.rubric import Criterion, Rubric
from hmap.agents.refine.stop import MaxIters, NoCritical, any_of
from hmap.core.contracts.domain import Critique, Issue
from hmap.core.errors import Cancelled

CODE_RUBRIC = Rubric(
    name="code-change", subject="a code change (unified diff) made for a task with acceptance criteria",
    criteria=(Criterion("A1", "Does the change meet every acceptance criterion of the task?", 2.0,
                        "REQUIREMENT_VIOLATION"),
              Criterion("A2", "Is the changed code free of obvious bugs (wrong logic, unhandled cases, crashes)?",
                        1.0, "LOGIC")),
    location_hint="a file path from the diff")
SEVERITY = {"compile": "critical", "imports": "critical", "tests": "major", "lint": "major"}


def output_of(loop: CodingLoop) -> dict[str, Any]:
    files = loop.ws.snapshot()
    return {"files": files, "changed": changed_files(loop.before, files),
            "checks": [c.model_dump() for c in loop.t.checks], "diff": unified_diff(loop.before, files)}


def check_issues(output: dict[str, Any], task_input: dict[str, Any]) -> list[Issue]:
    issues = []
    for c in output.get("checks", []):
        if c["status"] == "failed":
            issues.append(Issue(category="LOGIC" if c["name"] != "lint" else "FORMAT",
                                severity=SEVERITY.get(c["name"], "major"),
                                description=f"{c['name']} check fails: {(c.get('detail') or '')[-300:]}".strip(),
                                fix_hint=f"make the {c['name']} check pass"))
    if not output.get("changed") and task_input.get("expects_change"):
        issues.append(Issue(category="OMISSION", severity="major", description="no file was changed",
                            fix_hint="make the change the task asks for"))
    return issues


def render(output: dict[str, Any], task_input: dict[str, Any]) -> str:
    checks = ", ".join(f"{c['name']}={c['status']}" for c in output.get("checks", [])) or "none"
    diff = output.get("diff") or "(no change)"
    if len(diff) > 9000:
        diff = diff[:6000] + "\n…[diff cut]…\n" + diff[-3000:]
    return f"{task_input['task']}\n\nChecks: {checks}\n\nDiff:\n{diff}"


class LoopReviser:
    """One more fix round through the coding loop, with the critique as the requested changes."""

    name = "coding-loop"

    def __init__(self, loop: CodingLoop) -> None:
        self.loop = loop

    async def revise(self, output: Any, critique: Critique, history: Sequence[Any], ctx: RefineContext, *,
                     task_input: Any = None, strategy: str = "targeted") -> Revision:
        loop = self.loop
        wanted = [i.fix_hint or i.description for i in critique.issues][:5]
        loop.job.task.required_changes = [*loop.job.task.required_changes, *wanted]
        focus = (output.get("changed") or [p["path"] for p in loop.t.located[:2]])[:3]
        try:
            fixed = await loop.edit(None, focus, kind="review",
                                    failures="\n".join(f"[{i.severity} {i.category}] {i.description}"
                                                       for i in critique.issues[:6]),
                                    output=loop.last_run.failures_for_model(2500) if loop.last_run else "")
        except (NoModel, StepBudget) as exc:
            return Revision(output=output, notes=[f"review fix skipped: {type(exc).__name__}"], applied=0)
        if fixed:
            await loop.run_checks(sorted(set(output.get("changed") or []) | set(fixed)))
        return Revision(output=output_of(loop), notes=[f"review fix changed {', '.join(fixed) or 'nothing'}"],
                        applied=len(fixed))


async def review(loop: CodingLoop, *, use_judge: bool) -> None:
    """Run the self-review; leaves the workspace at the best attempt and notes the result in the trace."""
    t = loop.t
    task_input = {"task": loop.job.task.text(), "expects_change": loop.job.task.kind == "revise" or not t.template}
    critics: list[Any] = [ProgrammaticCritic(check_issues, name="checks", covers={"FORMAT"})]
    if use_judge and loop.job.llm is not None:
        critics.append(LLMRubricCritic(CODE_RUBRIC, render=render))
    can_revise = use_judge and loop.job.llm is not None and t.stop_reason not in ("no_model", "step_budget")
    refiner = Refiner(critics=critics, reviser=LoopReviser(loop) if can_revise else None,
                      stop=any_of(NoCritical("major"), MaxIters(1)), name="code-review", producer_name="coding-loop")
    ctx = RefineContext(llm=loop.job.llm, check_cancelled=loop.check_cancelled)
    current = output_of(loop)
    result = await refiner.run(task_input, ctx, output=current)
    if result.stop_reason == "cancelled":
        raise Cancelled("execution cancelled during the self-review")
    best = result.final_output
    if best["files"] != loop.ws.snapshot():
        loop.ws.restore(best["files"])
        await loop.run_checks(best["changed"] or None)
    scores = ", ".join(f"{a.score:.2f}" for a in result.attempts)
    issues = "; ".join(i.description[:80] for i in result.attempts[result.best_index].critique.issues[:3])
    t.notes.append(f"self-review ({'checks + judge' if use_judge else 'checks'}): scores {scores}, kept attempt "
                   f"{result.best_index}, stop {result.stop_reason}" + (f"; open: {issues}" if issues else ""))
    if result.error:
        t.notes.append(f"self-review error: {result.error[:200]}")
