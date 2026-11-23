"""Research claims the item relies on are supported by their sources (Member 6's verdicts)."""

from collections import Counter

from hmap.agents.review.model import Check, Item


def check(item: Item) -> Check | None:
    vs = item.evidence.verification
    if not vs:
        return None
    count = Counter(v.verdict for v in vs)
    bad = [v.claim for v in vs if v.verdict != "supported"]
    if count["contradicted"] or count["unsupported"] == len(vs):
        return Check(verdict="FAIL", category="UNSUPPORTED_CLAIM", reasons=["not supported: " + "; ".join(bad)])
    if bad:
        return Check(verdict="PARTIAL", category="UNSUPPORTED_CLAIM", reasons=["not supported: " + "; ".join(bad)])
    return Check(verdict="PASS", reasons=[f"{len(vs)} claim(s) verified against their sources"])
