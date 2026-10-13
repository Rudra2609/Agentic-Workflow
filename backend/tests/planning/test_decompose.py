"""Skeleton (3.1), decomposition (3.2) and dependency inference (3.3): the template spine, parts per folder, things
only a person can do, the model call and its rule fallback, and the edges each source adds."""

from hmap.agents.planning.decompose import DraftPlan, DraftStep, NotPlannable, build_messages, rule_draft
from hmap.agents.planning.model import PROMPT_VERSION
from hmap.agents.planning.pipeline import make_plan
from hmap.agents.planning.skeleton import Part, build_parts, build_skeleton, human_only, review_questions, section_map
from hmap.agents.planning.templates import PLAN_CAPABILITIES, detect_kind
from hmap.agents.planning.validate import graph_of
from hmap.core.contracts import Priority
from hmap.core.contracts.domain import RequirementSet
from hmap.core.llm import FakeLLM, LLMProviderError

from .conftest import gold_rs, gold_sections, req, small_rs


def test_whitelist_never_contains_the_planning_steps_themselves() -> None:
    assert "plan.generate" not in PLAN_CAPABILITIES and "document.extract" not in PLAN_CAPABILITIES
    assert {"research.run", "verify.claims", "code.implement", "test.run", "docs.generate", "review.final"} == set(
        PLAN_CAPABILITIES)


def test_project_kind() -> None:
    assert detect_kind(["Implement a TCP server in Python"]) == "software"
    assert detect_kind(["Write a 2000-word report and discuss the literature", "Include references"]) == "document"
    assert detect_kind(["Do the thing"]) == "software"       # ties go to software


def test_skeleton_is_the_spine_with_review_criteria() -> None:
    rs = small_rs(evaluation_criteria=[{"id": "E1", "criterion": "Works", "max_marks": 10}], total_marks=10)
    plan, kind = build_skeleton(rs)
    assert kind == "software" and [t.id for t in plan.tasks] == ["research", "verify", "design", "review"]
    review = plan.task("review")
    assert review is not None and review.agent_capability == "review.final" and not review.requirement_ids
    assert any("C1 respected" in c for c in review.acceptance_criteria)
    assert any("D2 handed in" in c for c in review.acceptance_criteria)
    assert any("1 criteria, 10 marks" in c for c in review.acceptance_criteria)
    assert plan.edge_source[("research", "verify")] == "template"


def test_parts_follow_upload_folders_and_sections() -> None:
    rs = gold_rs("multipart")
    parts = build_parts(rs, section_map(gold_sections("multipart")))
    assert [p.name for p in parts] == ["Part A", "Part B", "Part C"] and [p.id for p in parts] == ["p1", "p2", "p3"]
    assert [r.id for r in parts[1].requirements] == ["R3", "R4", "R5", "R6"]
    single = build_parts(small_rs())
    assert len(single) == 1 and single[0].name == "" and single[0].label == "the work"
    mixed = RequirementSet.model_validate({"project_id": "P", "requirements": [
        req("R1", "a", folder="Part A"), req("R2", "b", folder="Part B"), req("R3", "c")]})
    assert [p.name for p in build_parts(mixed)] == ["Part A", "Part B", "General"]


def test_things_only_a_person_can_do_are_flagged() -> None:
    rs = gold_rs("adversarial")
    assert set(human_only(rs)) == {"R4", "R5"}                 # demo in person, upload to Moodle
    assert set(human_only(gold_rs("rubric"))) == {"R1"}         # every member presents the demo
    assert human_only(gold_rs("project_brief")) == {}           # "attendees", "download" are fine
    questions, low = review_questions(rs)
    assert low == ["R3"] and "Which email provider may be used?" in questions
    assert any(q.startswith("Is R3 right?") for q in questions)


def test_rule_draft_groups_and_tests_every_build_step() -> None:
    rs = small_rs()
    part = Part("p1", "", list(rs.requirements))
    draft = rule_draft(part, list(rs.requirements), "software")
    builds = [s for s in draft.steps if s.phase == "implement"]
    tests = [s for s in draft.steps if s.phase == "test"]
    assert [s.requirement_ids for s in builds] == [["R1", "R2", "R3"]]      # functional, in runs of 3
    assert any(s.requirement_ids == ["R4"] and s.group == "Quality" for s in tests)  # quality -> tests
    assert all(t.depends_on for t in tests)


def test_prompt_lists_requirements_constraints_and_part() -> None:
    rs = gold_rs("multipart")
    parts = build_parts(rs)
    messages = build_messages(parts[1], parts[1].requirements, rs, "software")
    user = messages[1].content
    assert "Part: Part B." in user and "R6 [must, functional] Use the schema from Part A." in user
    assert "R1" not in user.split("Requirements:")[1].split("Constraints")[0]   # only this part's requirements
    assert "Never invent requirements" in messages[0].content and PROMPT_VERSION == "2"


