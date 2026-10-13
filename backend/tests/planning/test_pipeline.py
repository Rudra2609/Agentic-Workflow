"""The whole planner on the gold set in replay mode (the Sprint-3 targets as a regression gate), contract checks on
every output, determinism, and the M2 -> M3 contract on Member 2's real outputs."""

import json

import jsonschema
import pytest

from hmap.agents.planning.pipeline import make_plan
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.contracts.domain import TaskGraph
from hmap.core.llm import Gateway

from .eval.run_eval import REPLANS, gold_cases, plan_case, replan_scenario, score

SCHEMA = json.loads((REPO_ROOT / "backend" / "src" / "hmap" / "core" / "contracts" / "schemas" / "domain" /
                     "TaskGraph.schema.json").read_text())


def replay_llm() -> Gateway:
    """The recorded answers in samples/llm_cache/planning (no network, no keys, no Ollama)."""
    return Gateway(Settings(llm_mode="replay")).for_plugin("planning")


async def test_gold_set_in_replay_meets_the_sprint_targets() -> None:
    must_ok = must_total = 0
    for case in gold_cases():
        result, seconds = await plan_case(case, replay_llm())
        s = score(case, result, seconds)
        assert s.valid, case["id"]                                  # spec: valid TaskGraph (>= 95 % with repair)
        assert not s.uncovered, (case["id"], s.uncovered)           # 100 % covered or flagged
        assert s.invented == 0 and s.kind_ok, case["id"]            # no invented agents
        assert s.flags.fn == 0 and s.flags.fp == 0, case["id"]      # human-only work flagged, nothing else
        must_ok += s.must_ok
        must_total += s.must_total
    assert must_ok / must_total >= 0.9                              # "no missing obvious deps on gold plans"


async def test_the_recorded_answers_are_used() -> None:
    case = gold_cases(["tcp_chat"])[0]
    result, _ = await plan_case(case, replay_llm())
    assert result.report.method == "llm" and result.report.answered_by == {"cache:openai/gpt-oss-120b": 1}


@pytest.mark.parametrize("case_id", [c["id"] for c in gold_cases()])
async def test_output_validates_against_the_exported_json_schema(case_id: str) -> None:
    case = gold_cases([case_id])[0]
    result, _ = await plan_case(case, replay_llm())
    data = json.loads(result.graph.model_dump_json())
    jsonschema.validate(data, SCHEMA)
    assert TaskGraph.model_validate(data) == result.graph            # round trip: what the Manager reads


async def test_replay_is_deterministic() -> None:
    case = gold_cases(["long_lab"])[0]
    a, _ = await plan_case(case, replay_llm())
    b, _ = await plan_case(case, replay_llm())
    assert a.graph == b.graph and a.report.schedule == b.report.schedule


async def test_rules_alone_also_meet_validity_and_coverage() -> None:
    for case in gold_cases():
        result, seconds = await plan_case(case, None)
        s = score(case, result, seconds)
        assert s.valid and not s.uncovered and s.invented == 0, case["id"]


async def test_every_research_step_carries_questions_for_member_5() -> None:
    for case in gold_cases():
        result, _ = await plan_case(case, replay_llm())
        for t in result.graph.tasks:
            if t.agent_capability == "research.run":
                assert t.research_questions, case["id"]


async def test_progress_and_cancellation() -> None:
    from hmap.core.errors import Cancelled

    case = gold_cases(["multipart"])[0]
    seen: list[tuple[int, str]] = []

    async def progress(pct: int, text: str) -> None:
        seen.append((pct, text))

    await make_plan(case["requirement_set"], None, progress=progress)
    assert [p for p, _ in seen] == sorted(p for p, _ in seen) and any("Part B" in t for _, t in seen)

    def cancel() -> None:
        raise Cancelled("stop")

    with pytest.raises(Cancelled):
        await make_plan(case["requirement_set"], None, check_cancelled=cancel)


@pytest.mark.parametrize("scenario", REPLANS, ids=lambda s: s["case"])
async def test_recorded_replans_keep_finished_work_and_follow_the_feedback(scenario: dict) -> None:  # type: ignore[type-arg]
    """Spec 3.10 with the model's recorded answers: finished steps untouched, still valid and covered, and the change
    the person asked for happened ("use asyncio"; "merge the command-line steps")."""
    r = await replan_scenario(scenario, replay_llm())
    assert r["method"] == "llm" and not r["fallbacks"]
    assert r["valid"] and r["finished_kept"] and r["covered"] and r["applied"], r
