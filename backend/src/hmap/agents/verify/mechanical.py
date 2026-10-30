"""L1 — the mechanical check (Sprint 6 item 6.2). Deterministic and free: no model.

For every piece of evidence a claim cites:

1. the saved page exists (the ``research-page`` artifact Member 5 stored, or the benchmark's page file);
2. its text hashes to the page's ``content_sha256`` **and** to the evidence's ``content_sha256`` (the page was not
   changed and the evidence points at this page);
3. the evidence URL is the page's URL (or its final URL after redirects);
4. the quote is verbatim in the text (Member 5's :func:`hmap.agents.research.quotes.locate`: typography-insensitive,
   never word-insensitive).

A claim passes L1 only when every evidence id it cites passes (a single invented quote is enough to distrust it).
"""

from collections.abc import Awaitable, Callable, Sequence

from hmap.agents.research import quotes
from hmap.agents.research.model import Page, sha256_text
from hmap.agents.verify.model import L1Result, Quote

PageLoader = Callable[[Quote], Awaitable[Page | None]]


def _same_url(a: str, b: str) -> bool:
    return a.strip().rstrip("/") == b.strip().rstrip("/")


def check_quote(q: Quote, page: Page | None) -> L1Result:
    if page is None:
        return L1Result(evidence_id=q.id, ok=False, reason="page_missing", detail="the saved page is not available")
    actual = sha256_text(page.text)
    if actual != page.content_sha256:
        return L1Result(evidence_id=q.id, ok=False, reason="hash_mismatch",
                        detail="the saved page text does not match its own hash (changed after saving)")
    if q.content_sha256 != actual:
        return L1Result(evidence_id=q.id, ok=False, reason="hash_mismatch",
                        detail="the evidence hash points at a different page version")
    if not (_same_url(q.url, page.url) or (page.final_url and _same_url(q.url, page.final_url))):
        return L1Result(evidence_id=q.id, ok=False, reason="url_mismatch",
                        detail=f"evidence URL {q.url} is not the saved page's URL {page.url}")
    if quotes.locate(q.quote, page.text) is None:
        return L1Result(evidence_id=q.id, ok=False, reason="quote_not_found",
                        detail="the quote is not in the saved page word for word")
    return L1Result(evidence_id=q.id, ok=True, reason="ok")


async def check_claim(evidence_ids: Sequence[str], evidence: dict[str, Quote], load: PageLoader) -> list[L1Result]:
    out: list[L1Result] = []
    for eid in evidence_ids:
        q = evidence.get(eid)
        if q is None:
            out.append(L1Result(evidence_id=eid, ok=False, reason="unknown_evidence",
                                detail="the claim cites evidence the report does not contain"))
            continue
        out.append(check_quote(q, await load(q)))
    return out


def passed(results: Sequence[L1Result]) -> bool:
    return bool(results) and all(r.ok for r in results)
