"""Documentation: ungrounded sentences (Member 9's accuracy report) and, for a document project, whether the
requirement is answered by a section (Member 9's report coverage)."""

from hmap.agents.review.model import Check, Item


def check(item: Item) -> Check | None:
    ev = item.evidence
    if ev.doc_status == "not shown" and item.mode == "document":
        return Check(verdict="FAIL", category="MISSING", reasons=["no section of the document answers it"])
    if ev.doc_ungrounded:
        return Check(verdict="PARTIAL", category="DOC_MISMATCH",
                     reasons=["ungrounded in the docs: " + "; ".join(ev.doc_ungrounded[:5])])
    if ev.doc_status == "conflict":
        return Check(verdict="PARTIAL", category="DOC_MISMATCH",
                     reasons=["the document's section conflicts with the verified research"])
    if ev.doc_status == "shown" and item.mode == "document":
        return Check(verdict="PASS", reasons=["answered by a section of the document"])
    return None
