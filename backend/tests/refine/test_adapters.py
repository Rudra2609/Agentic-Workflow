"""Adapters for Member 2's extraction and Member 3's plan (item 4.10), on gold outputs made by their rule fallbacks.
The model is scripted (FakeLLM); Members 2 and 3's folders are only called, never edited."""

import pytest

from hmap.agents.refine import RefineContext, Refiner, ReflectionMemory, default_policy
from hmap.agents.refine.adapters import extraction as ex
from hmap.agents.refine.adapters import plan as pa
from hmap.agents.refine.critics.rubric import RubricAnswer
from hmap.agents.refine.revisers.patch import canonical_bytes
from hmap.core.contracts.domain import RequirementSet
from hmap.core.llm import FakeLLM
from tests.refine.conftest import rules_extraction, rules_plan


def judge(*answers):
    return FakeLLM(default=None).on_schema(RubricAnswer, *answers)


async def test_extraction_critics_on_a_clean_set_find_nothing_major() -> None:
    rs, dm = await rules_extraction("g01_tcp_chat")
    inp = ex.build_input(dm)
    assert ex.check_quotes(rs, inp) == []
    assert ex.check_priority(rs, inp) == []
    assert not [i for i in ex.check_contract(rs, inp) if i.severity in ("major", "critical")]


async def test_quote_check_accepts_lead_in_list_items_and_flags_invented_quotes() -> None:
    rs, dm = await rules_extraction("g10_long_lab")
    inp = ex.build_input(dm)
    assert any(":" in (r.source_ref.quote or "") for r in rs.requirements)          # lead-in items exist ...
    assert ex.check_quotes(rs, inp) == []                                          # ... and are verified
    bad = rs.requirements[0].model_copy(update={"source_ref": rs.requirements[0].source_ref.model_copy(
        update={"quote": "The garage must also launch rockets to the moon."})})
    broken = rs.model_copy(update={"requirements": [bad, *rs.requirements[1:]]})
    [issue] = ex.check_quotes(broken, inp)
    assert issue.category == "HALLUCINATION" and issue.location == bad.id and issue.severity == "major"


async def test_priority_check_and_its_deterministic_fix() -> None:
    rs, dm = await rules_extraction("g09_request")
    inp = ex.build_input(dm)
    should = next(r for r in rs.requirements if "should" in (r.source_ref.quote or ""))
    wrong = rs.model_copy(update={"requirements": [r.model_copy(update={"priority": "must"}) if r.id == should.id
                                                   else r for r in rs.requirements]})
    [issue] = ex.check_priority(wrong, inp)
    assert issue.fix_hint == "set priority=should"
    refiner = Refiner(critics=ex.extraction_critics(inp, judge=False), reviser=ex.ExtractionReviser(),
                      stop=default_policy())
    res = await refiner.run(inp, RefineContext(), output=wrong)               # no model needed for this fix
    fixed = next(r for r in res.final_output.requirements if r.id == should.id)
    assert fixed.priority == "should" and res.improved and res.stop_reason in ("threshold", "no_critical_issues")


async def test_extraction_reviser_adds_only_verifiable_items_and_keeps_the_rest_identical() -> None:
    rs, dm = await rules_extraction("g02_lab_manual")
    inp = ex.build_input(dm)
    missing = "Use pytest.mark.parametrize for the tests of valid dates."
    fake = judge({"criteria": [{"id": "E1", "score": 2}], "issues": [
        {"criterion": "E1", "category": "OMISSION", "severity": "major", "description": "a requirement is missing",
         "location": "requirements", "evidence": missing}]}, {"criteria": [{"id": "E1", "score": 5}], "issues": []})
    fake.on_schema(ex.ChangeAnswer, {"changes": [
        {"op": "add", "kind": "requirement", "text": missing, "quote": missing, "priority": "should"},
        {"op": "add", "kind": "requirement", "text": "Deploy it to the cloud.", "quote": "Deploy it to the cloud."},
        {"op": "add", "kind": "requirement", "text": rs.requirements[0].text,
         "quote": rs.requirements[0].source_ref.quote},
        {"op": "drop", "id": "R1"}]})
    refiner = Refiner(critics=ex.extraction_critics(inp), reviser=ex.ExtractionReviser(), stop=default_policy())
    res = await refiner.run(inp, RefineContext(llm=fake), output=rs)
    out: RequirementSet = res.final_output
    added = out.requirements[-1]
    assert added.text == missing and added.id == f"R{len(rs.requirements) + 1}" and added.source_ref.quote
    rejected = res.attempts[1].rejected_changes
    assert any("not in the documents" in r for r in rejected)          # invented quote refused
    assert any("already listed" in r for r in rejected)                # duplicate refused
    assert any("not flagged" in r for r in rejected)                   # R1 was not flagged: not dropped
    for before in rs.requirements:                                     # unflagged items byte-identical
        after = next(r for r in out.requirements if r.id == before.id)
        assert canonical_bytes(after.model_dump(mode="json")) == canonical_bytes(before.model_dump(mode="json"))
    assert out.constraints == rs.constraints and out.deliverables == rs.deliverables


