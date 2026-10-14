"""Replanning (3.10) and human edits (3.12): finished and running steps are never touched, feedback reaches the
unfinished part only, changed requirements are followed, and edits are validated before they become a version."""

from hmap.agents.planning.decompose import DraftStep
from hmap.agents.planning.pipeline import PlanResult, make_plan
from hmap.agents.planning.replan import ReplanDraft, TaskChange, apply_edit, replan
from hmap.core.contracts.domain import RequirementSet
from hmap.core.llm import FakeLLM, LLMProviderError

from .conftest import gold_rs, req, small_rs


async def _plan() -> tuple[RequirementSet, PlanResult]:
    rs = gold_rs("tcp_chat")
    return rs, await make_plan(rs, None)


def _states(result: PlanResult, done: set[str], running: set[str] = frozenset()) -> dict[str, str]:  # type: ignore[assignment]
    return {t.id: ("COMPLETED" if t.id in done else "RUNNING" if t.id in running else "CREATED")
            for t in result.graph.tasks}


async def test_rule_replan_keeps_finished_steps_and_adds_the_feedback() -> None:
    rs, first = await _plan()
    done = {"research", "verify", "design"}
    builds = [t for t in first.graph.tasks if t.phase == "implement"]
    states = _states(first, done | {builds[0].id}, running={builds[1].id})
    result = await replan(first.graph, rs, states=states, feedback="Don't use threads.", previous=first.report)
    g = result.graph
    old = {t.id: t for t in first.graph.tasks}
    for tid in done | {builds[0].id, builds[1].id}:
        new = next(t for t in g.tasks if t.id == tid)
        assert (new.title, new.acceptance_criteria, new.requirement_ids) == (
            old[tid].title, old[tid].acceptance_criteria, old[tid].requirement_ids)      # frozen
    unfinished = [t for t in g.tasks if t.phase in ("implement", "test") and states.get(t.id, "CREATED") == "CREATED"]
    assert unfinished and all("Do not use threads" in t.acceptance_criteria for t in unfinished)
    assert g.version == first.graph.version + 1 and result.report.origin == "replanned"
    assert result.report.feedback == "Don't use threads." and result.report.method == "rules"


async def test_model_replan_cannot_touch_frozen_steps() -> None:
    rs, first = await _plan()
    builds = [t for t in first.graph.tasks if t.phase == "implement"]
    frozen, editable = builds[0], builds[1]
    states = _states(first, {"research", "verify", "design", frozen.id})
    draft = ReplanDraft(
        remove=[frozen.id, editable.id],
        change=[TaskChange(id=frozen.id, title="Rewritten")],
        add=[DraftStep(key="n1", title="Use asyncio streams", requirement_ids=editable.requirement_ids,
                       depends_on=[frozen.id])])
    llm = FakeLLM().on_schema(ReplanDraft, draft.model_dump_json())
    result = await replan(first.graph, rs, states=states, feedback="Use asyncio, not threads.", llm=llm,
                          previous=first.report)
    ids = {t.id for t in result.graph.tasks}
    assert frozen.id in ids and editable.id not in ids
    assert next(t for t in result.graph.tasks if t.id == frozen.id).title == frozen.title
    new = next(t for t in result.graph.tasks if t.title == "Use asyncio streams")
    assert frozen.id in new.depends_on or any(frozen.id in t.depends_on for t in result.graph.tasks)
    assert set(new.requirement_ids) == set(editable.requirement_ids) and new.id not in {t.id for t in
                                                                                         first.graph.tasks}
    assert any(f"kept {frozen.id}" in r for r in result.report.repairs) and result.report.method == "llm"
    assert set(result.graph.coverage_matrix) == {r.id for r in rs.requirements}


async def test_model_failure_during_replan_uses_the_rules() -> None:
    rs, first = await _plan()

    def broken(_call: object) -> ReplanDraft:
        raise LLMProviderError("down")

    result = await replan(first.graph, rs, states=_states(first, set()), feedback="avoid recursion",
                          llm=FakeLLM().on_schema(ReplanDraft, broken), previous=first.report)
    assert result.report.fallbacks and any("Do not use recursion" in c for t in result.graph.tasks
                                           for c in t.acceptance_criteria)


