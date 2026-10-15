"""Index (5.5: chunking, hybrid retrieval, project isolation, keyword-only fallback) and selection (5.6)."""

from hmap.agents.research.index import HybridIndex, MemoryBackend, chunk_page
from hmap.agents.research.select import authority, recency, select
from hmap.core.llm import FakeLLM
from tests.research.conftest import ASYNCIO_URL, SELECTORS_URL, TEXTS, THREAD_URL, make_page


def test_chunks_are_sentence_aligned_overlapping_and_point_into_the_text() -> None:
    text = " ".join(f"Sentence number {n} talks about sockets and event loops in detail." for n in range(60))
    page = make_page("https://a.org/x", "X", text)
    chunks = chunk_page(page, size=300, overlap=80)
    assert len(chunks) > 5
    for c in chunks:
        assert page.text[c.start:c.end] == c.text and c.text.startswith("Sentence") and c.text.endswith(".")
        assert len(c.text) <= 300 + 80
    assert any(chunks[i].end > chunks[i + 1].start for i in range(len(chunks) - 1))       # overlap
    assert chunks[-1].end == len(page.text)


async def test_hybrid_search_isolation_reindex_and_delete() -> None:
    llm = FakeLLM()
    index = HybridIndex(embed=llm.embed, backend=MemoryBackend())
    for url, (title, kind, text) in TEXTS.items():
        assert await index.add("P1", make_page(url, title, text, kind)) >= 1
    assert await index.add("P1", make_page(ASYNCIO_URL, *TEXTS[ASYNCIO_URL][:1], TEXTS[ASYNCIO_URL][2])) == 0
    hits = await index.search("P1", "global interpreter lock threads", k=3)
    assert hits[0].chunk.url == THREAD_URL and hits[0].keyword_rank == 0 and 0 < hits[0].relevance <= 1
    only = await index.search("P1", "multiplexing epoll", k=3, urls={SELECTORS_URL})
    assert {h.chunk.url for h in only} == {SELECTORS_URL}
    assert await index.search("P2", "threads", k=3) == []                                 # another project
    assert await index.delete_project("P1") >= 3 and await index.search("P1", "threads") == []


async def test_without_embeddings_the_index_falls_back_to_keywords() -> None:
    async def broken(texts: list[str]) -> list[list[float]]:
        raise RuntimeError("no Ollama")

    index = HybridIndex(embed=broken, backend=MemoryBackend())
    for url, (title, kind, text) in TEXTS.items():
        await index.add("P1", make_page(url, title, text, kind))
    hits = await index.search("P1", "event loop coroutines sockets", k=2)
    assert index.keyword_only and index.embed_error == "RuntimeError"
    assert hits[0].chunk.url == ASYNCIO_URL and hits[0].dense_rank is None


def test_authority_and_recency() -> None:
    assert authority("https://docs.python.org/3/library/asyncio.html") == 1.0
    assert authority("https://en.wikipedia.org/wiki/X") == 0.9
    assert authority("https://www.pinterest.com/pin/1") < authority("https://medium.com/x") < authority(
        "https://stackoverflow.com/q/1")
    assert authority("project://doc") == 0.8 and authority("https://unknown.example/") == 0.6
    assert recency("2010-01-01", "how does TCP work") == 1.0                       # timeless question
    assert recency("2018-01-01", "what is the latest Python release") < recency("2026-01-01",
                                                                                "what is the latest Python release")


async def test_select_keeps_a_breakdown_and_drops_near_duplicates() -> None:
    llm = FakeLLM()
    index = HybridIndex(embed=llm.embed, backend=MemoryBackend())
    text = TEXTS[THREAD_URL][2]
    await index.add("P", make_page(THREAD_URL, "Thread", text, "wiki"))
    await index.add("P", make_page("https://mirror.example/thread", "Thread copy", text))     # same text elsewhere
    await index.add("P", make_page(ASYNCIO_URL, "asyncio", TEXTS[ASYNCIO_URL][2]))
    retrieved = await index.search("P", "threads interpreter lock memory", k=6)
    chosen = select(retrieved, question="threads or asyncio", k=3)
    urls = [s.chunk.url for s in chosen]
    assert len(urls) == len(set(urls)) and not ({THREAD_URL, "https://mirror.example/thread"} <= set(urls))
    for s in chosen:
        assert set(s.breakdown) == {"relevance", "authority", "recency", "novelty"} and 0 < s.score <= 1
