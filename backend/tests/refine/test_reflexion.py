"""Reflexion (item 4.5): notes after failed attempts, strategy change on repeated failure, memory across runs."""

import json

from hmap.agents.refine import ArtifactMemoryStore, InMemoryStore, RefineContext, Refiner, ReflectionMemory
from hmap.agents.refine.core import Attempt, Critique
from hmap.agents.refine.reflexion import NoteAnswer
from hmap.agents.refine.stop import MaxIters
from hmap.core.llm import FakeLLM
from hmap.services.artifact.memory import InMemoryArtifactStore
from tests.refine.conftest import CountingReviser, ScriptedCritic, issue


def attempt(index: int, categories: list[str], strategy: str | None = None) -> Attempt:
    return Attempt(index=index, output=index, strategy=strategy,
                   critique=Critique(score=0.3, issues=[issue(c) for c in categories]))


def test_strategy_ladder_on_repeated_same_category_failure() -> None:
    m = ReflectionMemory("k")
    h = [attempt(0, ["OMISSION"])]
    assert m.choose_strategy(h) == "targeted"
    h.append(attempt(1, ["OMISSION"], "targeted"))
    assert m.choose_strategy(h) == "full"                        # same problem survived a targeted fix
    h.append(attempt(2, ["OMISSION"], "full"))
    assert m.choose_strategy(h) == "widen"
    h.append(attempt(3, ["OMISSION"], "widen"))
    assert m.choose_strategy(h) == "widen"                       # top of the ladder
    assert m.choose_strategy([attempt(0, ["LOGIC"]), attempt(1, ["OMISSION"], "targeted")]) == "targeted"


async def test_repeated_failure_changes_the_approach_in_the_loop() -> None:
    critic = ScriptedCritic([Critique(score=0.3, issues=[issue("OMISSION")])])
    reviser = CountingReviser()
    memory = ReflectionMemory("k", InMemoryStore())
    res = await Refiner(critics=[critic], reviser=reviser, stop=MaxIters(3), memory=memory).run(None, output=0)
    assert reviser.strategies == ["targeted", "full", "widen"]
    assert [a.strategy for a in res.attempts] == [None, "targeted", "full", "widen"]
    assert all(a.reflection for a in res.attempts[:-1])           # a note after every failed attempt
    assert "OMISSION" in (res.attempts[0].reflection or "")


async def test_notes_use_the_fast_model_and_reach_the_next_revision_prompt() -> None:
    fake = FakeLLM().on_schema(NoteAnswer, {"what_failed": "R4 is still missing.",
                                            "change": "Quote the sentence under Tasks."})
    memory = ReflectionMemory("k")
    critic = ScriptedCritic([Critique(score=0.3, issues=[issue("OMISSION")])])
    res = await Refiner(critics=[critic], reviser=CountingReviser(), stop=MaxIters(1), memory=memory).run(
        None, RefineContext(llm=fake), output=0)
    assert res.attempts[0].reflection == "R4 is still missing. Quote the sentence under Tasks."
    assert fake.calls[0].role == "fast"
    from hmap.agents.refine.revisers import reflection_lines

    assert "R4 is still missing" in reflection_lines(res.attempts, RefineContext(memory=memory))


async def test_memory_persists_per_project_and_starts_the_next_run_at_full() -> None:
    artifacts = InMemoryArtifactStore()
    store = ArtifactMemoryStore(artifacts, "P-1")
    critic = ScriptedCritic([Critique(score=0.3, issues=[issue("OMISSION")])])
    first = ReflectionMemory("document.extract", store)
    await Refiner(critics=[critic], reviser=CountingReviser(), stop=MaxIters(1), memory=first).run(None, output=0)
    [ref] = [r for r in await artifacts.list("P-1") if r.artifact_type == "reflection-memory"]
    saved = json.loads(await artifacts.get(ref, project_id="P-1"))
    assert saved["key"] == "document.extract" and saved["notes"][0]["outcome"] == "failed"
    second = await ReflectionMemory("document.extract", store).load()
    assert second.remembered() and second.start_strategy({"OMISSION"}) == "full"
    assert second.start_strategy({"LOGIC"}) == "targeted"
    reviser = CountingReviser()
    critic2 = ScriptedCritic([Critique(score=0.3, issues=[issue("OMISSION")])])
    await Refiner(critics=[critic2], reviser=reviser, stop=MaxIters(1), memory=second).run(None, output=0)
    assert reviser.strategies == ["full"]
    other_project = await ReflectionMemory("document.extract", ArtifactMemoryStore(artifacts, "P-2")).load()
    assert other_project.past == []


async def test_fixed_problems_are_marked_fixed() -> None:
    store = InMemoryStore()
    critic = ScriptedCritic([Critique(score=0.3, issues=[issue("OMISSION")]), Critique(score=1.0, issues=[])])
    await Refiner(critics=[critic], reviser=CountingReviser(), stop=MaxIters(2),
                  memory=ReflectionMemory("k", store)).run(None, output=0)
    assert store.data["k"][0]["outcome"] == "fixed"