async def test_model_plan_is_cleaned_and_whitelisted() -> None:
    rs = small_rs()
    draft = DraftPlan(
        steps=[DraftStep(key="b1", title="Accept many clients", requirement_ids=["R1", "R99"], effort_hours=99,
                         capability="deploy.cloud", group="Networking"),
               DraftStep(key="b2", title="Nicknames and private messages", requirement_ids=["R2", "R3"],
                         depends_on=["b1"], acceptance_criteria=[], group="Messaging"),
               DraftStep(key="t1", title="Test it", phase="test", requirement_ids=["R1", "R2", "R3", "R4"],
                         depends_on=["b1", "b2", "ghost"])],
        research_questions=["Threads or asyncio for many sockets?"],
        not_plannable=[NotPlannable(requirement_id="R99", reason="?")])
    llm = FakeLLM().on_schema(DraftPlan, draft.model_dump_json())
    result = await make_plan(rs, llm)
    g = result.graph
    by_title = {t.title: t for t in g.tasks}
    b1 = by_title["Accept many clients"]
    assert b1.requirement_ids == ["R1"] and b1.agent_capability == "code.implement"     # unknown id / capability fixed
    assert b1.est_effort == 16.0                                                         # effort clamped
    assert b1.acceptance_criteria and by_title["Nicknames and private messages"].acceptance_criteria[0].startswith("R2")
    assert result.report.method == "llm" and result.report.llm_calls == 1
    assert next(t for t in g.tasks if t.id == "research").research_questions == ["Threads or asyncio for many "
                                                                                 "sockets?"]
    assert all(t.agent_capability in PLAN_CAPABILITIES for t in g.tasks)
    assert {phase.name for phase in g.roadmap.phases} >= {"Build", "Networking", "Messaging"}
    call = llm.calls[0]
    assert call.role == "reasoner" and call.temperature == 0.0


async def test_model_failure_or_empty_answer_falls_back_to_rules_and_says_so() -> None:
    def broken(_call: object) -> DraftPlan:
        raise LLMProviderError("down")

    rs = small_rs()
    failed = await make_plan(rs, FakeLLM().on_schema(DraftPlan, broken))
    assert failed.report.method == "rules" and failed.report.fallbacks == ["the work: LLMProviderError"]
    empty = await make_plan(rs, FakeLLM().on_schema(DraftPlan, DraftPlan().model_dump_json()))
    assert empty.report.fallbacks == ["the work: empty answer"]
    for r in (failed, empty):
        assert set(r.graph.coverage_matrix) == {"R1", "R2", "R3", "R4"} and all(r.graph.coverage_matrix.values())


async def test_cache_means_no_second_model_call() -> None:
    from hmap.agents.planning.agent import LruCache

    rs = small_rs()
    llm = FakeLLM().on_schema(DraftPlan, rule_draft(Part("p1", "", list(rs.requirements)), list(rs.requirements),
                                                     "software").model_dump_json())
    cache = LruCache()
    a = await make_plan(rs, llm, cache=cache)
    b = await make_plan(rs, llm, cache=cache)
    assert len(llm.calls) == 1 and a.graph == b.graph and b.report.answered_by == {"memory": 1}


async def test_dependencies_from_templates_dataflow_and_parts() -> None:
    result = await make_plan(gold_rs("multipart"), None, document_model=gold_sections("multipart"))
    g = graph_of(result.graph.tasks)
    tasks = {t.id: t for t in result.graph.tasks}
    builds = {r: t.id for t in result.graph.tasks if t.phase == "implement" for r in t.requirement_ids}
    import networkx as nx
    assert nx.has_path(g, builds["R1"], builds["R6"])           # Part B "uses the schema from Part A"
    assert nx.has_path(g, builds["R3"], builds["R7"])           # Part C tests Part B's endpoints
    for t in tasks.values():
        if t.phase == "test":
            assert any(nx.has_path(g, b, t.id) for b in builds.values())
    assert [n for n in g.nodes if g.out_degree(n) == 0] == ["review"]
    assert result.report.edges.get("template", 0) > 0 and result.report.edges.get("dataflow", 0) > 0


async def test_priorities_follow_moscow_and_the_critical_path() -> None:
    result = await make_plan(gold_rs("tcp_chat"), None)
    crit = set(result.report.schedule.critical_path)
    for t in result.graph.tasks:
        if t.id in crit and t.requirement_ids:
            assert t.priority in (Priority.URGENT, Priority.HIGH)
    assert next(t for t in result.graph.tasks if t.id == "research").priority == Priority.HIGH  # normal, +critical
