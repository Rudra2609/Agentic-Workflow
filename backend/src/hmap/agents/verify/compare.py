"""L4 — cross-source comparison and conflict detection (Sprint 6 item 6.5).

The claim (already supported by its own quotes) is compared with passages from **other** sources: the ones L3 found
and any counter-sources handed in. Two steps, cheapest first:

1. **rule signals** per passage: a different number for the same thing, a different year, opposite negation
   ("is stateless" vs "is not stateless"); recorded for the explanation and used to choose what the judge sees;
2. **judge** (role ``judge``, the L2 prompt, no position swap) on the rule-flagged passages and the best-overlapping
   ones, at most :data:`MAX_JUDGED`. ``refutes`` = a conflict; ``supports`` from another site = agreement.

Domain diversity: agreement counts per *site* (``en.wikipedia.org`` and ``de.wikipedia.org`` are one site), and a
site already cited by the claim does not count as independent. Date precedence: when two sources disagree and both
carry a date, the explanation names the newer one (the verdict stays CONFLICTING; a human decides).
"""

from collections.abc import Sequence

from hmap.agents.verify import entail, textual
from hmap.agents.verify.entail import Usage
from hmap.agents.verify.model import Comparison, Judgement, Passage
from hmap.core.llm.base import LLMClient

MAX_JUDGED = 3
RULE_OVERLAP = 0.5


def signals(claim: str, passage: str) -> list[str]:
    out: list[str] = []
    cn, pn = textual.numbers(claim), textual.numbers(passage)
    if cn and pn and not (cn & pn):
        out.append(f"number {', '.join(sorted(cn))} vs {', '.join(sorted(pn)[:3])}")
    cy, py = textual.years(claim), textual.years(passage)
    if cy and py and not (cy & py):
        out.append(f"year {', '.join(sorted(cy))} vs {', '.join(sorted(py))}")
    if textual.negated(claim) != textual.negated(passage):
        out.append("negation")
    return out


async def compare(claim: str, passages: Sequence[Passage], *, llm: LLMClient | None, usage: Usage,
                  max_judged: int = MAX_JUDGED) -> list[Comparison]:
    comps = [Comparison(passage=p, signals=signals(claim, p.text)) for p in passages]
    # counter-sources first, then rule-flagged, then by overlap
    def rank(i: int) -> tuple[bool, bool, float]:
        c = comps[i]
        return (c.passage.origin != "counter", not (c.signals and c.passage.overlap >= RULE_OVERLAP),
                -c.passage.overlap)

    order = sorted(range(len(comps)), key=rank)
    for i in order[:max_judged]:
        c = comps[i]
        if llm is None:
            # rules only: a strong-overlap passage with a conflicting number or negation is a conflict
            if c.signals and c.passage.overlap >= RULE_OVERLAP:
                c.judgement = Judgement(label="refutes", rationale="; ".join(c.signals), by="rules")
            else:
                c.judgement = Judgement(label="not_enough", rationale="no conflicting signal", by="rules")
            continue
        c.judgement = await entail.judge(llm, claim, [(c.passage.url, c.passage.text)], swap=False, use_guard=False,
                                         usage=usage)
    return comps


def independent_sites(comps: Sequence[Comparison], cited_urls: Sequence[str]) -> list[str]:
    cited = {textual.site(u) for u in cited_urls}
    return sorted({textual.site(c.passage.url) for c in comps if c.agrees} - cited)


def newer_source(comps: Sequence[Comparison]) -> str:
    dated = [c for c in comps if c.conflict and c.passage.published]
    if not dated:
        return ""
    newest = max(dated, key=lambda c: str(c.passage.published))
    return f"the newest conflicting source is {newest.passage.host} ({newest.passage.published})"
