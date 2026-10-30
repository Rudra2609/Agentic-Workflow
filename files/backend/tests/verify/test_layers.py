"""Unit tests of the verification layers (6.1-6.6) — no infra, no model (FakeLLM or none)."""

import json
from pathlib import Path

import pytest

from hmap.agents.research.clean import page_from_text
from hmap.agents.research.model import Hit, Page
from hmap.agents.verify import aggregate, benchmark, claims, compare, entail, independent, mechanical, textual
from hmap.agents.verify.entail import EntailAnswer, Usage
from hmap.agents.verify.independent import Queries
from hmap.agents.verify.model import AtomCheck, ClaimCheck, Comparison, Judgement, L1Result, Passage, Quote
from hmap.agents.verify.pipeline import VerifyDeps
from hmap.core.llm import FakeLLM

GOLD = benchmark.BENCH_DIR / "atomic_gold.jsonl"
TEXT = ("A thread-per-client server is simple to write. In CPython the global interpreter lock lets only one thread "
        "execute Python bytecode at a time. The default pool uses 20 worker threads.")
URL = "https://en.wikipedia.org/wiki/Thread_(computing)"


def page(text: str = TEXT, url: str = URL) -> Page:
    return page_from_text(text, url=url, title="Thread", kind="wiki", provider="seed", min_chars=10)


def quote(p: Page, q: str, eid: str = "E1") -> Quote:
    return Quote(id=eid, url=p.url, quote=q, content_sha256=p.content_sha256)


# ------------------------------------------------------------------------------------------------ 6.1 claims


def test_atomizer_matches_the_gold_splits() -> None:
    rows = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
    assert len(rows) >= 25
    for g in rows:
        atoms = claims.atomize("C1", g["claim"])
        assert [a.text for a in atoms] == g["atoms"], g["claim"]
        if "check_worthy" in g:
            assert [a.check_worthy for a in atoms] == g["check_worthy"]


def test_atom_ids_keep_the_claim_id() -> None:
    assert [a.atom_id for a in claims.atomize("C3", "X is fast; Y is slow today")] == ["C3.a", "C3.b"]
    assert [a.atom_id for a in claims.atomize("C3", "X is fast for sure")] == ["C3"]


# ---------------------------------------------------------------------------------------------- 6.2 L1


def test_l1_accepts_a_verbatim_quote_with_typography_differences() -> None:
    p = page()
    r = mechanical.check_quote(quote(p, "the global interpreter lock lets only one  thread execute"), p)
    assert r.ok and r.reason == "ok"


@pytest.mark.parametrize("case,reason", [
    ("altered", "quote_not_found"), ("missing", "page_missing"), ("tampered", "hash_mismatch"),
    ("other_version", "hash_mismatch"), ("url", "url_mismatch")])
def test_l1_rejects(case: str, reason: str) -> None:
    p = page()
    q = quote(p, "the global interpreter lock lets only one thread execute")
    if case == "altered":
        q = quote(p, "the global interpreter lock lets only two threads execute")
    elif case == "tampered":
        p = p.model_copy(update={"text": p.text + " Extra."})
    elif case == "other_version":
        q = q.model_copy(update={"content_sha256": "0" * 64})
    elif case == "url":
        q = q.model_copy(update={"url": "https://example.com/other"})
    r = mechanical.check_quote(q, None if case == "missing" else p)
    assert not r.ok and r.reason == reason


async def test_l1_on_the_benchmark_catches_every_fake_quote_and_nothing_else() -> None:
    items = benchmark.load()
    assert len(items) >= 60 + 20
    for it in items:
        res = await mechanical.check_claim([q.id for q in it.evidence], {q.id: q for q in it.evidence},
                                           benchmark.load_page)
        assert mechanical.passed(res) == (it.kind != "fake_quote"), it.id


async def test_l1_unknown_evidence_id_fails() -> None:
    res = await mechanical.check_claim(["E9"], {}, benchmark.load_page)
    assert res[0].reason == "unknown_evidence" and not mechanical.passed(res)


# ---------------------------------------------------------------------------------------------- 6.3 L2


