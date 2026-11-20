"""Items 7.6 / 7.7: the coding loop with a scripted FakeLLM (happy path, rejected edit, debug round, budgets,
degraded mode, cancel, prompt budget and replay hygiene)."""

import asyncio
import re
import shutil
from pathlib import Path

import pytest

from hmap.agents.coding.context_budget import tokens
from hmap.agents.coding.loop import CodingLoop, Job, Options
from hmap.agents.coding.model import CodingTrace
from hmap.agents.coding.prompts import CodePlan, TaskView
from hmap.agents.coding.workspace import Workspace
from hmap.core.config import Settings
from hmap.core.errors import Cancelled
from hmap.core.llm.fake import FakeLLM
from tests.coding.conftest import BENCH, block

B3 = BENCH / "b3_median_even"
GOLD_B3 = (B3 / "gold.edits").read_text()
WRONG_B3 = block("stats.py", "    mid = len(ordered) // 2\n    return ordered[mid]\n",
                 "    mid = len(ordered) // 2\n    return ordered[mid - 1]\n")
DEBUG_FIX = block("stats.py", "    return ordered[mid - 1]\n", "    if len(ordered) % 2:\n        return ordered[mid]\n"
                  "    return (ordered[mid - 1] + ordered[mid]) / 2\n")
VISIBLE_TEST = ("import unittest\nfrom stats import median\n\n\nclass T(unittest.TestCase):\n"
                "    def test_even(self):\n        self.assertEqual(median([1, 2, 3, 4]), 2.5)\n\n"
                "    def test_odd(self):\n        self.assertEqual(median([3, 1, 2]), 2)\n")


def starter(tmp_path: Path, task: Path = B3, *, with_test: bool = False) -> Workspace:
    root = tmp_path / "ws"
    shutil.copytree(task / "starter", root)
    if with_test:
        (root / "test_stats.py").write_text(VISIBLE_TEST)
    return Workspace(root)


def job(ws: Workspace, settings: Settings, llm: FakeLLM | None, objective: str = "", criteria: list[str] | None = None,
        **kw: object) -> Job:
    import json
    meta = json.loads((B3 / "task.json").read_text())
    task = TaskView(objective=objective or meta["objective"], criteria=criteria if criteria is not None else
                    meta["acceptance_criteria"])
    trace = CodingTrace(task_id="T1", project_id="P1", capability="code.implement")
    return Job(ws=ws, settings=settings, trace=trace, task=task, llm=llm, **kw)  # type: ignore[arg-type]


def plan_b3() -> CodePlan:
    return CodePlan(summary="handle an even number of values", files_to_modify=["stats.py"], steps=["fix median"])


async def hidden_tests_pass(ws: Workspace, task: Path = B3) -> bool:
    import subprocess
    import sys
    for f in (task / "hidden_tests").iterdir():
        shutil.copy(f, ws.root / f.name)
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-p", "test_*.py"], cwd=ws.root,
                          capture_output=True, timeout=60)
    return proc.returncode == 0


async def test_happy_path_fixes_the_bug(tmp_path: Path, settings: Settings) -> None:
    ws = starter(tmp_path)
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", GOLD_B3)
    trace = await CodingLoop(job(ws, settings, fake)).run()
    assert trace.outcome == "success" and trace.stop_reason == "checks_pass"
    assert trace.files_changed == ["stats.py"] and trace.plan and trace.plan["files_to_modify"] == ["stats.py"]
    assert [s.kind for s in trace.steps] == ["plan", "edit"]
    assert trace.located and trace.located[0]["path"] == "stats.py"
    assert await hidden_tests_pass(ws)


async def test_a_rejected_edit_is_fed_back_and_fixed(tmp_path: Path, settings: Settings) -> None:
    ws = starter(tmp_path)
    bad = block("stats.py", "    return ordered[middle]\n", "    return 0\n")
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", bad, GOLD_B3)
    trace = await CodingLoop(job(ws, settings, fake)).run()
    assert [e.ok for e in trace.edits] == [False, True]
    assert "not found" in (trace.edits[0].error or "")
    assert "was NOT applied" in fake.calls[-1].messages[1].content
    assert trace.outcome == "success"


async def test_failing_tests_drive_a_debug_round(tmp_path: Path, settings: Settings) -> None:
    ws = starter(tmp_path, with_test=True)
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", WRONG_B3, "HYPOTHESIS: off by one\n" + DEBUG_FIX)
    trace = await CodingLoop(job(ws, settings, fake)).run()
    assert trace.outcome == "success" and trace.stop_reason == "checks_pass"
    assert [s.kind for s in trace.steps] == ["plan", "edit", "debug"]
    assert trace.steps[-1].summary == "hypothesis: off by one"
    debug_prompt = fake.calls[-1].messages[1].content
    assert "The checks fail" in debug_prompt and "stats.py" in debug_prompt
    assert any(c.cmd.startswith("python -m pytest") or "unittest" in c.cmd for c in trace.commands)