async def test_failed_steps_run_again_and_changed_requirements_are_followed() -> None:
    rs, first = await _plan()
    builds = [t for t in first.graph.tasks if t.phase == "implement"]
    states = _states(first, {"research", "verify", "design"})
    states[builds[0].id] = "FAILED"
    # R8 removed by a person, R9 added
    changed = rs.model_copy(update={"requirements": [r for r in rs.requirements if r.id != "R8"] + [
        RequirementSet.model_validate({"project_id": "P", "requirements": [
            req("R9", "The server must log every connection to a file.")]}).requirements[0]]})
    result = await replan(first.graph, changed, states=states, previous=first.report)
    g = result.graph
    again = next(t for t in g.tasks if t.id == builds[0].id)
    assert "previous attempt failed" in again.description
    assert all("R8" not in t.requirement_ids for t in g.tasks)
    assert g.coverage_matrix["R9"] and "R8" not in g.coverage_matrix


async def test_edit_is_validated_then_becomes_the_next_version() -> None:
    rs = small_rs()
    first = await make_plan(rs, None)
    base = first.graph
    data = base.model_dump(mode="json")
    builds = [t for t in data["tasks"] if t["phase"] == "implement"]
    # a cycle is refused, with the reason
    bad = {**data, "tasks": [dict(t, depends_on=[*t["depends_on"], "review"]) if t["id"] == builds[0]["id"] else t
                             for t in data["tasks"]]}
    _, _, problems = apply_edit(bad, rs, base=base, kind="software", previous=first.report)
    assert [p.code for p in problems] == ["cycle"]
    # an invented capability is refused
    bad2 = {**data, "tasks": [dict(t, agent_capability="deploy.cloud") if t["id"] == builds[0]["id"] else t
                              for t in data["tasks"]]}
    assert [p.code for p in apply_edit(bad2, rs, base=base, kind="software")[2]] == ["unknown_capability"]
    # a finished step cannot change
    bad3 = {**data, "tasks": [dict(t, title="Something else") if t["id"] == "research" else t for t in data["tasks"]]}
    assert [p.code for p in apply_edit(bad3, rs, base=base, kind="software", states={"research": "COMPLETED"})[2]] \
        == ["frozen_changed"]
    # a good edit: a new step without criteria or edges -> repaired, connected, next version
    good = {**data, "tasks": [*data["tasks"], {"id": "X1", "title": "Add a /quit command",
                                               "agent_capability": "code.implement", "phase": "implement",
                                               "requirement_ids": ["R1"]}]}
    graph, report, problems = apply_edit(good, rs, base=base, kind="software", author="user:u1",
                                         previous=first.report)
    assert not problems and graph.version == base.version + 1 and report.origin == "edited"
    x1 = next(t for t in graph.tasks if t.id == "X1")
    assert x1.acceptance_criteria and x1.depends_on == ["design"]
    assert report.author == "user:u1" and any("X1" in r for r in report.repairs)
    assert "X1" in graph.coverage_matrix["R1"]


async def test_feedback_after_everything_finished_becomes_a_change_request() -> None:
    rs, first = await _plan()
    states = _states(first, {t.id for t in first.graph.tasks})                 # the whole plan is done
    result = await replan(first.graph, rs, states=states, feedback="Do not use threads.", previous=first.report)
    g = result.graph
    ids = {t.id for t in g.tasks}
    builds = [t.id for t in first.graph.tasks if t.phase in ("implement", "test", "research", "design")]
    assert set(builds) <= ids                                                    # finished work kept, same ids
    change = [t for t in g.tasks if t.title.startswith("Change request")]
    assert len(change) == 1 and "Do not use threads" in change[0].acceptance_criteria
    assert "review" not in ids and f"review-v{first.graph.version + 1}" in ids  # the review runs again
    review = next(t for t in g.tasks if t.phase == "review")
    import networkx as nx

    from hmap.agents.planning.validate import graph_of
    assert nx.has_path(graph_of(g.tasks), change[0].id, review.id)