def test_text_signals() -> None:
    assert textual.missing_numbers("a drop of 5% or more", "a drop of >= 20%") == {"5"}
    assert textual.missing_numbers("HS256 and RS256", "HMAC with SHA-256 (HS256) and RS256") == set()
    assert textual.missing_numbers("uses SHA-1", "uses SHA-256") == {"1"}
    assert textual.negated("it is not stateless") and not textual.negated("it is stateless")
    assert textual.site("https://en.wikipedia.org/wiki/X") == "wikipedia.org"


async def test_l2_model_verdict_with_both_orders() -> None:
    llm = FakeLLM(default=None).on_schema(EntailAnswer, EntailAnswer(verdict="supports", rationale="it says so"))
    usage = Usage()
    j = await entail.judge(llm, "Only one thread executes Python bytecode at a time in CPython",
                           [(URL, "In CPython the GIL lets only one thread execute Python bytecode at a time")],
                           usage=usage)
    assert j.label == "supports" and j.by == "model" and not j.unsure and usage.calls == 2
    first, second = llm.calls[0].messages[1].content, llm.calls[1].messages[1].content
    assert first.startswith("Claim:") and second.startswith("Source passages:")      # position-swap control
    assert "<<<PAGE source=" in first and "untrusted" in llm.calls[0].messages[0].content


async def test_l2_disagreeing_orders_are_unsure() -> None:
    llm = FakeLLM(default=None).on_schema(EntailAnswer, EntailAnswer(verdict="supports"),
                                          EntailAnswer(verdict="not_enough"))
    j = await entail.judge(llm, "claim text here", [(URL, "passage text here")])
    assert j.unsure


async def test_l2_number_guard_overrides_a_lenient_model() -> None:
    llm = FakeLLM(default=None).on_schema(EntailAnswer, EntailAnswer(verdict="supports"))
    j = await entail.judge(llm, "The pool uses 50 worker threads", [(URL, "The default pool uses 20 worker threads")])
    assert j.label == "not_enough" and "50" in j.guard


async def test_l2_without_a_model_the_rules_decide() -> None:
    j = await entail.judge(FakeLLM(default=None), "The default pool uses 20 worker threads",
                           [(URL, "The default pool uses 20 worker threads.")])
    assert j.by == "rules" and j.label == "supports"
    j2 = await entail.judge(None, "Bananas are blue fruit", [(URL, "The default pool uses 20 worker threads.")])
    assert j2.label == "not_enough"


# ---------------------------------------------------------------------------------------------- 6.4 L3


class Provider:
    name, kind, network = "fake", "web", True

    def __init__(self, hits: list[str]) -> None:
        self.hits, self.calls = hits, []  # type: ignore[var-annotated]

    async def search(self, query: str, k: int = 5) -> list[Hit]:
        self.calls.append(query)
        return [Hit(provider="fake", url=u, query=query) for u in self.hits[:k]]


async def test_l3_uses_its_own_queries_and_skips_the_cited_page() -> None:
    other = page("Python threads are limited: only one thread at a time executes Python bytecode in CPython because "
                 "of the GIL.", url="https://docs.python.org/3/glossary.html")
    pages = {URL: page(), other.url: other}

    async def lookup(hit: Hit) -> Page | None:
        return pages.get(hit.url)

    llm = FakeLLM(default=None).on_schema(Queries, Queries(queries=["python gil one thread bytecode"]))
    prov = Provider([URL, other.url])
    out = await independent.retrieve("Only one thread executes Python bytecode at a time", providers=[prov],
                                     lookup=lookup, exclude_urls={URL}, llm=llm, usage=Usage())
    assert prov.calls == ["python gil one thread bytecode"]
    assert out.passages and {p.url for p in out.passages} == {other.url}
    assert "Claim:" in llm.calls[0].messages[1].content and len(llm.calls[0].messages) == 2   # claim only


async def test_l3_rule_query_without_a_model() -> None:
    qs = await independent.make_queries(None, "The GIL restricts threading performance for CPU-bound work", Usage())
    assert qs and "gil" in qs[0]


# ---------------------------------------------------------------------------------------------- 6.5 L4


def test_l4_signals() -> None:
    assert compare.signals("released in 2019 with 20 threads", "released in 2021 with 50 threads") == [
        "number 20, 2019 vs 2021, 50", "year 2019 vs 2021"]
    assert compare.signals("JWT is stateless", "JWT is not stateless") == ["negation"]


