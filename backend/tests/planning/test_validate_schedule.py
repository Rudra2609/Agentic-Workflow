"""Validator + auto-repair (3.4, with property tests on random graphs), scheduling (3.5), coverage (3.6) and the
roadmap (3.7)."""

import networkx as nx
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from hmap.agents.planning import schedule
from hmap.agents.planning.coverage import coverage
from hmap.agents.planning.model import Schedule, WorkingPlan
from hmap.agents.planning.pipeline import finalize, make_plan
from hmap.agents.planning.roadmap import build as build_roadmap
from hmap.agents.planning.validate import check, errors, graph_of, reduce, repair, validate_plan
from hmap.core.contracts.domain import PlanTask, RequirementSet

from .conftest import gold_rs, small_rs

PHASES = ["research", "design", "implement", "test", "document", "review"]
CAPS = {"research": "research.run", "design": "code.implement", "implement": "code.implement", "test": "test.run",
        "document": "docs.generate", "review": "review.final"}


def _t(tid: str, phase: str = "implement", deps: list[str] | None = None, **kw: object) -> PlanTask:
    return PlanTask(id=tid, title=f"Step {tid}", agent_capability=str(kw.pop("cap", CAPS[phase])), phase=phase,
                    depends_on=deps or [], acceptance_criteria=["done"], **kw)


def codes(tasks: list[PlanTask], rs: RequirementSet | None = None) -> set[str]:
    return {i.code for i in check(tasks, rs)}


def test_check_reports_every_kind_of_problem() -> None:
    rs = small_rs()
    assert "cycle" in codes([_t("A", deps=["B"]), _t("B", deps=["A"]), _t("R", "review", ["A"])])
    assert "unknown_dependency" in codes([_t("A", deps=["ghost"])])
    assert "self_dependency" in codes([_t("A", deps=["A"])])
    assert "unknown_capability" in codes([_t("A", cap="deploy.cloud")])
    assert "unknown_capability" in codes([_t("A", cap="plan.generate")])       # never plan inside a plan
    assert "no_acceptance" in codes([PlanTask(id="A", title="x", agent_capability="code.implement")])
    assert "multiple_sinks" in codes([_t("A"), _t("B")])
    assert "sink_not_review" in codes([_t("A")])
    assert "unknown_requirement" in codes([_t("A", requirement_ids=["R99"])], rs)
    assert "uncovered" in codes([_t("A", requirement_ids=["R1"])], rs)
    assert "duplicate_id" in codes([_t("A"), _t("A")])
    warnings = {i.code for i in check([_t("A"), _t("B", "test", ["A"]), _t("R", "review", ["B"])]) if
                i.severity == "warning"}
    assert {"unjustified", "orphan"} <= warnings


def test_repair_fixes_a_broken_model_plan() -> None:
    rs = small_rs()
    plan = WorkingPlan(tasks=[
        _t("research", "research"), _t("design", "design", ["research"]),
        _t("A", requirement_ids=["R1", "R2", "R3", "R9"], cap="deploy.cloud"),
        _t("B", "test", ["A", "ghost"], requirement_ids=["R4"]),
        _t("C", "implement", ["B"]), _t("D", "implement", ["C"]),
    ])
    plan.edge_source.update({("A", "B"): "dataflow", ("B", "C"): "llm", ("C", "D"): "llm"})
    plan.add_edge("D", "A", "llm")          # closes A -> B -> C -> D -> A
    repair(plan, rs)
    left = errors(check(plan.tasks, rs))
    assert not left, left
    a = plan.task("A")
    assert a is not None and a.agent_capability == "code.implement" and "R9" not in a.requirement_ids
    assert nx.is_directed_acyclic_graph(graph_of(plan.tasks))
    assert any("cycle" in r for r in plan.repairs) and any(t.agent_capability == "review.final" for t in plan.tasks)
    edges = {(d, t.id) for t in plan.tasks for d in t.depends_on}
    assert ("A", "B") in edges and ("B", "C") not in edges      # a model edge going back a phase is dropped first


