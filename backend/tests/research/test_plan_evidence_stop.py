"""Planner (5.1), evidence with quote-must-match (5.7), coverage + stopping (5.8, property test), synthesis (5.9)."""

from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from hmap.agents.refine.stop import LoopState
from hmap.agents.research import evidence as ev
from hmap.agents.research import planner, stop, synthesize
from hmap.agents.research.model import Chunk, EvidenceDraft, Scored
from hmap.core.contracts import ResearchBrief
from hmap.core.contracts.domain import Claim, ResearchBudget, SubQuestion
from hmap.core.llm import FakeLLM
from tests.research.conftest import ASYNCIO_URL, TEXTS, THREAD_URL, make_page

BRIEF = ResearchBrief(task_id="T1", questions=["Threads or asyncio for a TCP chat server?",
                                               "How to measure latency with the standard library?"])


async def test_planner_uses_the_model_but_every_question_gets_a_sub_question() -> None:
    llm = FakeLLM(default=None).on_schema(planner.PlanAnswer, {"sub_questions": [
        {"question": 0, "text": "How does an asyncio event loop serve many sockets?",
         "queries": ["asyncio event loop many sockets", "site:evil.com \"quoted\" https://x.y/z", ""],
         "success_criteria": "names the event loop"},
        {"question": 0, "text": "What does the GIL mean for threaded servers?", "queries": "python GIL threads"},
        {"question": 7, "text": "out of range", "queries": ["x"]}]})
    subs, how = await planner.plan(BRIEF, llm)
    assert how == "model" and [s.id for s in subs] == ["S1.1", "S1.2", "S2.1"]
    assert subs[0].queries == ["asyncio event loop many sockets", "quoted"]            # operators and URLs removed
    assert subs[1].queries == ["python GIL threads"]
    assert subs[2].question == 1 and subs[2].text == BRIEF.questions[1]                 # rule fallback for Q2


async def test_planner_falls_back_to_rules_without_a_model() -> None:
    subs, how = await planner.plan(BRIEF, FakeLLM(default=None))
    assert how == "rules" and len(subs) == 2 and all(s.queries for s in subs)


def _cand(cid: str, sub: SubQuestion, url: str) -> ev.Candidate:
    title, kind, text = TEXTS[url]
    page = make_page(url, title, text, kind)
    chunk = Chunk(id=f"{cid}-c", url=url, title=title, kind=kind, text=page.text, start=0, end=len(page.text))
    return ev.Candidate(cid=cid, sub=sub, scored=Scored(chunk=chunk, score=0.9), page=page)


SUB = SubQuestion(id="S1.1", text="Do threads or an event loop serve many sockets better?",
                  queries=["event loop many sockets threads"])


async def test_invented_quotes_never_survive() -> None:
    lying = FakeLLM(default=None).on_schema(ev.TriageAnswer, {"relevant": ["C1", "C2"]}).on_schema(
        ev.ExtractAnswer, {"evidence": [
            {"passage": "C1", "sub_question": "S1.1",
             "quote": "asyncio is always faster than threads for every server.", "why": "made up"},
            {"passage": "C1", "sub_question": "S1.1", "quote": "An event loop runs in a single thread and multiplexes "
                                                              "many sockets.", "why": "real"},
            {"passage": "C2", "sub_question": "S1.1", "why": "real",
             "quote": "In CPython the global interpreter lock lets only one thread execute Python bytecode at a time"},
            {"passage": "C9", "sub_question": "S1.1", "quote": "unknown passage", "why": ""}]})
    out = await ev.extract([_cand("C1", SUB, ASYNCIO_URL), _cand("C2", SUB, THREAD_URL)], lying, first_id=1,
                           known=set())
    assert [e.id for e in out.evidence] == ["E1", "E2"] and out.dropped == 1 and out.proposed == 3
    title, kind, text = TEXTS[ASYNCIO_URL]
    page_text = make_page(ASYNCIO_URL, title, text, kind).text
    e1 = out.evidence[0]
    assert page_text[e1.char_start:e1.char_end] == e1.quote and "faster" not in "".join(e.quote for e in out.evidence)


async def test_rule_extraction_without_a_model_is_verbatim() -> None:
    out = await ev.extract([_cand("C1", SUB, ASYNCIO_URL)], None, first_id=4, known=set())
    [e] = out.evidence
    assert e.id == "E4" and e.quote in TEXTS[ASYNCIO_URL][2] and out.dropped == 0