async def test_budget_exhausted_returns_partial(tmp_path: Path, settings: Settings) -> None:
    ws = starter(tmp_path, with_test=True)
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", WRONG_B3)
    trace = await CodingLoop(job(ws, settings, fake)).run()
    assert trace.outcome == "partial" and trace.stop_reason in ("plateau", "max_iters")
    assert trace.reflections and "did not fix" in trace.reflections[-1]
    assert len(trace.steps) <= settings.coding_max_steps


async def test_step_budget(tmp_path: Path) -> None:
    s = Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path / "w"), "HMAP_CODING_MAX_STEPS": "1"})
    ws = starter(tmp_path)
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", GOLD_B3)
    trace = await CodingLoop(job(ws, s, fake)).run()
    assert trace.stop_reason == "step_budget" and len(trace.steps) == 1 and trace.outcome == "partial"


@pytest.mark.parametrize("llm", [None, FakeLLM(default=None), FakeLLM()])
async def test_no_model_answer_degrades_gracefully(tmp_path: Path, settings: Settings, llm: FakeLLM | None) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    ws = Workspace(root)
    trace = await CodingLoop(job(ws, settings, llm, objective="Build a multi-client TCP chat server and client",
                                 criteria=["clients see each other's messages"])).run()
    assert trace.template == "tcp_server_client" and "server.py" in trace.files_changed
    assert trace.outcome == "partial" and trace.stop_reason == "no_model"
    assert any(n.startswith("no model answer") for n in trace.notes)


async def test_greenfield_template_with_no_further_change_succeeds(tmp_path: Path, settings: Settings) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    fake = FakeLLM().on_schema(CodePlan, CodePlan(summary="the template already does it"))
    trace = await CodingLoop(job(Workspace(root), settings, fake,
                                 objective="Set up the project skeleton for a multi-client TCP chat server",
                                 criteria=["the skeleton runs"])).run()
    assert trace.template == "tcp_server_client" and trace.outcome == "success"
    assert {c.name: c.status for c in trace.checks}["tests"] == "passed"


async def test_cancel_stops_the_loop(tmp_path: Path, settings: Settings) -> None:
    ws = starter(tmp_path)
    stop = asyncio.Event()
    stop.set()
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", GOLD_B3)
    with pytest.raises(Cancelled):
        await CodingLoop(job(ws, settings, fake, cancelled=stop)).run()


async def test_prompts_fit_the_budget_and_are_replay_stable(tmp_path: Path) -> None:
    s = Settings.from_env({"HMAP_CODING_WORK_DIR": str(tmp_path / "w"), "HMAP_CODING_PROMPT_TOKENS": "1500"})
    ws = starter(tmp_path, with_test=True)
    ws.write("big.py", "".join(f"def f{i}(x):\n    return x + {i}\n\n" for i in range(600)))
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", WRONG_B3, DEBUG_FIX)
    await CodingLoop(job(ws, s, fake)).run()
    for call in fake.calls:
        text = "".join(m.content for m in call.messages)
        assert tokens(text) <= 1500 + 16
        assert str(ws.root) not in text and str(tmp_path) not in text
        assert not re.search(r"\b\d+\.\d{2,}s\b", text), "a duration in a prompt breaks replay"
        assert call.temperature == 0.0 and call.seed == 7


async def test_regression_guard_keeps_the_best_round(tmp_path: Path, settings: Settings) -> None:
    ws = starter(tmp_path, with_test=True)
    breaks_import = block("stats.py", "    mid = len(ordered) // 2\n", "    mid = len(ordered) // 2\n"
                          "    undefined_helper()\n") + block("extra.py", "", "import missing_module\n")
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", GOLD_B3.replace("/ 2", "/ 3"), breaks_import)
    trace = await CodingLoop(job(ws, settings, fake, options=Options(use_embeddings=False))).run()
    assert trace.outcome == "partial"
    assert not ws.exists("extra.py") and "undefined_helper" not in ws.read("stats.py")
    assert any("kept the best round" in n for n in trace.notes)


async def test_no_change_at_all_is_not_a_success(tmp_path: Path, settings: Settings) -> None:
    ws = starter(tmp_path)
    noop = block("stats.py", "    mid = len(ordered) // 2\n", "    mid = len(ordered) // 2\n")
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", noop)
    trace = await CodingLoop(job(ws, settings, fake)).run()
    assert trace.files_changed == [] and trace.outcome == "partial"
    assert all(not e.ok and "changes nothing" in (e.error or "") for e in trace.edits)
    assert any("no change was made" in n for n in trace.notes)


async def test_no_changes_answer_is_a_success_when_checks_pass(tmp_path: Path, settings: Settings) -> None:
    ws = starter(tmp_path)
    fake = FakeLLM().on_schema(CodePlan, plan_b3()).on_role("coder", "NO CHANGES")
    trace = await CodingLoop(job(ws, settings, fake)).run()
    assert trace.outcome == "success" and any("already does" in n for n in trace.notes)
