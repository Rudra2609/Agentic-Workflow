"""Output of a stub agent cannot be judged or revised (plan T6, Q8): PARTIAL, no action."""

from hmap.agents.review.model import Check, Item


def check(item: Item) -> Check | None:
    if not item.evidence.stub:
        return None
    return Check(verdict="PARTIAL", reasons=["produced by a stub agent (placeholder output, not reviewed)"],
                 no_action=True)
