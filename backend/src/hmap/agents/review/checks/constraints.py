"""Constraints and human change requests ("use Python only", "don't use asyncio") against the facts of the code
(Member 9's ``docgen-facts``); a violation found in :mod:`hmap.agents.review.evidence` is a FAIL."""

from hmap.agents.review.model import Check, Item


def check(item: Item) -> Check | None:
    if item.kind not in ("constraint", "change"):
        return None
    if item.evidence.violations:
        return Check(verdict="FAIL", category="INCORRECT", reasons=item.evidence.violations[:5])
    if item.evidence.facts:
        return Check(verdict="PASS", reasons=item.evidence.facts[:3])
    return None