@st.composite
def random_plans(draw: st.DrawFn) -> list[PlanTask]:
    n = draw(st.integers(min_value=1, max_value=14))
    ids = [f"T{i}" for i in range(n)]
    tasks = []
    for i, tid in enumerate(ids):
        deps = draw(st.lists(st.sampled_from(ids), max_size=4, unique=True))   # any direction: cycles allowed
        phase = draw(st.sampled_from(PHASES[:-1]))
        tasks.append(PlanTask(id=tid, title=f"t{i}", agent_capability=draw(st.sampled_from(
            [CAPS[phase], "weird.cap", "code.implement"])), phase=phase, depends_on=deps,
            acceptance_criteria=draw(st.sampled_from([[], ["ok"]]))))
    return tasks


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(random_plans())
def test_repair_always_yields_a_valid_single_sink_dag_and_keeps_every_task(tasks: list[PlanTask]) -> None:
    plan = WorkingPlan(tasks=list(tasks))
    for t in tasks:
        for d in t.depends_on:
            plan.edge_source[(d, t.id)] = "llm"
    repair(plan)
    assert {t.id for t in tasks} <= plan.ids()                       # nothing is thrown away
    hard = [i for i in errors(check(plan.tasks)) if i.code != "uncovered"]
    assert not hard, hard
    g = graph_of(plan.tasks)
    sinks = [n for n in g.nodes if g.out_degree(n) == 0]
    assert len(sinks) == 1 and plan.task(sinks[0]).agent_capability == "review.final"
    before = {n: nx.descendants(g, n) for n in g.nodes}
    reduce(plan)
    g2 = graph_of(plan.tasks)
    assert {n: nx.descendants(g2, n) for n in g2.nodes} == before   # reduction keeps reachability
    assert g2.number_of_edges() <= g.number_of_edges()


def test_schedule_layers_critical_path_and_slack() -> None:
    tasks = [_t("a", est_effort=1), _t("b", deps=["a"], est_effort=5), _t("c", deps=["a"], est_effort=1),
             _t("d", "review", ["b", "c"], est_effort=1)]
    s = schedule.compute(tasks)
    assert s.layers == [["a"], ["b", "c"], ["d"]]
    assert s.critical_path == ["a", "b", "d"] and s.makespan == 7.0 and s.total_effort == 8.0
    assert s.slack["c"] == 4.0 and s.slack["b"] == 0.0 and s.earliest_start["d"] == 6.0
    assert schedule.compute(list(reversed(tasks))) == s               # deterministic, order-independent
    assert schedule.execution_order(tasks) == ["a", "b", "c", "d"]


async def test_priorities_do_not_creep_up_over_versions() -> None:
    rs = gold_rs("tcp_chat")
    first = await make_plan(rs, None)
    from hmap.agents.planning.pipeline import working_plan_from
    again, _ = finalize(working_plan_from(first.graph), rs, kind="software", report=first.report, version=2)
    assert [t.priority for t in again.tasks] == [t.priority for t in first.graph.tasks]


async def test_coverage_matrix_and_roadmap_on_the_gold_plans() -> None:
    for case in ("tcp_chat", "multipart", "long_lab", "adversarial"):
        rs = gold_rs(case)
        result = await make_plan(rs, None)
        g = result.graph
        cov = coverage(list(g.tasks), rs, result.report.flagged)
        assert cov.ratio == 1.0 and not cov.uncovered, case
        assert set(g.coverage_matrix) == {r.id for r in rs.requirements}
        for rid in result.report.flagged:
            assert g.coverage_matrix[rid] == []
        # hierarchy: phase -> part -> group at most, every task in exactly one group
        parents = {p.id: p.parent_id for p in g.roadmap.phases}
        for p in g.roadmap.phases:
            depth, cur = 1, p.parent_id
            while cur is not None:
                depth, cur = depth + 1, parents[cur]
            assert depth <= 3, (case, p.id)
            assert len(p.task_ids) <= 8 or depth == 3, (case, p.id)      # branching limit (spec 3.2)
        members = [tid for p in g.roadmap.phases for tid in p.task_ids]
        assert sorted(members) == sorted(t.id for t in g.tasks), case
        assert g.roadmap.markdown and "## Critical path" in g.roadmap.markdown
        assert [m.name for m in g.roadmap.milestones][-1] == "Ready to hand in"
        assert not validate_plan(g, rs, flagged=result.report.flagged) or all(
            i.severity == "warning" for i in validate_plan(g, rs, flagged=result.report.flagged))
    multipart = await make_plan(gold_rs("multipart"), None)
    assert {m.name for m in multipart.graph.roadmap.milestones} >= {"Part A built and tested",
                                                                     "Part C built and tested"}
    assert "## Not given to an agent" in (await make_plan(gold_rs("adversarial"), None)).graph.roadmap.markdown


def test_roadmap_handles_an_empty_requirement_set() -> None:
    rs = RequirementSet(project_id="P", requirements=[])
    plan = WorkingPlan(tasks=[_t("review", "review")])
    plan.groups.append(("g-review", "Review", None))
    plan.task_group["review"] = "g-review"
    rm = build_roadmap(plan, Schedule(layers=[["review"]], critical_path=["review"]), rs, flagged={}, questions=[])
    assert rm.phases[0].task_ids == ["review"]
