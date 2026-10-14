"""Critics (item 4.3): programmatic, LLM rubric (judge role, evidence + valid location), composite (D8)."""

import pytest

from hmap.agents.refine import CompositeCritic, Criterion, LLMRubricCritic, ProgrammaticCritic, Rubric
from hmap.agents.refine.core import Critique, RefineContext
from hmap.agents.refine.critics.rubric import RubricAnswer
from hmap.agents.refine.refiner import Refiner
from hmap.agents.refine.trace import iteration_record
from hmap.core.llm import FakeLLM
from tests.refine.conftest import ScriptedCritic, issue

RUBRIC = Rubric(name="t", subject="a test output", criteria=(Criterion("A", "complete?", 2.0, "OMISSION"),
                                                             Criterion("B", "faithful?", 1.0, "HALLUCINATION")))


async def test_programmatic_critic_shapes() -> None:
    ctx = RefineContext()
    by_issues = ProgrammaticCritic(lambda o, i: [issue(severity="major"), issue(severity="minor")], name="c")
    c = await by_issues.review(1, None, ctx)
    assert c.score == pytest.approx(0.75) and len(c.issues) == 2 and c.critic == "c"
    tupled = ProgrammaticCritic(lambda o, i: (0.3, [issue()]))
    assert (await tupled.review(1, None, ctx)).score == 0.3

    async def with_ctx(o, i, ctx):
        return Critique(score=0.5, issues=[])
    assert (await ProgrammaticCritic(with_ctx, name="w").review(1, None, ctx)).critic == "w"
    assert (await ProgrammaticCritic(lambda o, i: [issue(severity="critical")] * 3).review(1, None, ctx)).score == 0.0


async def test_rubric_critic_scores_criteria_and_drops_issues_without_a_valid_location() -> None:
    fake = FakeLLM().on_schema(RubricAnswer, {
        "criteria": [{"id": "A", "score": 3, "evidence": "x"}, {"id": "B", "score": 5}],
        "issues": [{"criterion": "A", "category": "OMISSION", "severity": "major", "description": "R9 missing",
                    "location": "R2", "evidence": "the text"},
                   {"criterion": "A", "category": "omission", "severity": "MAJOR", "description": "vague",
                    "location": ""},
                   {"criterion": "B", "category": "nonsense", "severity": "info", "description": "where?",
                    "location": "R77"}]})
    critic = LLMRubricCritic(RUBRIC, locations=lambda o, i: ["R1", "R2"])
    ctx = RefineContext(llm=fake)
    c = await critic.review({"x": 1}, None, ctx)
    assert c.score == pytest.approx((2 * 0.5 + 1 * 1.0) / 3, abs=1e-3)
    assert [i.location for i in c.issues] == ["R2"]
    assert len(critic.dropped) == 2
    assert fake.calls[0].role == "judge"
    # the same material is not judged twice (cache, plan D10); tokens are counted
    await critic.review({"x": 1}, None, ctx)
    assert len(fake.calls) == 1 and ctx.usage.calls == 1 and ctx.usage.tokens > 0


async def test_rubric_critic_counts_skipped_criteria_as_met_unless_it_raised_an_issue() -> None:
    fake = FakeLLM().on_schema(RubricAnswer, {"criteria": [], "issues": [
        {"criterion": "B", "category": "HALLUCINATION", "severity": "major", "description": "R1 invented",
         "location": "R1"}]})
    c = await LLMRubricCritic(RUBRIC).review({}, None, RefineContext(llm=fake))
    assert c.score == pytest.approx((2 * 1.0 + 1 * 0.5) / 3, abs=1e-3)


async def test_composite_programmatic_first_caps_and_overrides() -> None:
    prog = ScriptedCritic([Critique(score=1.0, issues=[issue("HALLUCINATION", "major", "R1")])], name="quotes",
                          covers=frozenset({"SCHEMA"}))
    clean_schema = ScriptedCritic([Critique(score=1.0, issues=[])], name="schema", covers=frozenset({"SCHEMA"}))
    llm = ScriptedCritic([Critique(score=1.0, issues=[
        issue("SCHEMA", "major", "R2"),                       # contradicted: the schema check passed
        issue("HALLUCINATION", "major", "R1"),                # a repeat of a programmatic finding
        issue("HALLUCINATION", "major", "R1", evidence="new"),  # a repeat WITH evidence: kept
        issue("OMISSION", "minor", "R3")])], name="judge", kind="llm")
    merged, parts = await CompositeCritic([llm, prog, clean_schema]).review_all("out", None,
                                                                              RefineContext(llm=FakeLLM()))
    assert [p.critic for p in parts] == ["quotes", "schema", "judge"]           # programmatic first
    assert merged.score == 0.75                                                 # capped by the major finding
    judge = parts[2]
    assert [(i.category, i.location, i.evidence) for i in judge.issues] == [
        ("HALLUCINATION", "R1", "new"), ("OMISSION", "R3", None)]


async def test_composite_soft_cap_for_llm_findings_and_weights() -> None:
    a = ScriptedCritic([Critique(score=1.0)], name="a")
    j = ScriptedCritic([Critique(score=1.0, issues=[issue(severity="major")])], name="j", kind="llm")
    merged, _ = await CompositeCritic([a, j]).review_all(1, None, RefineContext(llm=FakeLLM()))
    assert merged.score == 0.85
    b = ScriptedCritic([Critique(score=0.0)], name="b")
    merged, _ = await CompositeCritic([a, b], weights={"b": 3.0}).review_all(1, None, RefineContext())
    assert merged.score == 0.25


async def test_composite_skips_llm_critics_without_a_model_and_survives_their_failure() -> None:
    prog = ScriptedCritic([Critique(score=0.9)], name="p")

    class Broken:
        name, kind = "judge", "llm"

        async def review(self, output, task_input, ctx):
            raise RuntimeError("model down")

    comp = CompositeCritic([prog, Broken()])
    merged, parts = await comp.review_all(1, None, RefineContext())         # no model: judge not even called
    assert merged.score == 0.9 and len(parts) == 1
    merged, parts = await comp.review_all(1, None, RefineContext(llm=FakeLLM()))
    assert len(parts) == 1 and comp.errors == ["judge: RuntimeError"]
    # the loop records the skipped judge in the round, so the trace / UI / eval say "code checks only"
    res = await Refiner(critics=[ScriptedCritic([Critique(score=0.95)], name="p"), Broken()]).run(
        None, RefineContext(llm=FakeLLM()), output=1)
    assert res.attempts[0].critic_errors == ["judge: RuntimeError"]
    assert iteration_record(res.attempts[0], None).critic_errors == ["judge: RuntimeError"]
    with pytest.raises(ValueError):
        CompositeCritic([])
