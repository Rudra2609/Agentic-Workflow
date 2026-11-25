import json
import sys
import types
from pathlib import Path

import pytest

from hmap.agents.models.bench import quant, quick, sets, table
from hmap.agents.models.bench.common import env_for, gateway_for, is_cloud, slug
from hmap.core.config import Settings


def test_model_ids() -> None:
    assert is_cloud("groq:openai/gpt-oss-120b") and is_cloud("gemini:gemini-3.6-flash")
    assert not is_cloud("qwen3.5:9b") and slug("groq:qwen/qwen3.8-27b") == "groq_qwen_qwen3.8-27b"
    local = env_for("qwen3.5:9b", Settings())
    assert local["HMAP_CLOUD_OK"] == "false" and "judge=qwen3.5:9b" in local["HMAP_ROLE_MAP"]
    cloud = env_for("groq:openai/gpt-oss-120b", Settings())
    assert "judge=groq:openai/gpt-oss-120b" in cloud["HMAP_CLOUD_ROLE_MAP"]
    assert "judge=no-local-fallback" in cloud["HMAP_ROLE_MAP"]


@pytest.mark.slow
async def test_quick_set_replay_reproduces_the_bakeoff() -> None:
    """The harness is the bake-off: replaying the imported answers gives the §0 scores (model-choice.md)."""
    res = await quick.run_quick("qwen3.5:9b", Settings(), mode="replay")
    assert res["quality"] == 0.833 and res["coverage"] == 1.0
    assert {k: v["score"] for k, v in res["suites"].items()} == {"extraction": 0.949, "planning": 0.971,
                                                                "critique": 0.6, "verify": 0.944, "coding": 0.68}


async def test_quick_set_fast_suites_replay() -> None:
    res = await quick.run_quick("qwen3.5:4b", Settings(), mode="replay", suites=["verify", "critique"])
    assert res["suites"]["verify"]["score"] == 1.0 and res["suites"]["critique"]["score"] == 0.7
    assert res["suites"]["critique"]["catch"] == pytest.approx(0.857, abs=1e-3)


async def test_unanswered_cloud_calls_are_not_scored() -> None:
    s = Settings(groq_api_keys=[], gemini_api_keys=[])
    res = await quick.run_quick("groq:nothing", s, mode="live", suites=["verify"], limit=2, retries=0)
    v = res["suites"]["verify"]
    assert v["answered"] == 0 and v["score"] is None and res["quality"] is None
    gw = gateway_for("groq:nothing", s, "live")
    assert gw.model_for("judge") == "no-local-fallback"


def test_table_and_quant() -> None:
    fake = {"a": {"suites": {"extraction": {"score": 0.9}, "planning": {"score": 0.8}, "critique": {"score": 0.5},
                             "verify": {"score": 0.7}, "coding": {"score": 0.6}}, "quality": 0.72},
            "b": {"suites": {"extraction": {"score": 0.9}, "planning": {"score": 0.8}, "critique": {"score": 0.5},
                             "verify": {"score": 0.7}, "coding": {"score": 0.61}}, "quality": 0.73},
            "c": {"suites": {"verify": {"score": 1.0}}, "quality": 1.0}}
    assert table.role_scores(fake["a"]) == {"reasoner": 0.85, "judge": 0.6, "coder": 0.6, "fast": 0.8,
                                            "classify": 0.8}
    assert table.role_scores(fake["c"]) == {}                          # incomplete: not in the table
    speed = {"a": {"resident_gb": 3.4, "tok_s": 10.0}, "b": {"resident_gb": 5.8, "tok_s": 6.0}}
    rep = quant.report(fake, speed, ["a", "b", "missing"])
    assert rep["recommendation"] == "a" and rep["not_measured"] == ["missing"]
    rows = table.bench_rows({"a": fake["a"]}, [{"set": "m6_verify", "model": "a", "role": "judge", "task": "t",
                                                "score": 0.8, "seconds": 3}], speed)
    assert len(rows) == 6 and rows[-1].set_name == "m6_verify"


def test_build_table_writes_roles(tmp_path: Path) -> None:
    t = table.build_table({"m": {"suites": {"extraction": {"score": 1.0}, "planning": {"score": 0.5},
                                            "critique": {"score": 0.5}, "verify": {"score": 0.5},
                                            "coding": {"score": 0.5}}}}, path=tmp_path / "t.json")
    assert t["roles"]["reasoner"] == {"m": 0.75}
    assert json.loads((tmp_path / "t.json").read_text())["roles"]["coder"] == {"m": 0.5}


def test_gold_set_adapters_cover_the_spec() -> None:
    """Item 11.5: M2 F1, M3 validity, M5 fact coverage, M6 detection, M7 pass@1, M10 judge agreement (+ M4)."""
    assert {s.member for s in sets.GOLD_SETS.values()} >= {2, 3, 5, 6, 7, 10}
    for gold in sets.GOLD_SETS.values():
        mod = __import__(gold.module, fromlist=["main"])
        assert callable(mod.main) and all(hasattr(mod, p) for p in gold.patch), gold.name
    m10 = sets.GOLD_SETS["m10_judge"]
    sample = json.loads((Path(__file__).resolve().parents[3] / "samples" / "review" / "eval_results" /
                         "cloud.json").read_text())
    assert m10.score(sample) == pytest.approx(0.707)
    assert sets.GOLD_SETS["m3_planning"].score({"summary": {"validity": 1.0}}) == 1.0
    assert sets._kappa01(-0.2) == 0.0


def test_child_main_points_results_away(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("fake_eval")
    fake.RESULTS = Path("/members/own/folder")                         # type: ignore[attr-defined]

    async def main() -> int:
        fake.RESULTS.mkdir(parents=True, exist_ok=True)               # type: ignore[attr-defined]
        (fake.RESULTS / "bench.json").write_text(json.dumps({"argv": sys.argv[1:]}))  # type: ignore[attr-defined]
        return 0

    fake.main = main                                                   # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fake_eval", fake)
    assert sets.child_main(["fake_eval", str(tmp_path), "RESULTS", "--", "--mode", "live"]) == 0
    assert json.loads((tmp_path / "bench.json").read_text()) == {"argv": ["--mode", "live"]}
