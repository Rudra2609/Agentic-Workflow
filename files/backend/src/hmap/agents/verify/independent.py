"""L3 — independent retrieval (Sprint 6 item 6.4).

The verifier searches again **on its own**: its query generator sees only the claim text (never the research brief,
the sub-questions or the researcher's queries), and the pages the claim already cites are excluded, so whatever L3
finds is a second opinion, not the researcher's own source read twice.

Search uses Member 5's public providers (``hmap.agents.research.providers``) behind **the verifier's own search
cache** (``samples/verify/search_cache`` committed + ``HMAP_VERIFY_CACHE_DIR``), obeying the research mode: offline
(``cached``) only the cache and the local corpus answer, so the demo needs no network. From each page the sentences
that share most content words with the claim become candidate passages for L4.

Queries: role ``fast`` with a small schema; without a model, the claim's content words.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from hmap.agents.research.index import split_sentences
from hmap.agents.research.model import Hit, Page
from hmap.agents.verify import textual
from hmap.agents.verify.entail import Usage
from hmap.agents.verify.model import Passage
from hmap.core.errors import Cancelled
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.verify.independent")
MAX_QUERIES = 2
HITS_PER_QUERY = 4
MAX_PASSAGES = 4
PER_PAGE = 2
MIN_OVERLAP = 0.3

PageLookup = Callable[[Hit], Awaitable[Page | None]]


class Queries(BaseModel):
    queries: list[str] = Field(default_factory=list, max_length=4,
                               description="1-2 short web search queries (3-8 words) that would find sources "
                                           "confirming or contradicting the claim")


QUERY_SYSTEM = ("You write web search queries to fact-check a claim. Write 1 or 2 short, neutral queries (3-8 "
                "words, no quotes, no site: filters) that find independent sources about what the claim states. "
                "Answer in JSON.")


@dataclass
class Retrieval:
    queries: list[str] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    pages_seen: int = 0


def rule_query(claim: str) -> str:
    words: list[str] = []
    for w in textual.content_words(claim):
        if w not in words:
            words.append(w)
    return " ".join(words[:7])


async def make_queries(llm: LLMClient | None, claim: str, usage: Usage) -> list[str]:
    if llm is not None:
        try:
            resp = await llm.generate("fast", [{"role": "system", "content": QUERY_SYSTEM},
                                               {"role": "user", "content": f"Claim: {claim}"}],
                                      schema=Queries, max_tokens=200, temperature=0.0)
            usage.calls += 1
            usage.tokens += resp.usage.input_tokens + resp.usage.output_tokens
            parsed = resp.parsed if isinstance(resp.parsed, Queries) else Queries.model_validate(resp.parsed)
            out = [" ".join(q.split())[:120] for q in parsed.queries if q.strip()][:MAX_QUERIES]
            if out:
                return out
        except Cancelled:
            raise
        except Exception as exc:
            usage.errors.append(type(exc).__name__)
    q = rule_query(claim)
    return [q] if q else []


def best_passages(claim: str, page: Page, *, origin: Literal["independent", "counter"] = "independent",
                  query: str = "") -> list[Passage]:
    scored: list[tuple[float, str]] = []
    for s, e in split_sentences(page.text):
        sent = " ".join(page.text[s:e].split())
        if len(sent) < 30:
            continue
        ov = textual.overlap(claim, sent)
        if ov >= MIN_OVERLAP:
            scored.append((ov, sent))
    scored.sort(key=lambda x: -x[0])
    return [Passage(url=page.url, host=textual.host(page.url), title=page.title, text=t[:600], overlap=round(ov, 3),
                    origin=origin, query=query, published=page.published)
            for ov, t in scored[:PER_PAGE]]


async def retrieve(claim: str, *, providers: Sequence[object], lookup: PageLookup, exclude_urls: set[str],
                   llm: LLMClient | None, usage: Usage) -> Retrieval:
    """Search with the verifier's own queries; candidate passages from pages the claim does not already cite."""
    out = Retrieval(queries=await make_queries(llm, claim, usage))
    seen: set[str] = {u.rstrip("/") for u in exclude_urls}
    passages: list[Passage] = []
    for query in out.queries:
        for provider in providers:
            try:
                hits: list[Hit] = await provider.search(query, k=HITS_PER_QUERY)  # type: ignore[attr-defined]
            except Cancelled:
                raise
            except Exception as exc:  # one provider down never stops verification
                log.info("independent search failed", provider=getattr(provider, "name", "?"),
                         error=type(exc).__name__)
                continue
            for hit in hits:
                key = hit.url.rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                page = await lookup(hit)
                if page is None:
                    continue
                out.pages_seen += 1
                passages.extend(best_passages(claim, page, query=query))
    passages.sort(key=lambda p: -p.overlap)
    out.passages = passages[:MAX_PASSAGES]
    return out
