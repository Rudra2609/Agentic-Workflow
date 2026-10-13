"""Rules (item 2.5), quote verification (spec §9), LLM extraction with re-ask and cache (2.5/2.7), merge (2.6) and
validation (2.7). The model is a scripted FakeLLM."""

import pytest

from hmap.agents.doc_intel.cache import MemoryCache, cache_key
from hmap.agents.doc_intel.chunking import Chunk
from hmap.agents.doc_intel.extract.llm import ChunkExtraction, ExtractedItem, extract_chunk
from hmap.agents.doc_intel.extract.quotes import jaccard, locate, normalize, overlap
from hmap.agents.doc_intel.extract.rules import classify_sentence, constraint_kind, priority_of, rule_pass, sentences
from hmap.agents.doc_intel.merge import Candidate, assemble, dedup
from hmap.agents.doc_intel.model import Block, SourceDocument
from hmap.agents.doc_intel.validate import check
from hmap.core.contracts.domain import EvaluationCriterion, Requirement, RequirementSet, RubricLevel, SourceRef
from hmap.core.llm import FakeLLM
from hmap.core.llm.fake import FakeCall


def block(bid: str, text: str, section: list[str], kind: str = "list_item", start: int = 0) -> Block:
    return Block(id=bid, type=kind, text=text, section_path=section, char_start=start,  # type: ignore[arg-type]
                 char_end=start + len(text), page=1)


def doc(*blocks: Block) -> SourceDocument:
    return SourceDocument(doc_id="d1", name="brief.pdf", blocks=list(blocks), folder="Part A",
                          text="\n\n".join(b.text for b in blocks))


REQ = block("b2", "The server must accept 10 clients.", ["Brief", "Requirements"], start=0)
CON = block("b3", "Use Python 3.11 only.", ["Brief", "Constraints"], start=40)
DEL = block("b4", "Submit a ZIP file with the code.", ["Brief", "What to submit"], start=70)
BG = block("b5", "Chat servers are fun to build.", ["Brief", "Background"], kind="paragraph", start=110)


def test_rule_patterns() -> None:
    assert [priority_of(s) for s in ("You must do it", "It should be fast", "You may add", "Do it")] == [
        "must", "should", "could", "must"]
    assert constraint_kind("Use Python 3.11 only") == "technology"
    assert constraint_kind("Submit before 23:59 on Friday") == "process"
    assert sentences("One must. Two should! three") == ["One must.", "Two should! three"]
    assert classify_sentence(REQ.text, REQ) == "R"
    assert classify_sentence(CON.text, CON) == "C"
    assert classify_sentence(DEL.text, DEL) == "D"
    assert classify_sentence(BG.text, BG) is None
    hits = rule_pass([doc(REQ, CON, DEL, BG)])
    assert [(h.kind, h.block_id) for h in hits] == [("R", "b2"), ("C", "b3"), ("D", "b4")]


def test_quote_location() -> None:
    blocks = [REQ, CON]
    exact = locate("the server must accept 10 clients", blocks)
    assert exact.status == "exact" and exact.block is REQ and exact.char_span == (0, len("the server must accept "
                                                                                          "10 clients"))
    approx = locate("The server must accept ten 10 clients at once", blocks)
    assert approx.status in ("approximate", "unverified")
    assert locate("Something nobody wrote", blocks).status == "unverified"
    assert locate("", blocks, fallback_text="Use Python 3.11 only.").block is CON
    assert normalize("  1. The “Server”  must—go. ") == 'the "server" must-go'
    assert overlap("server accept clients", REQ.text) == 1.0 and jaccard("a b", "") == 0.0


def _chunk() -> Chunk:
    d = doc(REQ, CON, DEL)
    return Chunk(0, 0, d, list(d.blocks))


def item(kind: str, text: str, quote: str | None = None, **kw: object) -> ExtractedItem:
    return ExtractedItem(kind=kind, text=text, quote=quote or text, **kw)  # type: ignore[arg-type]


async def test_extract_chunk_reasks_for_missing_quotes_and_caches() -> None:
    first = ChunkExtraction(items=[item("requirement", REQ.text),
                                   item("constraint", "Python only", quote="Only Python 3 may be used.")])
    fixed = ChunkExtraction(items=[item("constraint", "Python only", quote=CON.text)], open_questions=["Which OS?"])
    fake = FakeLLM().on_schema(ChunkExtraction, first, fixed)
    cache = MemoryCache()
    out, who = await extract_chunk(fake, _chunk(), [], cache)
    assert who == "fake:fake"
    assert [i.quote for i in out.items] == [REQ.text, CON.text] and out.open_questions == ["Which OS?"]
    assert len(fake.calls) == 2 and "These quotes are not in the text above" in fake.calls[1].messages[-1].content
    assert fake.calls[0].role == "reasoner" and fake.calls[0].temperature == 0.0
    again, who_again = await extract_chunk(fake, _chunk(), [], cache)
    assert again == out and who_again == "memory" and len(fake.calls) == 2  # cached
    assert cache_key("extract", "a").startswith("extract-") and cache_key("x", "a") != cache_key("x", "b")


