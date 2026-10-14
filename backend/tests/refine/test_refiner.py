"""The loop (item 4.2): deterministic, keeps the best attempt, accounts tokens and time, honours cancellation,
budgets and errors; the trace matches the shared contract."""

import asyncio

import pytest

from hmap.agents.refine import GENERIC_RUBRIC, LLMRubricCritic, RefineContext, Refiner
from hmap.agents.refine.core import Critique, RefinementTrace
from hmap.agents.refine.critics.rubric import RubricAnswer
from hmap.agents.refine.stop import Budget, MaxIters, Threshold, any_of
from hmap.core.errors import Cancelled
from hmap.core.llm import FakeLLM
from tests.refine.conftest import CountingReviser, ScoreByOutput, ScriptedCritic, issue


async def test_self_refine_improves_until_the_threshold_and_records_everything() -> None:
    critic = ScoreByOutput({0: 0.2, 1: 0.6, 2: 0.95})
    reviser = CountingReviser()
    result = await Refiner(critics=[critic], reviser=reviser, stop=any_of(Threshold(0.9), MaxIters(3))).run(
        None, output=0)
    assert [a.score for a in result.attempts] == [0.2, 0.6, 0.95]
    assert result.stop_reason == "threshold" and result.final_output == 2 and result.best_index == 2
    assert result.improved and result.iterations == 2 and reviser.strategies == ["targeted", "targeted"]
    assert result.attempts[1].revision_notes == ["0 -> 1"]
    trace = RefinementTrace.model_validate(result.trace.model_dump())
    assert trace.stop_reason == "threshold" and trace.best_iteration == 2 and len(trace.iterations) == 3
    assert trace.spec.critics == ["by-output"] and trace.spec.reviser == "counter"


async def test_regression_guard_returns_the_best_not_the_last() -> None:
    critic = ScoreByOutput({0: 0.5, 1: 0.8, 2: 0.3, 3: 0.4})
    result = await Refiner(critics=[critic], reviser=CountingReviser(), stop=MaxIters(3)).run(None, output=0)
    assert result.stop_reason == "max_iters" and result.final_output == 1 and result.best_score == 0.8


async def test_deterministic_with_fake_llm() -> None:
    def make() -> Refiner:
        fake = FakeLLM().on_schema(RubricAnswer, {"criteria": [{"id": "G1", "score": 2}], "issues": [
            {"criterion": "G1", "category": "OMISSION", "severity": "major", "description": "x", "location": "/"}]},
            {"criteria": [{"id": "G1", "score": 5}], "issues": []})
        return Refiner(critics=[LLMRubricCritic(GENERIC_RUBRIC)], reviser=CountingReviser()), fake

    runs = []
    for _ in range(2):
        refiner, fake = make()
        res = await refiner.run(None, RefineContext(llm=fake), output=0)
        runs.append([(a.score, len(a.critique.issues), a.tokens) for a in res.attempts])
    assert runs[0] == runs[1] and len(runs[0]) == 2


async def test_token_accounting_and_budget_stop() -> None:
    fake = FakeLLM().on_schema(RubricAnswer, {"criteria": [{"id": "G1", "score": 1}], "issues": [
        {"criterion": "G1", "category": "OMISSION", "severity": "major", "description": "a part is missing",
         "location": "/"}]})

    class ChangingReviser(CountingReviser):
        pass

    ctx = RefineContext(llm=fake)
    res = await Refiner(critics=[LLMRubricCritic(GENERIC_RUBRIC)], reviser=ChangingReviser(),
                        stop=any_of(Budget(tokens=1, seconds=None), MaxIters(5))).run(None, ctx, output=0)
    assert res.stop_reason == "budget" and len(res.attempts) == 1
    assert res.usage.tokens > 0 and res.attempts[0].tokens == res.usage.tokens and res.usage.calls == 1


async def test_cancellation_stops_and_keeps_the_best_so_far() -> None:
    flag = {"stop": False}

    def check() -> None:
        if flag["stop"]:
            raise Cancelled("stopped")

    class StopAfterFirst(CountingReviser):
        async def revise(self, output, critique, history, ctx, *, task_input=None, strategy="targeted"):
            flag["stop"] = True
            return await super().revise(output, critique, history, ctx, task_input=task_input, strategy=strategy)

    res = await Refiner(critics=[ScoreByOutput({0: 0.3, 1: 0.9})], reviser=StopAfterFirst(),
                        stop=MaxIters(5)).run(None, RefineContext(check_cancelled=check), output=0)
    assert res.stop_reason == "cancelled" and len(res.attempts) == 1 and res.final_output == 0


async def test_a_failing_reviser_ends_with_error_but_a_failing_first_critique_propagates() -> None:
    class Boom(CountingReviser):
        async def revise(self, *a, **k):
            raise RuntimeError("reviser broke")

    res = await Refiner(critics=[ScoreByOutput({0: 0.3})], reviser=Boom(), stop=MaxIters(3)).run(None, output=0)
    assert res.stop_reason == "error" and "reviser broke" in (res.error or "") and res.final_output == 0

    class BadCritic:
        name, kind = "bad", "programmatic"

        async def review(self, *a):
            raise ValueError("no")

    with pytest.raises(ValueError):
        await Refiner(critics=[BadCritic()], reviser=CountingReviser()).run(None, output=0)


async def test_producer_runs_when_no_output_is_given_and_critique_only_without_reviser() -> None:
    async def produce(task_input, ctx):
        return 5

    res = await Refiner(producer=produce, critics=[ScoreByOutput({5: 0.4})], stop=Threshold(2.0)).run("in")
    assert res.final_output == 5 and res.stop_reason == "max_iters" and len(res.attempts) == 1
    assert res.trace.spec.producer == "produce" and res.trace.spec.reviser == "none"
    with pytest.raises(ValueError):
        await Refiner(critics=[ScoreByOutput({})]).run(None)


async def test_progress_callback_sees_each_attempt_and_the_stop() -> None:
    seen: list[tuple[int, str | None]] = []

    async def on_attempt(attempts, reason):
        seen.append((len(attempts), reason))

    await Refiner(critics=[ScoreByOutput({0: 0.2, 1: 0.95})], reviser=CountingReviser(),
                  stop=any_of(Threshold(0.9), MaxIters(3)), on_attempt=on_attempt).run(None, output=0)
    assert seen == [(1, None), (2, "threshold")]


async def test_hard_cap_beats_a_policy_that_never_stops() -> None:
    critic = ScriptedCritic([Critique(score=0.1, issues=[issue()])])
    res = await Refiner(critics=[critic], reviser=CountingReviser(), stop=Threshold(2.0),
                        hard_max_iters=4).run(None, output=0)
    assert len(res.attempts) == 5 and res.stop_reason == "max_iters"


async def test_concurrent_loops_do_not_share_state() -> None:
    async def one(start: int):
        return await Refiner(critics=[ScoreByOutput({start: 0.1, start + 1: 0.95})], reviser=CountingReviser(),
                             stop=any_of(Threshold(0.9), MaxIters(3))).run(None, output=start)

    a, b = await asyncio.gather(one(0), one(10))
    assert (a.final_output, b.final_output) == (1, 11)