def _ev(n: int, sub: str, host: str) -> EvidenceDraft:
    return EvidenceDraft(id=f"E{n}", sub_question=sub, url=f"https://{host}/p", quote="q" * 30, char_start=0,
                         char_end=30, content_sha256="0" * 64, retrieved_at=datetime.now(UTC), host=host)


def test_coverage_needs_two_sources_or_more_quotes() -> None:
    s = SubQuestion(id="S1.1", text="x")
    assert stop.coverage(s, []) == 0.0
    assert stop.coverage(s, [_ev(1, "S1.1", "a.org")]) == 0.5
    assert stop.coverage(s, [_ev(1, "S1.1", "a.org"), _ev(2, "S1.1", "a.org")]) == 0.625
    assert stop.coverage(s, [_ev(n, "S1.1", "a.org") for n in range(5)]) == 0.75          # one site never answers
    assert stop.coverage(s, [_ev(1, "S1.1", "a.org"), _ev(2, "S1.1", "b.org")]) == 1.0
    assert stop.coverage(s, [_ev(1, "S2.1", "a.org")]) == 0.0
    [u] = stop.update([s], [_ev(1, "S1.1", "a.org")], 1, exhausted=set())
    assert u.status == "partial" and u.coverage == 0.5


def test_policy_reasons_map_to_research_words() -> None:
    p = stop.research_policy(ResearchBudget(max_rounds=3))
    assert stop.research_reason(p.check(LoopState().record(1.0))) == "all_covered"
    state = LoopState(extra={"novelty": 0.05}).record(0.3).record(0.4)
    assert stop.research_reason(p.check(LoopState(scores=state.scores, extra={"novelty": 0.05}))) == "low_novelty"
    assert stop.research_reason(p.check(LoopState(scores=(0.1, 0.2, 0.3), extra={"novelty": 0.5}))) == "max_rounds"
    assert stop.research_reason(p.check(LoopState(scores=(0.1,), tokens=10**6, extra={}))) == "budget"


@settings(max_examples=150, deadline=None)
@given(rounds=st.integers(1, 10), scores=st.lists(st.floats(0, 1), min_size=1, max_size=20),
       novelty=st.lists(st.floats(0, 1), min_size=20, max_size=20))
def test_every_research_loop_stops_within_its_rounds(rounds: int, scores: list[float], novelty: list[float]) -> None:
    policy = stop.research_policy(ResearchBudget(max_rounds=rounds))
    state = LoopState()
    for n, sc in enumerate(scores + [0.0] * 20):
        state = LoopState(scores=(*state.scores, sc), extra={"novelty": novelty[n % 20]})
        if policy.check(state) is not None:
            break
    assert len(state.scores) <= min(rounds, stop.HARD_MAX_ROUNDS)


async def test_synthesis_keeps_only_properly_cited_claims() -> None:
    evid = [EvidenceDraft(id="E1", sub_question="S1.1", url=ASYNCIO_URL, quote="An event loop runs in a single thread "
                          "and multiplexes many sockets", char_start=0, char_end=10, content_sha256="0" * 64,
                          retrieved_at=datetime.now(UTC), host="docs.python.org")]
    llm = FakeLLM(default=None).on_schema(synthesize.SynthesisAnswer, {"claims": [
        {"sub_question": "S1.1", "text": "One asyncio event loop thread can multiplex many sockets.",
         "evidence_ids": ["E1"]},
        {"sub_question": "S1.1", "text": "Threads are deprecated in Python 3.13.", "evidence_ids": []},
        {"sub_question": "S1.1", "text": "Rust is a memory-safe language.", "evidence_ids": ["E1"]},
        {"sub_question": "S1.1", "text": "Cites a ghost.", "evidence_ids": ["E99"]}]})
    claims, sub_of, dropped, how = await synthesize.synthesize([SUB], evid, llm)
    assert how == "model" and [c.text for c in claims] == ["One asyncio event loop thread can multiplex many sockets."]
    assert sub_of == {"C1": "S1.1"} and len(dropped) == 3
    md = synthesize.summary_markdown(["Q?"], [SUB.model_copy(update={"question": 0, "coverage": 0.5})], claims, sub_of,
                                     evid, "all_covered")
    assert "[1]" in md and ASYNCIO_URL in md and "Stopped: all covered" in md
    issues = synthesize.check_claims([Claim(id="C9", text="x", evidence_ids=["E5"])], evid, {})
    assert issues[0].severity == "critical" and issues[0].location == "/claims/0"