async def test_judge_saying_a_verified_quote_is_invented_is_contradicted() -> None:
    rs, dm = await rules_extraction("g01_tcp_chat")
    inp = ex.build_input(dm)
    fake = judge({"criteria": [{"id": "E2", "score": 1}], "issues": [
        {"criterion": "E2", "category": "HALLUCINATION", "severity": "major",
         "description": "R1 is not in the document", "location": "R1"}]})
    critique = await ex.ExtractionJudge().review(rs, inp, RefineContext(llm=fake))
    assert critique.issues == []


async def test_plan_critics_and_dependency_patch_through_finalize() -> None:
    graph, report, rs = await rules_plan("tcp_chat")
    inp = pa.PlanInput(requirements=rs, report=report)
    assert pa.check_validity(graph, inp) == [] and pa.check_coverage(graph, inp) == []
    fake = judge({"criteria": [{"id": "P1", "score": 2}], "issues": [
        {"criterion": "P1", "category": "LOGIC", "severity": "major", "description": "T3 needs T1's nicknames",
         "location": "T1 -> T3"}]}, {"criteria": [{"id": "P1", "score": 5}], "issues": []})
    fake.on_schema(pa.PlanChangeAnswer, {"changes": [
        {"op": "add_dependency", "before": "T1", "after": "T3"},
        {"op": "add_dependency", "before": "T3", "after": "T1"},                  # a cycle now: refused
        {"op": "add_dependency", "before": "T2", "after": "T6"},                  # not flagged: refused
        {"op": "add_requirement", "task": "T1", "requirement": "R99"}]})          # unknown: refused
    setup = pa.plan_setup(inp)
    res = await Refiner(critics=setup.critics, reviser=setup.reviser, stop=default_policy()).run(
        inp, RefineContext(llm=fake), output=graph)
    new = res.final_output
    t3 = next(t for t in new.tasks if t.id == "T3")
    assert "T1" in t3.depends_on and res.best_index == 1
    rejected = " | ".join(res.attempts[1].rejected_changes)
    assert "cycle" in rejected and "not flagged" in rejected and "unknown" in rejected
    from hmap.agents.planning.validate import errors, validate_plan

    assert not errors(validate_plan(new, rs, flagged=report.flagged))       # still a valid plan (Member 3's checks)
    assert {t.id for t in new.tasks} == {t.id for t in graph.tasks}


async def test_plan_add_requirement_and_reflexion_switches_to_replan() -> None:
    graph, report, rs = await rules_plan("tcp_chat")
    inp = pa.PlanInput(requirements=rs, report=report)
    stuck = {"criteria": [{"id": "P2", "score": 2}], "issues": [
        {"criterion": "P2", "category": "OMISSION", "severity": "major",
         "description": "R7 is never built; add it to T1", "location": "R7"}]}
    fake = judge(stuck)
    fake.on_schema(pa.PlanChangeAnswer, {"changes": [{"op": "add_requirement", "task": "T1", "requirement": "R7"}]})
    from hmap.agents.planning.replan import ReplanDraft

    fake.on_schema(ReplanDraft, {"remove": [], "change": [], "add": [], "notes": "no change"})
    memory = ReflectionMemory("plan.generate")
    setup = pa.plan_setup(inp)
    res = await Refiner(critics=setup.critics, reviser=setup.reviser, stop=default_policy(max_iters=2),
                        memory=memory).run(inp, RefineContext(llm=fake), output=graph)
    t1 = next(t for t in res.attempts[1].output.tasks if t.id == "T1")
    assert "R7" in t1.requirement_ids                                     # targeted fix applied
    assert [a.strategy for a in res.attempts] == [None, "targeted", "full"]   # same problem again -> replan
    assert any("replanned" in n for n in res.attempts[2].revision_notes)


@pytest.mark.parametrize("case", ["g03_rubric", "g05_photo", "g08_multipart"])
async def test_render_and_windows_cover_every_document(case: str) -> None:
    rs, dm = await rules_extraction(case)
    inp = ex.build_input(dm)
    wins = ex.windows(inp)
    assert {d.doc_id for w in wins for d, _ in w} == {d.doc_id for d in dm.documents}
    text = ex.render_window(rs, wins[0], True)
    assert "=== Extracted items" in text
    small = ex.windows(inp, limit=200)
    assert len(small) >= len(wins)



async def test_a_rubric_without_requirements_is_not_flagged_and_criteria_are_not_copied() -> None:
    rs, dm = await rules_extraction("g03_rubric")
    inp = ex.build_input(dm)
    assert not rs.requirements and rs.evaluation_criteria
    assert not [i for i in ex.check_contract(rs, inp) if i.location == "requirements"]
    crit = rs.evaluation_criteria[0]
    assert ex._duplicate(rs, "requirement", crit.criterion, crit.source_ref.quote) == crit.id
