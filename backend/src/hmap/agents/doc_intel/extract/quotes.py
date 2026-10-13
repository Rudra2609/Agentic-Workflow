"""Quote verification (spec §9 "quote required"): every extracted item must quote its source; the quote is looked
up in the chunk's blocks. Exact (after normalising whitespace, case, quotes and dashes) -> verified; mostly the same
words -> approximate; otherwise unverified (the item keeps a low confidence and an open question)."""

import re
from dataclasses import dataclass

from hmap.agents.doc_intel.model import Block

WORD_RE = re.compile(r"[a-z0-9]+(?:['.][a-z0-9]+)*")
_TRANS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
                        "\u00a0": " "})
STOPWORDS = frozenset({"a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "at", "by", "with", "be", "is",
                       "are", "it", "this", "that", "as", "from"})


def normalize(text: str) -> str:
    text = text.translate(_TRANS).lower()
    text = re.sub(r"^\s*(?:[-*\u2022]|\d{1,2}[.)])\s+", "", text)
    return re.sub(r"\s+", " ", text).strip(" .;:")


def words(text: str) -> list[str]:
    return WORD_RE.findall(normalize(text))


def overlap(a: str, b: str) -> float:
    """Share of ``a``'s content words that appear in ``b`` (0..1)."""
    wa = [w for w in words(a) if w not in STOPWORDS] or words(a)
    if not wa:
        return 0.0
    wb = set(words(b))
    return sum(1 for w in wa if w in wb) / len(wa)


def jaccard(a: str, b: str) -> float:
    sa, sb = set(words(a)) - STOPWORDS, set(words(b)) - STOPWORDS
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class QuoteMatch:
    block: Block | None
    status: str                      # exact | approximate | unverified
    char_span: tuple[int, int] | None = None  # within SourceDocument.text
    score: float = 0.0


def locate(quote: str, blocks: list[Block], fallback_text: str = "") -> QuoteMatch:
    """Find ``quote`` (or, without one, ``fallback_text``) in ``blocks``."""
    needle = normalize(quote or fallback_text)
    if not needle:
        return QuoteMatch(None, "unverified")
    for block in blocks:
        hay = normalize(block.text)
        pos = hay.find(needle)
        if pos >= 0 and quote:
            raw = block.text.lower().translate(_TRANS).find(quote.strip().lower().translate(_TRANS)[:40])
            start = block.char_start + (raw if raw >= 0 else 0)
            end = start + len(quote.strip()) if raw >= 0 else block.char_end
            return QuoteMatch(block, "exact", (start, min(end, block.char_end)), 1.0)
    best_score, best_block = 0.0, None
    for block in blocks:
        score = overlap(needle, block.text)
        if score > best_score:
            best_score, best_block = score, block
    if best_block is not None and best_score >= 0.75:
        return QuoteMatch(best_block, "approximate", (best_block.char_start, best_block.char_end), best_score)
    return QuoteMatch(best_block if best_score >= 0.4 else None, "unverified", None, best_score)
