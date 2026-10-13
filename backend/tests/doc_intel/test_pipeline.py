"""The whole pipeline: replay-mode determinism and a quality gate on the gold set (spec §8 DoD), rules fallback when
the model fails, cancellation, marks-total handling and progress."""

import json

import jsonschema
import pytest

from hmap.agents.doc_intel.cache import MemoryCache
from hmap.agents.doc_intel.extract.llm import ChunkExtraction
from hmap.agents.doc_intel.loaders import InputDocument
from hmap.agents.doc_intel.pipeline import run_pipeline
from hmap.core.config import REPO_ROOT, Settings
from hmap.core.contracts.domain import RequirementSet
from hmap.core.errors import Cancelled
from hmap.core.llm import FakeLLM, Gateway, LLMProviderError

from .eval.metrics import PRF
from .eval.run_eval import gold_cases, inputs_for, score_document


def replay_llm() -> Gateway:
    """The recorded answers in samples/llm_cache/doc_intel (no network, no keys, no Ollama)."""
    return Gateway(Settings(llm_mode="replay")).for_plugin("doc_intel")


async def test_gold_set_in_replay_meets_the_sprint_targets() -> None:
    totals = {f: PRF() for f in ("requirements", "constraints", "deliverables", "evaluation_criteria")}
    marks = [0, 0]
    for case in gold_cases():
        result = await run_pipeline(f"P-{case['id']}", inputs_for(case), replay_llm(), cache=MemoryCache())
        score = score_document(case, result.requirement_set, result.document_model, 0.0)
        for f, prf in score.fields.items():
            totals[f].add(prf)
        marks[0] += score.marks_correct
        marks[1] += score.marks_total
        assert score.ocr_gate_ok, case["id"]          # native files never OCR'd, scans always
        if not case.get("needs_ocr"):
            # scans: Tesseract (used when no vision answer is recorded) can lose a table row; then the pipeline
            # withholds the total and asks, which is right, but does not match the gold total
            assert score.total_marks_ok, case["id"]
        assert score.quotes_verified == score.quotes_total, case["id"]
    assert totals["requirements"].f1 >= 0.75          # spec §8 target
    assert marks[0] / marks[1] >= 0.9                 # rubric marks accuracy on structured tables
    assert totals["evaluation_criteria"].f1 >= 0.9


async def test_replay_is_deterministic() -> None:
    case = gold_cases(["g01"])[0]
    a = await run_pipeline("P-1", inputs_for(case), replay_llm())
    b = await run_pipeline("P-1", inputs_for(case), replay_llm())
    assert a.requirement_set == b.requirement_set
    RequirementSet.model_validate_json(a.requirement_set.model_dump_json())  # contract round trip


async def test_model_failure_falls_back_to_rules_and_says_so() -> None:
    def broken(_call: object) -> ChunkExtraction:
        raise LLMProviderError("model unavailable")

    case = gold_cases(["g01"])[0]
    result = await run_pipeline("P-1", inputs_for(case), FakeLLM().on_schema(ChunkExtraction, broken))
    rs = result.requirement_set
    assert result.stats.rules_only_chunks == result.stats.chunks and result.stats.llm_chunks == 0
    assert len(rs.requirements) >= 6 and all(r.confidence == 0.6 for r in rs.requirements)
    assert any("keyword rules only" in q for q in rs.open_questions)
    assert len(rs.evaluation_criteria) == 6 and rs.total_marks == 100  # tables never needed the model


async def test_an_empty_answer_with_rule_hits_falls_back_to_rules() -> None:
    case = gold_cases(["g01"])[0]
    result = await run_pipeline("P-1", inputs_for(case), FakeLLM().on_schema(ChunkExtraction, ChunkExtraction()))
    assert result.stats.rules_only_chunks == 1 and len(result.requirement_set.requirements) >= 6
    assert any("keyword rules only" in q for q in result.requirement_set.open_questions)


async def test_no_model_at_all_still_produces_a_valid_set() -> None:
    result = await run_pipeline("P-1", inputs_for(gold_cases(["g02"])[0]), None)
    assert result.requirement_set.requirements and result.stats.llm_chunks == 0


async def test_mismatched_total_is_dropped_and_asked_about() -> None:
    text = b"# Task\n\n- The app must work.\n\n| Criterion | Marks |\n|---|---|\n| Works | 5 |\n| Tests | 3 |\n\n" \
           b"Total: 10 marks\n"
    result = await run_pipeline("P-1", [InputDocument("d1", "brief.md", text, "text/markdown")], None)
    rs = result.requirement_set
    assert rs.total_marks is None and sum(e.max_marks for e in rs.evaluation_criteria) == 8
    assert any("add up to 8 marks" in q and "total of 10" in q for q in rs.open_questions)
    assert "marks_sum_mismatch" in result.stats.issues


async def test_progress_and_cancellation() -> None:
    seen: list[tuple[int, str]] = []

    async def progress(pct: int, summary: str) -> None:
        seen.append((pct, summary))

    case = gold_cases(["g08"])[0]
    await run_pipeline("P-1", inputs_for(case), replay_llm(), progress=progress)
    percents = [p for p, _ in seen]
    assert percents == sorted(percents) and percents[-1] == 98
    assert any("Part B/part_b.docx" in s for _, s in seen) and any("Extracting requirements" in s for _, s in seen)

    calls = 0

    def cancel_after_two() -> None:
        nonlocal calls
        calls += 1
        if calls > 2:
            raise Cancelled("stop")

    with pytest.raises(Cancelled):
        await run_pipeline("P-1", inputs_for(case), replay_llm(), check_cancelled=cancel_after_two)


SCHEMA = REPO_ROOT / "backend/src/hmap/core/contracts/schemas/domain/RequirementSet.schema.json"


@pytest.mark.parametrize("case_id", [c["id"] for c in gold_cases()])
async def test_output_validates_against_the_exported_json_schema(case_id: str) -> None:
    """The contract test of spec item 2.14: Member 3 reads the JSON file, so check the JSON against the published
    schema (not only the Python model that produced it)."""
    schema = json.loads(SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    case = gold_cases([case_id])[0]
    result = await run_pipeline("P-1", inputs_for(case), replay_llm())
    jsonschema.validate(json.loads(result.requirement_set.model_dump_json()), schema,
                        cls=jsonschema.Draft202012Validator)


async def test_the_documents_modal_word_decides_priority() -> None:
    from hmap.agents.doc_intel.extract.llm import ExtractedItem

    sentence = "The program should be runnable from the command line."
    llm = FakeLLM().on_schema(ChunkExtraction, ChunkExtraction(items=[  # the model says "must"; the text says should
        ExtractedItem(kind="requirement", text=sentence, quote=sentence, priority="must")]))
    doc = InputDocument("d1", "lab.md", f"# Lab\n\n{sentence}\n".encode(), "text/markdown")
    result = await run_pipeline("P-1", [doc], llm)
    assert [r.priority for r in result.requirement_set.requirements] == ["should"]