async def test_hints_are_in_the_prompt() -> None:
    from hmap.agents.doc_intel.extract.rules import RuleHit

    seen: list[FakeCall] = []

    def reply(call: FakeCall) -> ChunkExtraction:
        seen.append(call)
        return ChunkExtraction()

    await extract_chunk(FakeLLM().on_schema(ChunkExtraction, reply), _chunk(), [RuleHit("R", REQ.text, 0, "b2")])
    prompt = seen[0].messages[-1].content
    assert "Document: brief.pdf (folder: Part A)" in prompt and "# Requirements" in prompt
    assert "requirement keywords" in prompt and f"- {REQ.text}" in prompt


def _cand(kind: str, text: str, blk: Block, conf: float = 0.9, quote: str | None = None, **kw: object) -> Candidate:
    d = doc(REQ, CON, DEL)
    return Candidate(kind, text, 0, d, block=blk, quote=quote or blk.text, char_span=(blk.char_start, blk.char_end),
                     confidence=conf, **kw)  # type: ignore[arg-type]


def test_merge_dedups_orders_and_numbers() -> None:
    cands = [_cand("D", "ZIP with code", DEL, name="Source code", fmt="ZIP"),
             _cand("R", REQ.text, REQ, conf=0.7),
             _cand("R", "The server must accept 10 clients", REQ, conf=0.95),     # duplicate, more confident
             _cand("C", REQ.text, REQ),                                              # same quote, other kind
             _cand("C", CON.text, CON, ckind="technology"),
             _cand("E", "Broadcasting", REQ, origin="table", max_marks=30, levels=[("Good", "all", 30.0)])]
    assert len(dedup(cands)) == 4
    out = assemble(cands)
    assert [(r.id, r.confidence) for r in out.requirements] == [("R1", 0.95)]
    assert out.requirements[0].source_ref == SourceRef(doc_id="d1", page=1, block_ids=["b2"],
                                                       char_span=(0, len(REQ.text)), quote=REQ.text, folder="Part A")
    assert [(c.id, c.kind) for c in out.constraints] == [("C1", "technology")]
    assert [(d.id, d.name, d.format) for d in out.deliverables] == [("D1", "Source code", "ZIP")]
    assert out.evaluation_criteria[0].rubric_levels == [RubricLevel(label="Good", description="all", marks=30)]


def _rs(**kw: object) -> RequirementSet:
    req = Requirement(id="R1", text="x", source_ref=SourceRef(doc_id="d1", quote="x"))
    return RequirementSet(project_id="P-1", requirements=[req], **kw)  # type: ignore[arg-type]


def test_validation_reports_marks_problems_and_empty_sets() -> None:
    crits = [EvaluationCriterion(id="E1", criterion="a", max_marks=10,
                                 rubric_levels=[RubricLevel(label="top", marks=12)]),
             EvaluationCriterion(id="E2", criterion="b", max_marks=5)]
    report = check(_rs(evaluation_criteria=crits), [20])
    assert "marks_sum_mismatch" in report.issues
    assert any("add up to 15 marks" in q and "20" in q for q in report.questions)
    assert any("worth 12 marks but a maximum of 10" in q for q in report.questions)
    assert check(_rs(evaluation_criteria=crits[1:]), [5]).issues == []
    empty = check(RequirementSet(project_id="P-1", requirements=[]), [])
    assert "no_requirements" in empty.issues and empty.questions
    with pytest.raises(ValueError, match="criteria marks sum"):  # the contract itself refuses an inconsistent total
        _rs(evaluation_criteria=crits[1:], total_marks=20)


def test_null_fields_fall_back_to_defaults() -> None:
    item = ExtractedItem.model_validate({"kind": "requirement", "text": "x", "quote": "x", "priority": None,
                                         "constraint_kind": None, "deliverable_name": None, "req_type": None})
    assert (item.priority, item.req_type, item.constraint_kind, item.deliverable_name) == (
        "must", "functional", "other", "")


def test_list_under_a_lead_in_becomes_requirements() -> None:
    lead = block("b1", "Implement the classes. At minimum, your code needs to support:", ["Lab", "Part E"],
                 kind="paragraph")
    items = [block(f"b{i}", t, ["Lab", "Part E"], start=100 + 40 * i)
             for i, t in enumerate(["Customer and booking management", "Booking confirmation"], start=2)]
    after = block("b9", "This is unrelated text.", ["Lab", "Part F"], kind="paragraph", start=400)
    hits = rule_pass([doc(lead, *items, after)])
    assert [(h.kind, h.block_id, h.text) for h in hits if h.block_id != "b1"] == [
        ("R", "b2", "At minimum, your code needs to support: Customer and booking management."),
        ("R", "b3", "At minimum, your code needs to support: Booking confirmation.")]
    assert not any(h.text.endswith(":") for h in hits)
    assert [h.block_id for h in hits if h.block_id == "b1"] == ["b1"]  # "Implement the classes." still counts
