"""Evidence extraction with quote-must-match (Sprint 5 item 5.7, plan D9).

1. **Triage** (``fast``, one batched call per round): which selected chunks really help with their sub-question.
2. **Extraction** (``reasoner``, at most 4 chunks / 6 000 characters per call): for each useful chunk, a short
   verbatim quote, the sub-question it supports and why.
3. **Check in code**: a quote must be a verbatim substring of the page's cleaned text (``quotes.locate``); if not,
   it is dropped and counted (``quotes_dropped``) — so the report can contain no invented quote.

Without a model the rules pick, per chunk, the sentence that shares most words with the sub-question (verbatim by
construction). Page text is always passed wrapped as untrusted data (``sanitize.wrap``).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from hmap.agents.research import quotes, sanitize
from hmap.agents.research.index import split_sentences
from hmap.agents.research.model import EvidenceDraft, Page, Scored
from hmap.core.contracts.domain import SubQuestion
from hmap.core.errors import Cancelled
from hmap.core.llm.base import LLMClient
from hmap.core.tracing import get_logger

log = get_logger("hmap.research.evidence")
PROMPT_VERSION = "2"
TRIAGE_CHARS = 500
BATCH_CHUNKS = 4
BATCH_CHARS = 6000


class TriageAnswer(BaseModel):
    relevant: list[str] = Field(default_factory=list, description="ids (C1, C2, ...) of the passages that help answer "
                                                                  "their sub-question")


class ExtractedQuote(BaseModel):
    passage: str = Field(description="passage id, e.g. C3")
    sub_question: str = Field(description="sub-question id, e.g. S1.2")
    quote: str = Field(description="one or two sentences copied EXACTLY from the passage (20-400 characters)")
    why: str = Field(default="", description="how the quote answers the sub-question, in a few words")


class ExtractAnswer(BaseModel):
    evidence: list[ExtractedQuote] = Field(default_factory=list)


TRIAGE_SYSTEM = ("You check search results. For each passage decide whether it contains information that helps "
                 "answer its sub-question. " + sanitize.UNTRUSTED_NOTE + " Answer with the ids of the helpful "
                 "passages only.")
EXTRACT_SYSTEM = ("You collect evidence for a research report. For every passage that says something useful for its "
                  "sub-question — a definition, how something works, a trade-off, a limit, a number, a "
                  "recommendation — copy 1 to 3 sentences that state it, EXACTLY as written (no paraphrase, no "
                  "shortening inside a sentence, no added words), and say which sub-question each supports. Partial "
                  "answers count. Skip only passages with nothing relevant. " + sanitize.UNTRUSTED_NOTE)


@dataclass
class Candidate:
    """A selected chunk with its sub-question and page."""

    cid: str
    sub: SubQuestion
    scored: Scored
    page: Page


@dataclass
class Extraction:
    evidence: list[EvidenceDraft] = field(default_factory=list)
    triaged: int = 0
    relevant: int = 0
    proposed: int = 0
    dropped: int = 0
    dropped_quotes: list[str] = field(default_factory=list)


TRIAGE_ABOVE = 8     # triage pays off only for many passages; a few go straight to extraction (which decides too)


async def triage(cands: Sequence[Candidate], llm: LLMClient | None) -> list[Candidate]:
    if llm is None or len(cands) <= TRIAGE_ABOVE:
        return list(cands)
    blocks = [f"[{c.cid}] sub-question {c.sub.id}: {c.sub.text}\n"
              f"{sanitize.wrap(c.scored.chunk.text[:TRIAGE_CHARS], source=c.page.host or 'local')}" for c in cands]
    try:
        resp = await llm.generate("fast", [{"role": "system", "content": TRIAGE_SYSTEM},
                                           {"role": "user", "content": "\n\n".join(blocks)}],
                                  schema=TriageAnswer, max_tokens=300, temperature=0.0)
        keep = {x.strip().upper() for x in resp.parsed.relevant}
    except Cancelled:
        raise
    except Exception as exc:  # triage is an optimisation: on failure keep everything
        log.info("research triage skipped", error=type(exc).__name__)
        return list(cands)
    chosen = [c for c in cands if c.cid.upper() in keep]
    return chosen or list(cands[: max(1, len(cands) // 2)])


def rule_quote(sub: SubQuestion, text: str) -> str | None:
    """The sentence of ``text`` that shares most words with the sub-question (≥ 2 words), verbatim."""
    want = quotes.words(sub.text + " " + " ".join(sub.queries))
    best: tuple[int, int, str] | None = None
    for n, (s, e) in enumerate(split_sentences(text)):
        sent = text[s:e].strip()
        if not (quotes.MIN_QUOTE_CHARS <= len(sent) <= 400):
            continue
        overlap = len(want & quotes.words(sent))
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, n, sent)
    return best[2] if best else None


def _accept(c: Candidate, quote: str, why: str, out: Extraction, next_id: int,
            known: set[tuple[str, int]]) -> bool:
    # look inside the chunk first (the passage the model saw), then the whole page
    span = quotes.locate(quote, c.scored.chunk.text)
    if span is not None:
        start, end = span[0] + c.scored.chunk.start, span[1] + c.scored.chunk.start
    else:
        page_span = quotes.locate(quote, c.page.text)
        if page_span is None:
            out.dropped += 1
            out.dropped_quotes.append(quote[:120])
            return False
        start, end = page_span
    if (c.page.url, start) in known or any(o.url == c.page.url and o.char_start < end and start < o.char_end
                                           for o in out.evidence):
        return False                       # the same passage again (or overlapping it): not new evidence
    known.add((c.page.url, start))
    out.evidence.append(EvidenceDraft(
        id=f"E{next_id}", sub_question=c.sub.id, url=c.page.url, title=c.page.title, quote=c.page.text[start:end],
        char_start=start, char_end=end, content_sha256=c.page.content_sha256, retrieved_at=c.page.retrieved_at,
        why=why[:200], host=c.page.host))
    return True


async def extract(cands: Sequence[Candidate], llm: LLMClient | None, *, first_id: int,
                  known: set[tuple[str, int]]) -> Extraction:
    out = Extraction(triaged=len(cands))
    useful = await triage(cands, llm)
    out.relevant = len(useful)
    next_id = first_id
    if llm is None:
        for c in useful:
            q = rule_quote(c.sub, c.scored.chunk.text)
            if q is not None:
                out.proposed += 1
                if _accept(c, q, "shares the sub-question's key words", out, next_id, known):
                    next_id += 1
        return out
    batches: list[list[Candidate]] = []
    for c in useful:
        if not batches or len(batches[-1]) >= BATCH_CHUNKS or \
                sum(len(x.scored.chunk.text) for x in batches[-1]) + len(c.scored.chunk.text) > BATCH_CHARS:
            batches.append([])
        batches[-1].append(c)
    for batch in batches:
        by_id = {c.cid.upper(): c for c in batch}
        subs = {c.sub.id: c.sub.text for c in batch}
        user = "Sub-questions:\n" + "\n".join(f"{k}: {v}" for k, v in subs.items()) + "\n\nPassages:\n\n" + \
            "\n\n".join(f"[{c.cid}] (for {c.sub.id})\n"
                        f"{sanitize.wrap(c.scored.chunk.text, source=c.page.host or 'local')}" for c in batch)
        try:
            resp = await llm.generate("reasoner", [{"role": "system", "content": EXTRACT_SYSTEM},
                                                   {"role": "user", "content": user}], schema=ExtractAnswer,
                                      max_tokens=1200, temperature=0.0)
            items = resp.parsed.evidence
        except Cancelled:
            raise
        except Exception as exc:
            log.info("research extraction fell back to rules for a batch", error=type(exc).__name__)
            items = [ExtractedQuote(passage=c.cid, sub_question=c.sub.id, quote=q, why="rule")
                     for c in batch if (q := rule_quote(c.sub, c.scored.chunk.text))]
        for item in items:
            found = by_id.get(item.passage.strip().upper())
            if found is None:
                continue
            c = found
            out.proposed += 1
            if item.sub_question.strip() and item.sub_question.strip() != c.sub.id:
                # the model may assign a quote to another sub-question of the same batch
                other = next((x for x in batch if x.sub.id == item.sub_question.strip()), None)
                if other is not None and other.page.url == c.page.url:
                    c = other
            if _accept(c, item.quote, item.why, out, next_id, known):
                next_id += 1
    return out