async def test_l4_rules_and_model() -> None:
    p = Passage(url="https://x.example.test/a", host="x.example.test", text="JWT authentication is not stateless",
                overlap=0.9)
    [c] = await compare.compare("JWT authentication is stateless", [p], llm=None, usage=Usage())
    assert c.conflict and c.judgement and c.judgement.by == "rules"
    llm = FakeLLM(default=None).on_schema(EntailAnswer, EntailAnswer(verdict="supports"))
    [c2] = await compare.compare("JWT authentication is stateless", [p], llm=llm, usage=Usage())
    assert c2.agrees and len(llm.calls) == 1                                  # no position swap in L4
    assert compare.independent_sites([c2], ["https://en.wikipedia.org/wiki/JWT"]) == ["example.test"]


# ---------------------------------------------------------------------------------------------- 6.6 table


def atom(**kw: object) -> AtomCheck:
    base: dict[str, object] = {"atom_id": "C1", "text": "x", "l1": [L1Result(evidence_id="E1", ok=True, reason="ok")]}
    base.update(kw)
    return AtomCheck.model_validate(base)


ALL = frozenset({"l1", "l2", "l3", "l4"})
SUP = Judgement(label="supports")
CONFLICT = Comparison(passage=Passage(url="https://o.test/a", host="o.test", text="t"),
                      judgement=Judgement(label="refutes"))
AGREE = Comparison(passage=Passage(url="https://o.test/a", host="o.test", text="t"),
                   judgement=Judgement(label="supports"))


@pytest.mark.parametrize("a,layers,row,verdict", [
    (atom(l1=[L1Result(evidence_id="E1", ok=False, reason="quote_not_found")]), ALL, "R1", "UNSUPPORTED"),
    (atom(), frozenset({"l1"}), "R2", "VERIFIED"),
    (atom(l2=Judgement(label="refutes")), ALL, "R3", "UNSUPPORTED"),
    (atom(l2=Judgement(label="supports", swapped_label="not_enough")), ALL, "R4", "NEEDS_MORE_RESEARCH"),
    (atom(l2=Judgement(label="not_enough")), ALL, "R5", "UNSUPPORTED"),
    (atom(l2=SUP, l4=[CONFLICT]), ALL, "R6", "CONFLICTING"),
    (atom(l2=SUP, l4=[AGREE], independent_hosts=["o.test"]), ALL, "R7", "VERIFIED"),
    (atom(l2=SUP), ALL, "R8", "VERIFIED"),
])
def test_decision_table_rows(a: AtomCheck, layers: frozenset[str], row: str, verdict: str) -> None:
    out = aggregate.decide(a, layers)
    assert (out.row, out.verdict) == (row, verdict)
    assert out.confidence == aggregate.CONFIDENCE[row] and out.explanation


def test_every_row_has_a_test_and_a_confidence() -> None:
    assert [r.id for r in aggregate.TABLE] == [f"R{i}" for i in range(1, 9)]
    assert set(aggregate.CONFIDENCE) == {r.id for r in aggregate.TABLE}


def test_rules_judgements_are_capped() -> None:
    out = aggregate.decide(atom(l2=Judgement(label="supports", by="rules")), ALL)
    assert out.confidence == aggregate.RULES_CAP


def test_roll_up_worst_part_wins_and_follow_up_questions() -> None:
    c = ClaimCheck(claim_id="C1", text="JWTs are stateless", evidence_ids=["E1"], atoms=[
        aggregate.decide(atom(atom_id="C1.a", l2=SUP), ALL),
        aggregate.decide(atom(atom_id="C1.b", l2=Judgement(label="not_enough")), ALL)])
    aggregate.roll_up(c)
    assert c.verdict == "UNSUPPORTED" and "[C1.a]" in c.explanation
    assert aggregate.follow_up_questions([c]) == ["Is it true that JWTs are stateless?"]


async def test_benchmark_without_a_model_runs_every_layer() -> None:
    items = benchmark.load()[:12]
    deps = VerifyDeps(llm=None, load_page=benchmark.load_page)
    for it in items:
        c = await benchmark.verify_item(it, deps)
        assert c.verdict in aggregate.SEVERITY and c.atoms


def test_paths_exist() -> None:
    assert Path(benchmark.BENCHMARK).is_file() and Path(benchmark.PAGES_DIR).is_dir()
